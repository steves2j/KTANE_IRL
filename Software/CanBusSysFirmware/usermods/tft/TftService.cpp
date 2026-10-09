#include "TftService.hpp"

extern "C" {
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "py/mphal.h"
}

#include <cstdarg>
#include <cstdio>
#include <cstring>

namespace {
constexpr spi_host_device_t kHost = SPI3_HOST;
constexpr int kWidth = 284;   // logical rotation-3 canvas
constexpr int kHeight = 76;
constexpr int kColStart = 18;
constexpr int kRowStart = 82;
constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kCyan = 0x07FF;

struct State {
    spi_device_handle_t spi = nullptr;
    TftPins pins{};
    bool configured = false;
    bool initialized = false;
    bool bus_owned = false;
    int last_error = ESP_OK;
    SemaphoreHandle_t mutex = nullptr;
} g;

void log_line(const char *format, ...) {
    char message[160];
    va_list args;
    va_start(args, format);
    std::vsnprintf(message, sizeof(message), format, args);
    va_end(args);
    mp_printf(&mp_plat_print, "%lu ms tft: %s\n",
              static_cast<unsigned long>(esp_log_timestamp()), message);
}

bool same_pins(const TftPins &a, const TftPins &b) {
    return a.cs == b.cs && a.dc == b.dc && a.reset == b.reset &&
           a.backlight == b.backlight && a.sck == b.sck && a.mosi == b.mosi;
}

esp_err_t transfer(const uint8_t *bytes, size_t length) {
    if (!length) return ESP_OK;
    spi_transaction_t transaction{};
    transaction.length = length * 8;
    transaction.tx_buffer = bytes;
    return spi_device_transmit(g.spi, &transaction);
}

// This follows the proven st7789 usermod framing exactly: command and its
// argument bytes share one CS assertion; each following command starts with
// a fresh assertion.  Some of these compact ST7789P3 panels are fussy about
// that framing, even though the controller data sheet permits CS to remain
// low across commands.
esp_err_t write_command(uint8_t value, const uint8_t *bytes = nullptr, size_t length = 0) {
    gpio_set_level(static_cast<gpio_num_t>(g.pins.cs), 0);
    gpio_set_level(static_cast<gpio_num_t>(g.pins.dc), 0);
    esp_err_t error = transfer(&value, 1);
    if (error == ESP_OK && length) {
        gpio_set_level(static_cast<gpio_num_t>(g.pins.dc), 1);
        error = transfer(bytes, length);
    }
    gpio_set_level(static_cast<gpio_num_t>(g.pins.cs), 1);
    return error;
}

esp_err_t set_window(int x, int y, int width, int height) {
    const int x1 = x + width - 1;
    const int y1 = y + height - 1;
    const uint8_t columns[] = {static_cast<uint8_t>((x + kColStart) >> 8),
                               static_cast<uint8_t>(x + kColStart),
                               static_cast<uint8_t>((x1 + kColStart) >> 8),
                               static_cast<uint8_t>(x1 + kColStart)};
    const uint8_t rows[] = {static_cast<uint8_t>((y + kRowStart) >> 8),
                            static_cast<uint8_t>(y + kRowStart),
                            static_cast<uint8_t>((y1 + kRowStart) >> 8),
                            static_cast<uint8_t>(y1 + kRowStart)};
    esp_err_t error = write_command(0x2A, columns, sizeof(columns));
    if (error == ESP_OK) error = write_command(0x2B, rows, sizeof(rows));
    if (error == ESP_OK) error = write_command(0x2C);
    return error;
}

esp_err_t fill_rect(int x, int y, int width, int height, uint16_t colour) {
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > kWidth || y + height > kHeight) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_err_t error = set_window(x, y, width, height);
    if (error != ESP_OK) return error;
    uint8_t block[256];
    for (size_t i = 0; i < sizeof(block); i += 2) {
        block[i] = static_cast<uint8_t>(colour >> 8);
        block[i + 1] = static_cast<uint8_t>(colour);
    }
    size_t remaining = static_cast<size_t>(width) * height * 2;
    gpio_set_level(static_cast<gpio_num_t>(g.pins.cs), 0);
    gpio_set_level(static_cast<gpio_num_t>(g.pins.dc), 1);
    while (remaining && error == ESP_OK) {
        const size_t chunk = remaining < sizeof(block) ? remaining : sizeof(block);
        error = transfer(block, chunk);
        remaining -= chunk;
    }
    gpio_set_level(static_cast<gpio_num_t>(g.pins.cs), 1);
    return error;
}

