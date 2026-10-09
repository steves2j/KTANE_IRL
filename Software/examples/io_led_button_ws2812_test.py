"""Exercise colour-matched buttons, indicator LEDs, and one RGB WS2812 LED.

XIAO pin assignments:
  LEDs (anode to pin): D6, D5, D4, D3 -- drive HIGH to illuminate.
  Buttons (switch to GND): D2, D1, D0, D7 -- internal pull-ups enabled.
  RGB WS2812 LED: D11 (GPIO38), one pixel.

The indicator LEDs do not cycle.  Each debounced button press illuminates its
matching-colour indicator LED and sets the RGB WS2812 LED to the same colour.
"""

from machine import Pin
from time import sleep_ms, ticks_add, ticks_diff, ticks_ms
import neopixel

# Chip GPIO numbers for the XIAO D-pin labels above.
LED_PINS = (43, 6, 5, 4)       # D6, D5, D4, D3
BUTTON_PINS = (3, 2, 1, 44)    # D2, D1, D0, D7
WS2812_PIN = 38                # D11, not chip GPIO11 (which is CAN MOSI)
WS2812_COUNT = 1

POLL_INTERVAL_MS = 20
DEBOUNCE_MS = 180

# Entries are (button label, indicator LED index, RGB strip colour).
# LEDs are ordered D6 (blue), D5 (red), D4 (green), D3 (yellow).
# Buttons are ordered D2 (red), D1 (green), D0 (blue), D7 (yellow).
BUTTON_ACTIONS = (
    ("red", 1, (24, 0, 0)),
    ("green", 2, (0, 24, 0)),
    ("blue", 0, (0, 0, 24)),
    ("yellow", 3, (24, 24, 0)),
)

leds = [Pin(pin, Pin.OUT, value=0) for pin in LED_PINS]
buttons = [Pin(pin, Pin.IN, Pin.PULL_UP) for pin in BUTTON_PINS]
pixels = neopixel.NeoPixel(Pin(WS2812_PIN, Pin.OUT), WS2812_COUNT, bpp=3)


def set_strip(colour):
    for index in range(WS2812_COUNT):
        pixels[index] = colour
    pixels.write()


def set_active_led(index):
    for led_index, led in enumerate(leds):
        led.value(1 if led_index == index else 0)


def all_off():
    for led in leds:
        led.value(0)
    set_strip((0, 0, 0))


try:
    previous_button_values = [button.value() for button in buttons]
    last_button_press = ticks_add(ticks_ms(), -DEBOUNCE_MS)

    set_strip((0, 0, 0))
    for led in leds:
        led.value(0)
    print("I/O colour test: buttons D2,D1,D0,D7 = red,green,blue,yellow")
    print("LEDs D6,D5,D4,D3 = blue,red,green,yellow")
    while True:
        now = ticks_ms()

        for index, button in enumerate(buttons):
            value = button.value()
            # Pull-up inputs are active-low.  React only to the falling edge
            # and ignore mechanical bounce for a short interval.
            if previous_button_values[index] and not value:
                if ticks_diff(now, last_button_press) >= DEBOUNCE_MS:
                    colour_name, led_index, colour = BUTTON_ACTIONS[index]
                    set_active_led(led_index)
                    set_strip(colour)
                    print("button", index + 1, "->", colour_name)
                    last_button_press = now
            previous_button_values[index] = value

        sleep_ms(POLL_INTERVAL_MS)
finally:
    all_off()
