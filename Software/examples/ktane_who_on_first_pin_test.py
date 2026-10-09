"""Logic-analyser pin exerciser for the Who's on First e-paper/touch module.

Every specified display/touch signal, including normally input-only BUSY and
MISO, toggles at a 1 ms high / 1 ms low interval until Enter is pressed in the
serial console.  The script then drives that pin low and advances to the next
signal.  This is intentionally a wiring test, not a safe normal-operation mode.
"""

from machine import Pin
from time import sleep_ms
import sys
import uselect


# XIAO ESP32-S3 D-pin labels mapped to GPIO numbers.
OUTPUT_PINS = (
    ("EPD BUSY", "D2", 3),
    ("EPD RESET", "D1", 2),
    ("EPD D/C", "D3", 4),
    ("TOUCH SDA", "D4", 5),
    ("TOUCH SCL", "D5", 6),
    ("TOUCH RESET", "D6", 43),
    ("EPD CS / SS", "D7", 44),
    ("EPD SCK", "D8", 7),
    ("EPD MISO", "D9", 8),
    ("EPD MOSI", "D10", 9),
)

TOGGLE_INTERVAL_MS = 1


console_poll = uselect.poll()
console_poll.register(sys.stdin, uselect.POLLIN)


def wait_for_enter_while_toggling(pin):
    """Toggle one output indefinitely; return only when a console line arrives."""
    level = 0
    while True:
        pin.value(level)
        level = 1 - level
        sleep_ms(TOGGLE_INTERVAL_MS)
        if console_poll.poll(0):
            # Consume the whole line.  Any text is ignored; Enter advances.
            sys.stdin.readline()
            pin.value(0)
            return


def main():
    print("Who on First pin exerciser")
    print("Each output is a 500 Hz square wave (1 ms high, 1 ms low).")
    print("Press Enter to advance; Ctrl-C stops the test.")
    print("WARNING: this deliberately drives BUSY and MISO for wiring checks.")

    for name, d_pin, gpio in OUTPUT_PINS:
        pin = Pin(gpio, Pin.OUT, value=0)
        print("\nTOGGLING %s: %s / GPIO%d -- press Enter for next pin" % (name, d_pin, gpio))
        wait_for_enter_while_toggling(pin)

    print("\nPin exercise complete; all tested output pins are low.")


try:
    main()
finally:
    # Leave every test signal low at completion or after Ctrl-C.
    for _, _, gpio in OUTPUT_PINS:
        Pin(gpio, Pin.OUT, value=0)
