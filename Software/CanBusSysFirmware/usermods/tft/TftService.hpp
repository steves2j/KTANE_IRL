#pragma once

extern "C" {
#include "esp_err.h"
}

struct TftPins {
    int cs;
    int dc;
    int reset;
    int backlight;
    int sck;
    int mosi;
};

struct TftStatus {
    bool bus_ready;
    bool initialized;
    int last_error;
};

class TftService {
  public:
    esp_err_t init(const TftPins &pins);
    // Text content deliberately comes from MicroPython; this only performs
    // the native RGB565/SPI rendering.
    esp_err_t draw_text(const char *text);
    esp_err_t show_digit(int digit);
    TftStatus status() const;
};

TftService &tft_service();
