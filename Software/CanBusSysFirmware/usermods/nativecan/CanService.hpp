#pragma once

#include "CanFrame.hpp"

// Placeholder boundary for the future core-pinned FreeRTOS CAN service.
// This type must remain independent of MicroPython headers and mp_obj_t.
class CanService {
  public:
    bool start();
    bool enqueue(const CanFrame &frame);
};
