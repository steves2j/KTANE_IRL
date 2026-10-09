#pragma once

#include <cstddef>
#include <cstdint>

extern "C" {
#include "esp_err.h"
}

struct EpaperStatus {
    bool bus_ready;
    bool initialized;
    bool busy;
    int last_error;
};

struct EpaperPins {
    int cs;
    int dc;
    int reset;
    int busy;
    int sck;
    int mosi;
};

class EpaperService {
  public:
    esp_err_t init(const EpaperPins &pins);
    esp_err_t full_refresh(const uint8_t *framebuffer, size_t length);
    esp_err_t set_partial_base_map(const uint8_t *framebuffer, size_t length);
    esp_err_t partial_refresh(const uint8_t *framebuffer, size_t length,
                              int x, int y, int width, int height);
    EpaperStatus status() const;
};

EpaperService &epaper_service();