esp_err_t initialise_controller() {
    // Mirror the known-good st7789 usermod's reset sequence exactly.
    gpio_set_level(static_cast<gpio_num_t>(g.pins.backlight), 0);
    gpio_set_level(static_cast<gpio_num_t>(g.pins.reset), 1);
    vTaskDelay(pdMS_TO_TICKS(50));
    gpio_set_level(static_cast<gpio_num_t>(g.pins.reset), 0);
    vTaskDelay(pdMS_TO_TICKS(50));
    gpio_set_level(static_cast<gpio_num_t>(g.pins.reset), 1);
    vTaskDelay(pdMS_TO_TICKS(150));
    esp_err_t error;
    if ((error = write_command(0x01)) != ESP_OK) return error; // SWRESET
    vTaskDelay(pdMS_TO_TICKS(150));
    if ((error = write_command(0x11)) != ESP_OK) return error; // SLPOUT
    vTaskDelay(pdMS_TO_TICKS(120));
    const uint8_t rgb565 = 0x55, rotation = 0xA0;
    if ((error = write_command(0x3A, &rgb565, 1)) != ESP_OK || // RGB565
        (error = write_command(0x36, &rotation, 1)) != ESP_OK || // rotation 3
        (error = write_command(0x20)) != ESP_OK || // inversion off
        (error = write_command(0x13)) != ESP_OK || // normal display mode
        (error = write_command(0x29)) != ESP_OK) return error; // display on
    vTaskDelay(pdMS_TO_TICKS(150));
    if ((error = fill_rect(0, 0, kWidth, kHeight, kBlack)) != ESP_OK) return error;
    // This board's BLK circuit is active-low.
    gpio_set_level(static_cast<gpio_num_t>(g.pins.backlight), 0);
    return ESP_OK;
}
} // namespace

TftService &tft_service() { static TftService service; return service; }

esp_err_t TftService::init(const TftPins &pins) {
    if (g.configured && !same_pins(g.pins, pins)) return g.last_error = ESP_ERR_INVALID_STATE;
    if (!g.mutex) g.mutex = xSemaphoreCreateMutex();
    if (!g.mutex) return g.last_error = ESP_ERR_NO_MEM;
    if (!g.spi) {
        spi_bus_config_t bus{};
        bus.sclk_io_num = pins.sck;
        bus.mosi_io_num = pins.mosi;
        bus.miso_io_num = -1;
        // The e-paper usermod can subsequently attach to this shared SPI3
        // host and transfers 15,000-byte framebuffers.
        bus.max_transfer_sz = 40000;
        esp_err_t error = spi_bus_initialize(kHost, &bus, SPI_DMA_CH_AUTO);
        if (error == ESP_OK) g.bus_owned = true;
        else if (error != ESP_ERR_INVALID_STATE) return g.last_error = error;
        spi_device_interface_config_t device{};
        device.clock_speed_hz = 10 * 1000 * 1000;
        device.mode = 0;
        // Match the known-working st7789 usermod: manual CS stays asserted
        // across command/data pairs and multi-chunk pixel transfers.
        device.spics_io_num = -1;
        device.queue_size = 1;
        if ((error = spi_bus_add_device(kHost, &device, &g.spi)) != ESP_OK) return g.last_error = error;
        // gpio_set_level() only changes the output latch; it does not put a
        // GPIO into output mode.  Configure every TFT-owned control line,
        // mirroring Pin(..., Pin.OUT) in the proven Python ST7789 driver.
        gpio_config_t control_config{};
        control_config.pin_bit_mask = (1ULL << pins.cs) | (1ULL << pins.dc) |
                                      (1ULL << pins.reset) | (1ULL << pins.backlight);
        control_config.mode = GPIO_MODE_OUTPUT;
        control_config.pull_up_en = GPIO_PULLUP_DISABLE;
        control_config.pull_down_en = GPIO_PULLDOWN_DISABLE;
        control_config.intr_type = GPIO_INTR_DISABLE;
        if ((error = gpio_config(&control_config)) != ESP_OK) return g.last_error = error;
        gpio_set_level(static_cast<gpio_num_t>(pins.cs), 1);
        gpio_set_level(static_cast<gpio_num_t>(pins.dc), 0);
        gpio_set_level(static_cast<gpio_num_t>(pins.reset), 1);
        gpio_set_level(static_cast<gpio_num_t>(pins.backlight), 0);
        g.pins = pins;
        g.configured = true;
    }
    xSemaphoreTake(g.mutex, portMAX_DELAY);
    const esp_err_t error = initialise_controller();
    xSemaphoreGive(g.mutex);
    g.initialized = error == ESP_OK;
    g.last_error = error;
    log_line("ST7789P3 init %s (error=%d)", error == ESP_OK ? "complete" : "failed", error);
    return error;
}

