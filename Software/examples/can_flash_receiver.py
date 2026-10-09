"""Mirror one/two/three LED-flash counts received from can_flash_sender.py.

Upload this file to the receiving XIAO, for example:
    mpremote connect /dev/cu.usbmodemXXXX fs cp can_flash_receiver.py :main.py

The native CAN service uses 500 kbit/s.  The other node must run the matching
sender example and be connected to the same correctly terminated CAN bus.
"""

from machine import Pin
from time import sleep_ms

import mcp2518

CAN_ID = 0x321
LED_PIN = 21
PULSE_MS = 100
GAP_MS = 100

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

while True:
    frame = mcp2518.recv()
    if frame is None:
        sleep_ms(10)
        continue

    identifier, payload = frame
    if identifier != CAN_ID or len(payload) != 1:
        continue
    count = payload[0]
    if 1 <= count <= 3:
        print("received", count)
        flash(count)
