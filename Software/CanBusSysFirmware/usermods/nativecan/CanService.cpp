#include "CanService.hpp"

extern "C" {
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
}

#include <cstring>

namespace {

// The supplied labels are XIAO D-pin labels, not ESP32-S3 GPIO numbers:
// D16=GPIO10, D17=GPIO13, D18=GPIO12, D19=GPIO11 and D13=GPIO40.
// SPI2 is the second general-purpose SPI peripheral; SPI1 remains reserved
// for flash/PSRAM.
constexpr spi_host_device_t kSpiHost = SPI2_HOST;
constexpr gpio_num_t kSck = GPIO_NUM_13;  // XIAO D17
constexpr gpio_num_t kMiso = GPIO_NUM_12; // XIAO D18
constexpr gpio_num_t kMosi = GPIO_NUM_11; // XIAO D19
constexpr gpio_num_t kCs = GPIO_NUM_10;   // XIAO D16
constexpr gpio_num_t kInt = GPIO_NUM_40;  // XIAO D13 (active-low MCP INT)
constexpr int kWorkerCore = 1;
constexpr uint32_t kSpiHz = 2 * 1000 * 1000; // conservative first-probe clock
constexpr size_t kQueueDepth = 32;

constexpr uint16_t kRegCiCon = 0x000;
constexpr uint16_t kRegOsc = 0xe00;
constexpr uint16_t kRegIoCon = 0xe04;
constexpr uint16_t kRegDevId = 0xe14;
constexpr uint16_t kRegEccCon = 0xe0c;
constexpr uint16_t kRamStart = 0x400;
constexpr uint16_t kTxFifoCon = 0x05c; // FIFO 1
constexpr uint16_t kTxFifoSta = 0x060;
constexpr uint16_t kTxFifoUa = 0x064;
constexpr uint16_t kRxFifoCon = 0x068; // FIFO 2
constexpr uint16_t kRxFifoSta = 0x06c;
constexpr uint16_t kRxFifoUa = 0x070;
constexpr uint16_t kFltCon0 = 0x1d0;
constexpr uint16_t kRegIntEnable = 0x01e;
constexpr uint8_t kSpiReset = 0x00;
constexpr uint8_t kSpiRead = 0x03;
constexpr uint8_t kSpiWrite = 0x02;
constexpr uint8_t kIoConXstbyEnable = 1u << 6;

struct ServiceState {
    QueueHandle_t tx_queue = nullptr;
    QueueHandle_t rx_queue = nullptr;
    SemaphoreHandle_t ready = nullptr;
    SemaphoreHandle_t mode_done = nullptr;
    spi_device_handle_t spi = nullptr;
    TaskHandle_t worker_task = nullptr;
    bool start_requested = false;
    volatile bool mode_change_pending = false;
    volatile bool requested_loopback = true;
    CanServiceStatus status{};
};

ServiceState g_state;

void IRAM_ATTR mcp_interrupt(void *) {
    BaseType_t higher_priority_task_woken = pdFALSE;
    vTaskNotifyGiveFromISR(g_state.worker_task, &higher_priority_task_woken);
    // The worker also has a short recovery timeout, so no ISR context switch
    // is required here (and this MicroPython/IDF configuration omits the
    // trace hook needed by portYIELD_FROM_ISR()).
}

bool spi_transfer(const uint8_t *tx, uint8_t *rx, size_t length) {
    spi_transaction_t transaction{};
    transaction.length = length * 8;
    transaction.tx_buffer = tx;
    transaction.rx_buffer = rx;
    return spi_device_transmit(g_state.spi, &transaction) == ESP_OK;
}

bool access_memory(uint8_t command, uint16_t address, const uint8_t *data, uint8_t *read, size_t length) {
    if (length > 80) return false;
    uint8_t tx[82]{};
    uint8_t rx[82]{};
    tx[0] = static_cast<uint8_t>((command << 4) | ((address >> 8) & 0x0f));
    tx[1] = static_cast<uint8_t>(address);
    if (data) std::memcpy(tx + 2, data, length);
    if (!spi_transfer(tx, rx, length + 2)) return false;
    if (read) std::memcpy(read, rx + 2, length);
    return true;
}

bool read_sfr(uint16_t address, uint8_t *data, size_t length) {
    // The MCP2518FD command is C<3:0> followed by A<11:0>.
    uint8_t tx[3 + 4]{};
    uint8_t rx[3 + 4]{};
    if (length > 4) {
        return false;
    }
    tx[0] = static_cast<uint8_t>((kSpiRead << 4) | ((address >> 8) & 0x0f));
    tx[1] = static_cast<uint8_t>(address);
    if (!spi_transfer(tx, rx, 2 + length)) {
        return false;
    }
    std::memcpy(data, rx + 2, length);
    return true;
}

bool write_u32(uint16_t address, uint32_t value) {
    uint8_t tx[6] = {static_cast<uint8_t>((kSpiWrite << 4) | ((address >> 8) & 0x0f)),
        static_cast<uint8_t>(address), static_cast<uint8_t>(value), static_cast<uint8_t>(value >> 8),
        static_cast<uint8_t>(value >> 16), static_cast<uint8_t>(value >> 24)};
    return spi_transfer(tx, nullptr, sizeof(tx));
}

bool read_u32(uint16_t address, uint32_t *value) {
    uint8_t data[4]{};
    if (!read_sfr(address, data, sizeof(data))) return false;
    *value = static_cast<uint32_t>(data[0]) | (static_cast<uint32_t>(data[1]) << 8) |
        (static_cast<uint32_t>(data[2]) << 16) | (static_cast<uint32_t>(data[3]) << 24);
    return true;
}

bool write_byte(uint16_t address, uint8_t value) { return access_memory(kSpiWrite, address, &value, nullptr, 1); }

bool configure_fifos() {
    // FIFO1: eight classic-CAN TX objects, FIFO2: sixteen classic-CAN RX objects.
    // PLSIZE=0 is eight data bytes; TXEN=bit7, unlimited retries and priority 1.
    const uint32_t tx_config = (7u << 24) | (3u << 21) | (1u << 16) | (1u << 7);
    const uint32_t rx_config = (15u << 24) | 1u; // RxNotEmpty interrupt enabled
    uint8_t ecc = 0;
    if (!read_sfr(kRegEccCon, &ecc, 1) || !write_byte(kRegEccCon, ecc | 1u)) return false;
    uint8_t zeroes[64]{};
    for (uint16_t address = kRamStart; address < kRamStart + 2048; address += sizeof(zeroes)) {
        if (!access_memory(kSpiWrite, address, zeroes, nullptr, sizeof(zeroes))) return false;
    }
    if (!write_u32(kTxFifoCon, tx_config) || !write_u32(kRxFifoCon, rx_config)) return false;
    // Filter 0 accepts all standard IDs and routes them to FIFO2.
    // Enable module RX interrupt (bit 1) after the FIFO's RX-not-empty event.
    return write_byte(kFltCon0, 0x82) && write_byte(kRegIntEnable, 0x02);
}

uint8_t dlc_for(uint8_t length) { return length <= 8 ? length : 8; }

bool mcp_transmit(const CanFrame &frame) {
    uint32_t ua = 0;
    if (!read_u32(kTxFifoUa, &ua)) return false;
    uint8_t object[16]{};
    object[0] = static_cast<uint8_t>(frame.identifier);
    object[1] = static_cast<uint8_t>(frame.identifier >> 8);
    object[4] = dlc_for(frame.length);
    std::memcpy(object + 8, frame.data, frame.length);
    const size_t bytes = ((8 + frame.length + 3) / 4) * 4;
    if (!access_memory(kSpiWrite, static_cast<uint16_t>(kRamStart + ua), object, nullptr, bytes)) return false;
    return write_byte(kTxFifoCon + 1, 0x03); // UINC + TXREQ
}

bool mcp_receive(CanFrame *frame) {
    uint8_t status = 0;
    if (!read_sfr(kRxFifoSta, &status, 1) || !(status & 1u)) return false;
    uint32_t ua = 0;
    uint8_t object[16]{};
    if (!read_u32(kRxFifoUa, &ua) || !access_memory(kSpiRead, static_cast<uint16_t>(kRamStart + ua), nullptr, object, sizeof(object))) return false;
    frame->identifier = static_cast<uint32_t>(object[0]) | (static_cast<uint32_t>(object[1]) << 8);
    frame->length = object[4] & 0x0f;
    if (frame->length > 8) frame->length = 8;
    std::memcpy(frame->data, object + 8, frame->length);
    return write_byte(kRxFifoCon + 1, 0x01); // UINC
}

bool mcp_set_loopback(bool enabled) {
    uint32_t config = 0;
    if (!read_u32(kRegCiCon, &config)) return false;

    // Stage every transition through Configuration mode.  Besides being the
    // documented safe way to change REQOP, entering Configuration resets the
    // FIFO state, which is why the FIFO layout is restored before leaving it.
    const uint32_t configuration_mode = (config & ~(7u << 24)) | (4u << 24);
    if (!write_u32(kRegCiCon, configuration_mode)) return false;
    for (int attempt = 0; attempt < 20; ++attempt) {
        vTaskDelay(pdMS_TO_TICKS(1));
        if (!read_u32(kRegCiCon, &config)) return false;
        if (((config >> 21) & 7u) == 4u) break;
        if (attempt == 19) return false;
    }
    if (!configure_fifos() || !write_u32(0x004, 0x003f0e0e)) return false;

    const uint32_t requested = (config & ~(7u << 24)) | ((enabled ? 2u : 0u) << 24);
    if (!write_u32(kRegCiCon, requested)) return false;
    for (int attempt = 0; attempt < 20; ++attempt) {
        vTaskDelay(pdMS_TO_TICKS(1));
        if (!read_u32(kRegCiCon, &config)) return false;
        if (((config >> 21) & 7u) == (enabled ? 2u : 0u)) {
            g_state.status.controller_config = config;
            g_state.status.loopback = enabled;
            g_state.status.last_error = ESP_OK;
            return true;
        }
    }
    return false;
}

uint32_t little_endian_u32(const uint8_t bytes[4]) {
    return static_cast<uint32_t>(bytes[0]) |
           (static_cast<uint32_t>(bytes[1]) << 8) |
           (static_cast<uint32_t>(bytes[2]) << 16) |
           (static_cast<uint32_t>(bytes[3]) << 24);
}

void initialise_worker() {
    spi_bus_config_t bus{};
    bus.sclk_io_num = kSck;
    bus.mosi_io_num = kMosi;
    bus.miso_io_num = kMiso;
    bus.quadwp_io_num = -1;
    bus.quadhd_io_num = -1;
    bus.max_transfer_sz = 72;
    esp_err_t error = spi_bus_initialize(kSpiHost, &bus, SPI_DMA_CH_AUTO);
    if (error != ESP_OK) {
        g_state.status.last_error = error;
        return;
    }

    spi_device_interface_config_t device{};
    device.clock_speed_hz = kSpiHz;
    device.mode = 0;
    device.spics_io_num = kCs;
    device.queue_size = 1;
    error = spi_bus_add_device(kSpiHost, &device, &g_state.spi);
    if (error != ESP_OK) {
        g_state.status.last_error = error;
        return;
    }
    gpio_config_t int_pin{};
    int_pin.pin_bit_mask = 1ULL << kInt;
    int_pin.mode = GPIO_MODE_INPUT;
    int_pin.pull_up_en = GPIO_PULLUP_ENABLE;
    int_pin.pull_down_en = GPIO_PULLDOWN_DISABLE;
    int_pin.intr_type = GPIO_INTR_NEGEDGE;
    gpio_config(&int_pin);

    // RESET selects Configuration mode. It intentionally does not configure
    // bit timing or enable the transceiver; those depend on the module's
    // oscillator, CAN bitrate, and (for safe TX) bus wiring.
    const uint8_t reset[2] = {kSpiReset, 0x00};
    if (!spi_transfer(reset, nullptr, sizeof(reset))) {
        g_state.status.last_error = ESP_FAIL;
        return;
    }
    vTaskDelay(pdMS_TO_TICKS(10));

    uint8_t dev_id[4]{};
    uint8_t config[4]{};
    uint8_t oscillator[4]{};
    if (!read_sfr(kRegDevId, dev_id, sizeof(dev_id)) ||
        !read_sfr(kRegCiCon, config, sizeof(config)) ||
        !read_sfr(kRegOsc, oscillator, sizeof(oscillator))) {
        g_state.status.last_error = ESP_FAIL;
        return;
    }

    // A floating MISO pin typically reads all ones. DEVID is allowed to be
    // zero on some revisions, so preserve it for diagnosis rather than trying
    // to infer a non-existent 0x2518 signature.
    const bool all_ff = dev_id[0] == 0xff && dev_id[1] == 0xff &&
                        dev_id[2] == 0xff && dev_id[3] == 0xff;
    g_state.status.device_id = dev_id[0];
    g_state.status.controller_config = little_endian_u32(config);
    g_state.status.oscillator = little_endian_u32(oscillator);
    g_state.status.spi_responding = !all_ff;
    g_state.status.initialized = !all_ff;
    if (!all_ff) {
        // 40 MHz oscillator, 500 kbit/s nominal CAN timing; internal loopback.
        const uint32_t requested = (g_state.status.controller_config & ~(7u << 24)) | (2u << 24);
        // INT0/GPIO0/XSTBY controls the ATA6561 STBY input on the production
        // hardware.  With XSTBYEN set, it is high only while the controller is
        // asleep and low whenever it is awake, enabling the transceiver.  The
        // MCP2518FD requires IOCON fields to be written one byte at a time.
        if (configure_fifos() && write_u32(0x004, 0x003f0e0e) &&
            write_byte(kRegIoCon, kIoConXstbyEnable) && write_u32(kRegCiCon, requested)) {
            vTaskDelay(pdMS_TO_TICKS(2));
            uint8_t mode[4]{};
            if (read_sfr(kRegCiCon, mode, sizeof(mode))) {
                g_state.status.controller_config = little_endian_u32(mode);
                g_state.status.loopback = ((g_state.status.controller_config >> 21) & 7u) == 2u;
                esp_err_t isr = gpio_install_isr_service(0);
                if (isr == ESP_OK || isr == ESP_ERR_INVALID_STATE) {
                    gpio_isr_handler_add(kInt, mcp_interrupt, nullptr);
                } else {
                    g_state.status.last_error = isr;
                }
            }
        }
    }
}

void worker(void *) {
    g_state.worker_task = xTaskGetCurrentTaskHandle();
    initialise_worker();
    g_state.status.started = true;
    xSemaphoreGive(g_state.ready);

    // Queue ownership lives on core 1 from now on. CAN FIFO configuration and
    // polling/IRQ handling are added only after bitrate and INT wiring are
    // confirmed; dropping no frames silently would be unsafe, so TX is held.
    CanFrame frame;
    for (;;) {
        if (g_state.mode_change_pending) {
            const bool requested_loopback = g_state.requested_loopback;
            g_state.mode_change_pending = false;
            if (!mcp_set_loopback(requested_loopback)) g_state.status.last_error = ESP_FAIL;
            xSemaphoreGive(g_state.mode_done);
        }
        if (xQueueReceive(g_state.tx_queue, &frame, 0) == pdTRUE) {
            if (!mcp_transmit(frame)) {
                ++g_state.status.tx_dropped;
                continue;
            }
        }
        // D13 wakes this task on MCP RX. The timeout also provides recovery if
        // an edge was lost while the task was busy transmitting.
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(10));
        CanFrame received{};
        while (mcp_receive(&received)) {
            if (xQueueSend(g_state.rx_queue, &received, 0) != pdTRUE) ++g_state.status.rx_dropped;
        }
    }
}

} // namespace

