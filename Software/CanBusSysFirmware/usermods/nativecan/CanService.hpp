#pragma once

#include "CanFrame.hpp"
#include <cstdint>

// Snapshot deliberately contains plain data only, so it is safe to share
// across the core-1 FreeRTOS worker and MicroPython's interpreter task.
struct CanServiceStatus {
    bool started = false;
    bool spi_responding = false;
    bool initialized = false;
    bool loopback = false;
    int32_t last_error = 0;
    uint8_t device_id = 0;
    uint32_t controller_config = 0;
    uint32_t oscillator = 0;
    uint32_t tx_dropped = 0;
    uint32_t rx_dropped = 0;
};

// Core-1 boundary for the MCP2518FD service. This type must remain independent
// of MicroPython headers and mp_obj_t. SPI and all MCP accesses belong solely
// to its worker task; Python interacts only through FreeRTOS queues.
class CanService {
  public:
    bool start();
    bool enqueue(const CanFrame &frame);
    bool dequeue(CanFrame *frame);
    bool set_loopback(bool enabled);
    CanServiceStatus status() const;
};

CanService &can_service();
