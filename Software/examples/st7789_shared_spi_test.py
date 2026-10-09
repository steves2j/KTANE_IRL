"""ST7789 shared-SPI3 bring-up for the XIAO ESP32-S3.

The ST7789 and SSD1683 e-paper panel share SPI3 SCK/D8, MOSI/D10 and DC/D3.
Their CS lines are distinct, so only one controller sees each transaction.
The TFT uses CS/D6, RESET/D0 and BL/D14.  SPI(2) maps to ESP-IDF SPI3 on
this ESP32-S3 MicroPython port; SPI(1) is reserved for the MCP2518 bus.

The connected TFT has a 76 x 284 pixel active area.  This is not one of the
upstream driver's preset geometries, so the script supplies its addressing
table explicitly.
"""

from machine import Pin, SPI
from time import ticks_ms
import st7789
import neopixel


# ST7789 module geometry.
WIDTH = 76
HEIGHT = 284
SPI_HZ = 10_000_000

# Shared e-paper SPI3 signals.
SCK = 7             # D8
MOSI = 9            # D10
DC = 4              # D3, shared with the e-paper panel

# TFT-only controls.
CS = 43             # D6
RESET = 1           # D0
BACKLIGHT = 13      # D14

# Four RGB WS2812 pixels on the board's D11 data line. Keep them dark during
# TFT bring-up so the screen result is unambiguous.
WS2812_DATA = 10    # D11
WS2812_COUNT = 4


def log(*items):
    print("%d ms st7789-test:" % ticks_ms(), *items)


def clear_ws2812():
    pixels = neopixel.NeoPixel(Pin(WS2812_DATA, Pin.OUT), WS2812_COUNT)
    pixels.fill((0, 0, 0))
    pixels.write()
    log("WS2812: switched off", WS2812_COUNT, "pixels on D11")


def main():
    log("ST7789 shared-SPI3 bring-up")
    log("pins: SCK/D8 MOSI/D10 DC/D3 (shared); CS/D6 RESET/D0 BL/D14 (TFT)")
    log("geometry:", WIDTH, "x", HEIGHT)
    log("SPI clock:", SPI_HZ, "Hz")
    clear_ws2812()

    # SPI(2) is ESP-IDF SPI3. The firmware permits it to attach to the SPI3
    # bus already created by epaper, without taking that bus away from it.
    # Use the known-good e-paper rate while validating this shared wiring.
    spi = SPI(2, baudrate=SPI_HZ, polarity=0, phase=0,
              sck=Pin(SCK), mosi=Pin(MOSI), miso=None)
    tft = st7789.ST7789(
        spi, WIDTH, HEIGHT,
        cs=Pin(CS, Pin.OUT, value=1),
        dc=Pin(DC, Pin.OUT, value=0),
        reset=Pin(RESET, Pin.OUT, value=1),
        backlight=Pin(BACKLIGHT, Pin.OUT, value=0),
        # {MADCTL, width, height, column offset, row offset}.  The 76x284
        # ST7789P3 bar panel is centred in the controller's 240x320 GRAM:
        # (240 - 76) / 2 = 82 and (320 - 284) / 2 = 18.  Addressing it from
        # (0, 0) sends pixels to inactive GRAM and causes the characteristic
        # noisy/partial image seen with generic ST7789 configurations.
        rotations=(
            (0x00, 76, 284, 82, 18),
            (0x60, 284, 76, 18, 82),
            (0xC0, 76, 284, 82, 18),
            (0xA0, 284, 76, 18, 82),
        ),
        # The working 76x284 reference uses portrait rotation 0.
        rotation=0,
        color_order=st7789.RGB,
        inversion=False,
    )

    log("initialising ST7789")
    tft.init()
    log("drawing RGB test fields")
    third = WIDTH // 3
    tft.fill(st7789.BLACK)
    tft.fill_rect(0, 0, third, HEIGHT, st7789.RED)
    tft.fill_rect(third, 0, third, HEIGHT, st7789.GREEN)
    tft.fill_rect(third * 2, 0, WIDTH - third * 2, HEIGHT, st7789.BLUE)
    tft.rect(0, 0, WIDTH, HEIGHT, st7789.WHITE)
    log("test complete; inspect colour order, inversion, and orientation")
    return tft


if __name__ == "__main__":
    main()
