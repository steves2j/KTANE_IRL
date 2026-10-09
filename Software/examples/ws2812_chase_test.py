"""Interactively flash one RGBW WS2812 LED on XIAO ESP32-S3 D11 (GPIO38).

Press 1 through 7 in the serial terminal to select the LED to flash.  Each
flash advances through red, green, blue and white.
"""

from machine import Pin
import neopixel
from time import sleep_ms
import sys
import uselect

LED_PIN = 38  # XIAO D11; do not confuse this with chip GPIO11 (CAN MOSI).
LED_COUNT = 7
FLASH_MS = 500

# RGBW primary colours, in MicroPython's (red, green, blue, white) order.
# Values are deliberately modest to limit current draw when powered from the
# XIAO's 3V3 rail.  White uses the LED's dedicated W die, not RGB mixing.
COLOURS = (
    (24, 0, 0, 0),   # red
    (0, 24, 0, 0),   # green
    (0, 0, 24, 0),   # blue
    (0, 0, 0, 24),   # dedicated white LED
)

# bpp=4 selects RGBW output (four bytes per pixel) rather than normal RGB.
pixels = neopixel.NeoPixel(Pin(LED_PIN, Pin.OUT), LED_COUNT, bpp=4)
OFF = (0, 0, 0, 0)


def show_one(index, colour):
    """Illuminate exactly one pixel."""
    for pixel in range(LED_COUNT):
        pixels[pixel] = colour if pixel == index else OFF
    pixels.write()


def all_off():
    for pixel in range(LED_COUNT):
        pixels[pixel] = OFF
    pixels.write()


def wait_with_input(milliseconds, selected):
    """Wait while accepting 1..7 without blocking the animation."""
    remaining = milliseconds
    while remaining:
        if serial.poll(0):
            key = sys.stdin.read(1)
            if key and "1" <= key <= str(LED_COUNT):
                selected = ord(key) - ord("1")
                print("selected LED", selected + 1)
        delay = min(20, remaining)
        sleep_ms(delay)
        remaining -= delay
    return selected


# MicroPython's USB serial input is polled so that a digit changes LEDs without
# having to stop the script with Ctrl-C.
serial = uselect.poll()
serial.register(sys.stdin, uselect.POLLIN)

try:
    selected_led = 0
    colour_index = 0
    while True:
        colour = COLOURS[colour_index]
        show_one(selected_led, colour)
        selected_led = wait_with_input(FLASH_MS, selected_led)
        all_off()
        selected_led = wait_with_input(FLASH_MS, selected_led)
        colour_index = (colour_index + 1) % len(COLOURS)
finally:
    all_off()
