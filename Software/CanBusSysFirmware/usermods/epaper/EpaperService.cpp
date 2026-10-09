#include "EpaperService.hpp"

extern "C" {
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "py/mpprint.h"
}

#include <cstring>
#include <cstdarg>
#include <cstdio>

namespace {

// SPI2 is occupied by the external MCP2518FD; use the other general SPI host.
// GPIO assignments are supplied from Python to EpaperService::init().
constexpr spi_host_device_t kSpiHost = SPI3_HOST;
constexpr int kSpiHz = 10 * 1000 * 1000;
constexpr int kWidth = 400;
constexpr int kHeight = 300;
constexpr int kBytesPerRow = kWidth / 8;
constexpr size_t kFramebufferBytes = kBytesPerRow * kHeight;
constexpr int kBusyTimeoutMs = 3000;

struct State {
    spi_device_handle_t spi = nullptr;
    SemaphoreHandle_t mutex = nullptr;
    bool initialized = false;
    bool partial_mode_ready = false;
    esp_err_t last_error = ESP_OK;
    EpaperPins pins{};
    bool pins_configured = false;
    bool bus_owned = false;
};

State g_state;

void log_line(const char *format, ...) {
    char message[256];
    va_list args;
    va_start(args, format);
    std::vsnprintf(message, sizeof(message), format, args);
    va_end(args);
    // Route through MicroPython's platform printer rather than stdio.  This
    // reaches both an interactive REPL and mpremote's captured serial output.
    mp_printf(&mp_plat_print, "%lu ms epaper: %s\n",
        static_cast<unsigned long>(esp_log_timestamp()), message);
}

bool take_lock() {
    return g_state.mutex && xSemaphoreTake(g_state.mutex, pdMS_TO_TICKS(5000)) == pdTRUE;
}

void give_lock() {
    if (g_state.mutex) xSemaphoreGive(g_state.mutex);
}

esp_err_t wait_ready(const char *) {
    const TickType_t start = xTaskGetTickCount();
    while (gpio_get_level(static_cast<gpio_num_t>(g_state.pins.busy))) {
        if ((xTaskGetTickCount() - start) > pdMS_TO_TICKS(kBusyTimeoutMs)) {
            log_line("BUSY timeout after %d ms", kBusyTimeoutMs);
            return ESP_ERR_TIMEOUT;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    log_line("BUSY ready after %lu ms", static_cast<unsigned long>(pdTICKS_TO_MS(xTaskGetTickCount() - start)));
    return ESP_OK;
}

// The SSD1683 asserts BUSY a short time *after* the 0x20 refresh trigger.
// Merely testing for BUSY == low immediately after sending 0x20 can therefore
// report a false completion and corrupt the following transfer.  This mirrors
// GxEPD2's post-command settling delay, and additionally makes a missing BUSY
// assertion a diagnosable failure instead of silently continuing.
esp_err_t wait_for_busy_cycle(const char *operation) {
    constexpr int kAssertTimeoutMs = 60;
    const TickType_t start = xTaskGetTickCount();
    esp_rom_delay_us(1000); // GxEPD2 waits 1 ms before its first BUSY sample.
    while (!gpio_get_level(static_cast<gpio_num_t>(g_state.pins.busy))) {
        if ((xTaskGetTickCount() - start) > pdMS_TO_TICKS(kAssertTimeoutMs)) {
            log_line("BUSY did not assert within %d ms after %s", kAssertTimeoutMs, operation);
            return ESP_ERR_INVALID_STATE;
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    log_line("BUSY asserted after %lu ms for %s",
        static_cast<unsigned long>(pdTICKS_TO_MS(xTaskGetTickCount() - start)), operation);
    return wait_ready(operation);
}

esp_err_t transfer(const uint8_t *data, size_t length) {
    if (length == 0) return ESP_OK;
    spi_transaction_t transaction{};
    transaction.length = length * 8;
    transaction.tx_buffer = data;
    return spi_device_transmit(g_state.spi, &transaction);
}

esp_err_t command(uint8_t value) {
    gpio_set_level(static_cast<gpio_num_t>(g_state.pins.dc), 0);
    return transfer(&value, 1);
}

esp_err_t data(const uint8_t *values, size_t length) {
    gpio_set_level(static_cast<gpio_num_t>(g_state.pins.dc), 1);
    return transfer(values, length);
}

esp_err_t data_byte(uint8_t value) {
    return data(&value, 1);
}

esp_err_t reset() {
    log_line("hardware reset");
    gpio_set_level(static_cast<gpio_num_t>(g_state.pins.reset), 0);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(static_cast<gpio_num_t>(g_state.pins.reset), 1);
    vTaskDelay(pdMS_TO_TICKS(10));
    return wait_ready("hardware reset");
}

esp_err_t configure_full_ram() {
    // GDEY042T81 / SSD1683 normal initialisation values, matching GxEPD2.
    const uint8_t mux[] = {0x2B, 0x01, 0x00};
    const uint8_t x_window[] = {0x00, 0x31};
    const uint8_t y_window[] = {0x2B, 0x01, 0x00, 0x00};
    const uint8_t y_pointer[] = {0x2B, 0x01};
    esp_err_t error;
    if ((error = command(0x01)) != ESP_OK || (error = data(mux, sizeof(mux))) != ESP_OK ||
        (error = command(0x3C)) != ESP_OK || (error = data_byte(0x01)) != ESP_OK ||
        (error = command(0x18)) != ESP_OK || (error = data_byte(0x80)) != ESP_OK ||
        (error = command(0x11)) != ESP_OK || (error = data_byte(0x01)) != ESP_OK ||
        (error = command(0x44)) != ESP_OK || (error = data(x_window, sizeof(x_window))) != ESP_OK ||
        (error = command(0x45)) != ESP_OK || (error = data(y_window, sizeof(y_window))) != ESP_OK ||
        (error = command(0x4E)) != ESP_OK || (error = data_byte(0x00)) != ESP_OK ||
        (error = command(0x4F)) != ESP_OK || (error = data(y_pointer, sizeof(y_pointer))) != ESP_OK) {
        return error;
    }
    return ESP_OK;
}

esp_err_t send_framebuffer(const uint8_t *framebuffer) {
    // Controller X coordinates run opposite the Python FrameBuffer rows.
    uint8_t line[kBytesPerRow];
    for (int row = 0; row < kHeight; ++row) {
        const uint8_t *source = framebuffer + row * kBytesPerRow;
        for (int index = 0; index < kBytesPerRow; ++index) {
            line[index] = source[kBytesPerRow - 1 - index];
        }
        const esp_err_t error = data(line, sizeof(line));
        if (error != ESP_OK) return error;
    }
    return ESP_OK;
}

esp_err_t full_init();

esp_err_t recover_with_full_refresh(const uint8_t *framebuffer) {
    // A stalled differential waveform leaves controller RAM state uncertain.
    // Reinitialise and put the supplied full frame in both SSD1683 planes.
    log_line("partial refresh stalled; recovering with normal full refresh");
    g_state.initialized = false;
    g_state.partial_mode_ready = false;
    esp_err_t error = full_init();
    if (error != ESP_OK) return error;
    if ((error = command(0x26)) != ESP_OK || (error = send_framebuffer(framebuffer)) != ESP_OK ||
        (error = command(0x24)) != ESP_OK || (error = send_framebuffer(framebuffer)) != ESP_OK ||
        (error = command(0x21)) != ESP_OK || (error = data_byte(0x40)) != ESP_OK ||
        (error = data_byte(0x00)) != ESP_OK || (error = command(0x22)) != ESP_OK ||
        (error = data_byte(0xF7)) != ESP_OK || (error = command(0x20)) != ESP_OK) {
        return error;
    }
    const esp_err_t refresh_error = wait_for_busy_cycle("partial recovery full refresh");
    if (refresh_error == ESP_OK) g_state.partial_mode_ready = true;
    return refresh_error;
}

bool same_pins(const EpaperPins &left, const EpaperPins &right) {
    return left.cs == right.cs && left.dc == right.dc && left.reset == right.reset &&
           left.busy == right.busy && left.sck == right.sck && left.mosi == right.mosi;
}

bool valid_pins(const EpaperPins &pins) {
    return GPIO_IS_VALID_GPIO(pins.cs) && GPIO_IS_VALID_GPIO(pins.dc) &&
           GPIO_IS_VALID_GPIO(pins.reset) && GPIO_IS_VALID_GPIO(pins.busy) &&
           GPIO_IS_VALID_GPIO(pins.sck) && GPIO_IS_VALID_GPIO(pins.mosi);
}

esp_err_t ensure_bus(const EpaperPins *pins = nullptr) {
    if (pins && !valid_pins(*pins)) return ESP_ERR_INVALID_ARG;
    if (g_state.spi) {
        if (!pins || same_pins(g_state.pins, *pins)) return ESP_OK;
        // Reconfiguration is only allowed through init(); no display transfer
        // can be in progress because init owns the service mutex.
        if (!g_state.bus_owned) return ESP_ERR_INVALID_STATE;
        spi_bus_remove_device(g_state.spi);
        spi_bus_free(kSpiHost);
        g_state.spi = nullptr;
        g_state.initialized = false;
        g_state.bus_owned = false;
        log_line("reconfiguring SPI bus for new pin assignment");
        if (g_state.mutex) {
            vSemaphoreDelete(g_state.mutex);
            g_state.mutex = nullptr;
        }
    }
    if (pins) {
        g_state.pins = *pins;
        g_state.pins_configured = true;
    }
    if (!g_state.pins_configured) return ESP_ERR_INVALID_STATE;
    log_line("configuring SPI3: CS=%d DC=%d RESET=%d BUSY=%d SCK=%d MOSI=%d @ %d Hz",
             g_state.pins.cs, g_state.pins.dc, g_state.pins.reset, g_state.pins.busy,
             g_state.pins.sck, g_state.pins.mosi, kSpiHz);
    g_state.mutex = xSemaphoreCreateMutex();
    if (!g_state.mutex) return ESP_ERR_NO_MEM;

    gpio_config_t output{};
    output.pin_bit_mask = (1ULL << g_state.pins.reset) | (1ULL << g_state.pins.dc);
    output.mode = GPIO_MODE_OUTPUT;
    output.pull_up_en = GPIO_PULLUP_DISABLE;
    output.pull_down_en = GPIO_PULLDOWN_DISABLE;
    output.intr_type = GPIO_INTR_DISABLE;
    esp_err_t error = gpio_config(&output);
    if (error != ESP_OK) return error;
    gpio_set_level(static_cast<gpio_num_t>(g_state.pins.reset), 1);
    gpio_set_level(static_cast<gpio_num_t>(g_state.pins.dc), 0);

    gpio_config_t input{};
    input.pin_bit_mask = 1ULL << g_state.pins.busy;
    input.mode = GPIO_MODE_INPUT;
    input.pull_up_en = GPIO_PULLUP_DISABLE;
    input.pull_down_en = GPIO_PULLDOWN_DISABLE;
    input.intr_type = GPIO_INTR_DISABLE;
    if ((error = gpio_config(&input)) != ESP_OK) return error;

    spi_bus_config_t bus{};
    bus.sclk_io_num = g_state.pins.sck;
    bus.mosi_io_num = g_state.pins.mosi;
    bus.miso_io_num = -1; // The panel's D9/MISO pad is not connected.
    bus.quadwp_io_num = -1;
    bus.quadhd_io_num = -1;
    bus.max_transfer_sz = kBytesPerRow;
    error = spi_bus_initialize(kSpiHost, &bus, SPI_DMA_CH_AUTO);
    if (error == ESP_OK) {
        g_state.bus_owned = true;
    } else if (error == ESP_ERR_INVALID_STATE) {
        // A compatible SPI3 device, such as the ST7789 usermod, has already
        // created the shared SCK/MOSI bus. Add only this display's CS device.
        g_state.bus_owned = false;
    } else {
        return error;
    }

    spi_device_interface_config_t device{};
    device.clock_speed_hz = kSpiHz;
    device.mode = 0;
    device.spics_io_num = g_state.pins.cs;
    device.queue_size = 1;
    if ((error = spi_bus_add_device(kSpiHost, &device, &g_state.spi)) != ESP_OK) {
        if (g_state.bus_owned) spi_bus_free(kSpiHost);
        g_state.bus_owned = false;
        return error;
    }
    return ESP_OK;
}

esp_err_t full_init() {
    log_line("SSD1683 normal initialisation");
    esp_err_t error = reset();
    if (error != ESP_OK) return error;
    if ((error = command(0x12)) != ESP_OK) return error;
    // The reference GxEPD2 driver uses a fixed 10 ms settling delay here;
    // this panel does not reliably pulse BUSY for software reset.
    vTaskDelay(pdMS_TO_TICKS(10));
    error = configure_full_ram();
    if (error == ESP_OK) {
        g_state.initialized = true;
        g_state.partial_mode_ready = false;
    }
    return error;
}

esp_err_t fast_init() {
    esp_err_t error = reset();
    if (error != ESP_OK) return error;
    // This controller does not reliably assert BUSY for software reset.
    if ((error = command(0x12)) != ESP_OK) return error;
    vTaskDelay(pdMS_TO_TICKS(10));
    const uint8_t update_control[] = {0x40, 0x00};
    const uint8_t x_window[] = {0x00, 0x31};
    const uint8_t y_window[] = {0x2B, 0x01, 0x00, 0x00};
    const uint8_t y_pointer[] = {0x2B, 0x01};
    if ((error = command(0x21)) != ESP_OK || (error = data(update_control, sizeof(update_control))) != ESP_OK ||
        (error = command(0x3C)) != ESP_OK || (error = data_byte(0x05)) != ESP_OK ||
        (error = command(0x1A)) != ESP_OK || (error = data_byte(0x6E)) != ESP_OK ||
        (error = command(0x22)) != ESP_OK || (error = data_byte(0x91)) != ESP_OK ||
        (error = command(0x20)) != ESP_OK) {
        return error;
    }
    // This panel performs the temperature-load step without a BUSY pulse.
    // Give it the same fixed settle period used by the vendor/GxEPD2 flow.
    vTaskDelay(pdMS_TO_TICKS(10));
    if ((error = command(0x11)) != ESP_OK || (error = data_byte(0x01)) != ESP_OK ||
        (error = command(0x44)) != ESP_OK || (error = data(x_window, sizeof(x_window))) != ESP_OK ||
        (error = command(0x45)) != ESP_OK || (error = data(y_window, sizeof(y_window))) != ESP_OK ||
        (error = command(0x4E)) != ESP_OK || (error = data_byte(0x00)) != ESP_OK ||
        (error = command(0x4F)) != ESP_OK || (error = data(y_pointer, sizeof(y_pointer))) != ESP_OK) {
        return error;
    }
    return wait_ready("fast RAM pointer setup");
}

} // namespace

EpaperService &epaper_service() {
    static EpaperService service;
    return service;
}

esp_err_t EpaperService::init(const EpaperPins &pins) {
    esp_err_t error = ensure_bus(&pins);
    if (error != ESP_OK) return g_state.last_error = error;
    if (!take_lock()) return g_state.last_error = ESP_ERR_TIMEOUT;
    error = full_init();
    give_lock();
    log_line("init %s (error=%d)", error == ESP_OK ? "complete" : "failed", error);
    return g_state.last_error = error;
}

esp_err_t EpaperService::full_refresh(const uint8_t *framebuffer, size_t length) {
    if (length != kFramebufferBytes) return g_state.last_error = ESP_ERR_INVALID_SIZE;
    esp_err_t error = ensure_bus();
    if (error != ESP_OK) return g_state.last_error = error;
    if (!take_lock()) return g_state.last_error = ESP_ERR_TIMEOUT;
    log_line("full refresh begin (%u bytes)", static_cast<unsigned>(length));
    if (!g_state.initialized && (error = full_init()) != ESP_OK) goto done;
    if ((error = command(0x26)) != ESP_OK || (error = send_framebuffer(framebuffer)) != ESP_OK ||
        (error = command(0x24)) != ESP_OK || (error = send_framebuffer(framebuffer)) != ESP_OK ||
        (error = command(0x21)) != ESP_OK || (error = data_byte(0x40)) != ESP_OK ||
        (error = data_byte(0x00)) != ESP_OK || (error = command(0x22)) != ESP_OK ||
        (error = data_byte(0xF7)) != ESP_OK ||
        (error = command(0x20)) != ESP_OK) goto done;
    error = wait_for_busy_cycle("full refresh");
    if (error == ESP_OK) g_state.partial_mode_ready = true;
done:
    give_lock();
    log_line("full refresh %s (error=%d)", error == ESP_OK ? "complete" : "failed", error);
    return g_state.last_error = error;
}

esp_err_t EpaperService::set_partial_base_map(const uint8_t *framebuffer, size_t length) {
    if (length != kFramebufferBytes) return g_state.last_error = ESP_ERR_INVALID_SIZE;
    esp_err_t error = ensure_bus();
    if (error != ESP_OK) return g_state.last_error = error;
    if (!take_lock()) return g_state.last_error = ESP_ERR_TIMEOUT;
    log_line("partial baseline begin (%u bytes)", static_cast<unsigned>(length));
    // A clean full update is the baseline required by GxEPD2 before its first
    // differential partial update.  It keeps 0x24/current and 0x26/previous
    // identical; the old C7 vendor fast-base sequence did not do this
    // consistently on this panel.
    if (!g_state.initialized && (error = full_init()) != ESP_OK) goto done;
    if ((error = command(0x26)) != ESP_OK || (error = send_framebuffer(framebuffer)) != ESP_OK ||
        (error = command(0x24)) != ESP_OK || (error = send_framebuffer(framebuffer)) != ESP_OK ||
        (error = command(0x21)) != ESP_OK || (error = data_byte(0x40)) != ESP_OK ||
        (error = data_byte(0x00)) != ESP_OK || (error = command(0x22)) != ESP_OK ||
        (error = data_byte(0xF7)) != ESP_OK || (error = command(0x20)) != ESP_OK) goto done;
    error = wait_for_busy_cycle("partial baseline refresh");
    if (error == ESP_OK) g_state.partial_mode_ready = true;
done:
    give_lock();
    log_line("partial baseline %s (error=%d)", error == ESP_OK ? "complete" : "failed", error);
    return g_state.last_error = error;
}

esp_err_t EpaperService::partial_refresh(const uint8_t *framebuffer, size_t length,
                                         int x, int y, int width, int height) {
    if (length != kFramebufferBytes) return g_state.last_error = ESP_ERR_INVALID_SIZE;
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > kWidth || y + height > kHeight ||
        (x & 7) || (width & 7)) return g_state.last_error = ESP_ERR_INVALID_ARG;
    esp_err_t error = ensure_bus();
    if (error != ESP_OK) return g_state.last_error = error;
    if (!take_lock()) return g_state.last_error = ESP_ERR_TIMEOUT;
    log_line("partial begin x=%d y=%d w=%d h=%d", x, y, width, height);
    const int source_x_start = x / 8;
    const int source_x_end = source_x_start + width / 8 - 1;
    const uint8_t ram_x_start = kBytesPerRow - 1 - source_x_end;
    const uint8_t ram_x_end = kBytesPerRow - 1 - source_x_start;
    const int ram_y_start = kHeight - 1 - y;
    const int ram_y_end = kHeight - (y + height);
    const uint8_t x_window[] = {ram_x_start, ram_x_end};
    const uint8_t y_window[] = {static_cast<uint8_t>(ram_y_start), static_cast<uint8_t>(ram_y_start >> 8),
                                static_cast<uint8_t>(ram_y_end), static_cast<uint8_t>(ram_y_end >> 8)};
    const uint8_t y_pointer[] = {static_cast<uint8_t>(ram_y_start), static_cast<uint8_t>(ram_y_start >> 8)};
    auto set_partial_area = [&]() -> esp_err_t {
        if ((error = command(0x11)) != ESP_OK || (error = data_byte(0x01)) != ESP_OK ||
            (error = command(0x44)) != ESP_OK || (error = data(x_window, sizeof(x_window))) != ESP_OK ||
            (error = command(0x45)) != ESP_OK || (error = data(y_window, sizeof(y_window))) != ESP_OK ||
            (error = command(0x4E)) != ESP_OK || (error = data_byte(ram_x_start)) != ESP_OK ||
            (error = command(0x4F)) != ESP_OK || (error = data(y_pointer, sizeof(y_pointer))) != ESP_OK) {
            return error;
        }
        return ESP_OK;
    };
    auto write_partial_plane = [&](uint8_t plane) -> esp_err_t {
        if ((error = set_partial_area()) != ESP_OK || (error = command(plane)) != ESP_OK) return error;
        uint8_t line[kBytesPerRow];
        const int line_length = width / 8;
        for (int row = y; row < y + height; ++row) {
            const uint8_t *source = framebuffer + row * kBytesPerRow;
            for (int column = 0; column < line_length; ++column) line[column] = source[source_x_end - column];
            if ((error = data(line, line_length)) != ESP_OK) return error;
        }
        return ESP_OK;
    };

    // A preceding normal full refresh writes both SSD1683 RAM planes and is
    // a valid differential baseline.  Do not apply the unverified 0x91 fast
    // sequence here: this panel does not assert BUSY for its resulting update.
    g_state.partial_mode_ready = true;

    // This follows GxEPD2's SSD1683 differential-update sequence: write the
    // new rectangle, refresh with 0xFC, then mirror it into both RAM planes.
    // The previous-plane write prevents artefacts from accumulating on the
    // next rectangle, and no reset is issued between partial updates.
    if ((error = write_partial_plane(0x24)) != ESP_OK || (error = command(0x21)) != ESP_OK ||
        (error = data_byte(0x00)) != ESP_OK || (error = data_byte(0x00)) != ESP_OK ||
        (error = command(0x22)) != ESP_OK || (error = data_byte(0xFC)) != ESP_OK ||
        (error = command(0x20)) != ESP_OK) goto done;
    error = wait_for_busy_cycle("partial refresh");
    if (error == ESP_ERR_TIMEOUT) {
        error = recover_with_full_refresh(framebuffer);
        goto done;
    }
    if (error != ESP_OK) goto done;
    if ((error = write_partial_plane(0x26)) != ESP_OK || (error = write_partial_plane(0x24)) != ESP_OK) goto done;
done:
    give_lock();
    log_line("partial %s (error=%d)", error == ESP_OK ? "complete" : "failed", error);
    return g_state.last_error = error;
}

EpaperStatus EpaperService::status() const {
    const bool busy = g_state.pins_configured &&
                      gpio_get_level(static_cast<gpio_num_t>(g_state.pins.busy)) != 0;
    return {g_state.spi != nullptr, g_state.initialized, busy, g_state.last_error};
}