esp_err_t TftService::show_digit(int digit) {
    if (!g.initialized) return g.last_error = ESP_ERR_INVALID_STATE;
    if (digit < 0 || digit > 9) return g.last_error = ESP_ERR_INVALID_ARG;
    static const uint8_t masks[] = {0x3F,0x06,0x5B,0x4F,0x66,0x6D,0x7D,0x07,0x7F,0x6F};
    constexpr int t = 8, n = 22, x = (kWidth - (n + 2 * t)) / 2, y = (kHeight - (3 * t + 2 * n)) / 2;
    const int rectangles[7][4] = {{x+t,y,n,t},{x+n+t,y+t,t,n},{x+n+t,y+2*t+n,t,n},
                                  {x+t,y+2*(t+n),n,t},{x,y+2*t+n,t,n},{x,y+t,t,n},{x+t,y+t+n,n,t}};
    xSemaphoreTake(g.mutex, portMAX_DELAY);
    esp_err_t error = fill_rect(0, 0, kWidth, kHeight, kBlack);
    for (int segment = 0; error == ESP_OK && segment < 7; ++segment) {
        if (masks[digit] & (1 << segment)) error = fill_rect(rectangles[segment][0], rectangles[segment][1], rectangles[segment][2], rectangles[segment][3], kCyan);
    }
    xSemaphoreGive(g.mutex);
    g.last_error = error;
    return error;
}

esp_err_t TftService::draw_text(const char *text) {
    if (!g.initialized) return g.last_error = ESP_ERR_INVALID_STATE;
    if (!text) return g.last_error = ESP_ERR_INVALID_ARG;
    // Compact 5x7 glyphs, scaled 3x, fit the 284x76 landscape canvas.  The
    // glyph renderer is native, but the actual words are supplied by Python.
    auto glyph = [](char c, uint8_t out[5]) {
        std::memset(out, 0, 5);
        switch (c) {
            case 'W': { const uint8_t v[] = {0x1F,0x10,0x0C,0x10,0x1F}; std::memcpy(out,v,5); } break;
            case 'H': { const uint8_t v[] = {0x1F,0x04,0x04,0x04,0x1F}; std::memcpy(out,v,5); } break;
            case 'O': { const uint8_t v[] = {0x0E,0x11,0x11,0x11,0x0E}; std::memcpy(out,v,5); } break;
            case 'S': { const uint8_t v[] = {0x12,0x15,0x15,0x15,0x09}; std::memcpy(out,v,5); } break;
            case 'N': { const uint8_t v[] = {0x1F,0x02,0x04,0x08,0x1F}; std::memcpy(out,v,5); } break;
            case 'F': { const uint8_t v[] = {0x1F,0x05,0x05,0x05,0x01}; std::memcpy(out,v,5); } break;
            case 'I': { const uint8_t v[] = {0x11,0x11,0x1F,0x11,0x11}; std::memcpy(out,v,5); } break;
            case 'R': { const uint8_t v[] = {0x1F,0x05,0x0D,0x15,0x11}; std::memcpy(out,v,5); } break;
            case 'T': { const uint8_t v[] = {0x01,0x01,0x1F,0x01,0x01}; std::memcpy(out,v,5); } break;
            case '\'': { const uint8_t v[] = {0x00,0x18,0x04,0x00,0x00}; std::memcpy(out,v,5); } break;
        }
    };
    constexpr int scale = 3, y0 = 27;
    xSemaphoreTake(g.mutex, portMAX_DELAY);
    esp_err_t error = fill_rect(0, 0, kWidth, kHeight, kBlack);
    // A 5-column glyph plus one spacing column is 18 pixels wide at scale 3.
    // Centre the complete supplied string, allowing nine pixels for spaces.
    int text_width = 0;
    for (const char *letter = text; *letter; ++letter) text_width += (*letter == ' ') ? scale * 3 : scale * 6;
    int cursor = (kWidth - text_width) / 2;
    for (const char *letter = text; *letter && error == ESP_OK; ++letter) {
        if (*letter == ' ') { cursor += scale * 3; continue; }
        char upper = *letter;
        if (upper >= 'a' && upper <= 'z') upper -= 'a' - 'A';
        uint8_t columns[5]; glyph(upper, columns);
        for (int column = 0; column < 5 && error == ESP_OK; ++column) {
            for (int row = 0; row < 7 && error == ESP_OK; ++row) {
                if (columns[column] & (1 << row)) error = fill_rect(cursor + column * scale, y0 + row * scale, scale, scale, kCyan);
            }
        }
        cursor += scale * 6;
    }
    xSemaphoreGive(g.mutex);
    g.last_error = error;
    return error;
}

TftStatus TftService::status() const { return {g.spi != nullptr, g.initialized, g.last_error}; }
