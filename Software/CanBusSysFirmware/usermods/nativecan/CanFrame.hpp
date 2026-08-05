#pragma once

#include <cstdint>

// Transport-neutral representation for the later MCP2518FD service.
// It intentionally owns no MicroPython objects.
struct CanFrame {
    uint32_t identifier = 0;
    uint8_t data[64] = {};
    uint8_t length = 0;
    bool extended = false;
    bool fd = false;
    bool bit_rate_switch = false;
};
