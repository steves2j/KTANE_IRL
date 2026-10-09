"""Send a one/two/three LED-flash count over the physical CAN bus.

Upload this file to the transmitting XIAO, for example:
    mpremote connect /dev/cu.usbmodemXXXX fs cp can_flash_sender.py :main.py

The native CAN service uses 500 kbit/s.  The other node must run the matching
receiver example and be connected to the same correctly terminated CAN bus.
"""

from machine import Pin
from time import sleep_ms, ticks_add, ticks_diff, ticks_ms

import mcp2518

CAN_ID = 0x321
LED_PIN = 21
PULSE_MS = 100
GAP_MS = 100
PERIOD_MS = 3000

# The XIAO ESP32-S3 user LED is active-low.
led = Pin(LED_PIN, Pin.OUT, value=1)


def flash(count):
    """Flash the user LED count times and leave it off."""
    for _ in range(count):
        led.value(0)
        sleep_ms(PULSE_MS)
        led.value(1)
        sleep_ms(GAP_MS)


if not mcp2518.start():
    raise RuntimeError("MCP2518FD was not initialised: %r" % mcp2518.status())
if not mcp2518.set_mode("normal"):
    raise RuntimeError("could not enter normal CAN mode: %r" % mcp2518.status())

count = 1
while True:
    cycle_started = ticks_ms()
    if not mcp2518.send(CAN_ID, bytes((count,))):
        print("CAN transmit queue full")
    else:
        print("sent", count)
    flash(count)

    # Start each count cycle one second apart, irrespective of flash duration.
    remaining = ticks_diff(ticks_add(cycle_started, PERIOD_MS), ticks_ms())
    if remaining > 0:
        sleep_ms(remaining)
    count = 1 if count == 3 else count + 1