bool CanService::start() {
    if (g_state.start_requested) {
        return g_state.status.initialized;
    }
    g_state.tx_queue = xQueueCreate(kQueueDepth, sizeof(CanFrame));
    g_state.rx_queue = xQueueCreate(kQueueDepth, sizeof(CanFrame));
    g_state.ready = xSemaphoreCreateBinary();
    g_state.mode_done = xSemaphoreCreateBinary();
    if (!g_state.tx_queue || !g_state.rx_queue || !g_state.ready || !g_state.mode_done) {
        g_state.status.last_error = ESP_ERR_NO_MEM;
        return false;
    }
    g_state.start_requested = true;
    if (xTaskCreatePinnedToCore(worker, "mcp2518", 4096, nullptr,
                                configMAX_PRIORITIES - 2, nullptr,
                                kWorkerCore) != pdPASS) {
        g_state.status.last_error = ESP_ERR_NO_MEM;
        return false;
    }
    // Report detection synchronously to Python; no MicroPython API is used by
    // the worker.
    if (xSemaphoreTake(g_state.ready, pdMS_TO_TICKS(2000)) != pdTRUE) {
        g_state.status.last_error = ESP_ERR_TIMEOUT;
        return false;
    }
    return g_state.status.initialized;
}

bool CanService::enqueue(const CanFrame &frame) {
    if (!g_state.tx_queue || frame.length > sizeof(frame.data)) {
        return false;
    }
    return xQueueSend(g_state.tx_queue, &frame, 0) == pdTRUE;
}

bool CanService::dequeue(CanFrame *frame) {
    return g_state.rx_queue && xQueueReceive(g_state.rx_queue, frame, 0) == pdTRUE;
}

bool CanService::set_loopback(bool enabled) {
    if (!g_state.worker_task || !g_state.status.initialized) return false;
    g_state.requested_loopback = enabled;
    g_state.mode_change_pending = true;
    xTaskNotifyGive(g_state.worker_task);
    if (xSemaphoreTake(g_state.mode_done, pdMS_TO_TICKS(500)) != pdTRUE) return false;
    return g_state.status.loopback == enabled;
}

CanServiceStatus CanService::status() const {
    return g_state.status;
}

CanService &can_service() {
    static CanService service;
    return service;
}
