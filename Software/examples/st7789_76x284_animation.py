"""Small left-to-right animation for the 76x284 ST7789P3 bar display.

Uses the verified pinout and controller offsets.  It updates only the old and
new bar positions on each frame rather than rewriting the whole display.
"""

from machine import Pin, SPI
from time import sleep_ms, ticks_ms
import neopixel
import st7789


WIDTH = 76
HEIGHT = 284
SPI_HZ = 10_000_000

SCK = 7             # D8, shared SPI clock
MOSI = 9            # D10, shared SPI data
DC = 4              # D3, shared command/data
CS = 43             # D6, TFT chip select
RESET = 1           # D0, TFT reset
BACKLIGHT = 13      # D14, active-low backlight

WS2812_DATA = 10    # D11
WS2812_COUNT = 4

BAR_WIDTH = 12
FRAME_MS = 40

ROTATIONS = (
    (0x00, 76, 284, 82, 18),
    (0x60, 284, 76, 18, 82),
    (0xC0, 76, 284, 82, 18),
    (0xA0, 284, 76, 18, 82),
)


def log(*items):
    print("%d ms st7789-animation:" % ticks_ms(), *items)


def make_display():
    pixels = neopixel.NeoPixel(Pin(WS2812_DATA, Pin.OUT), WS2812_COUNT)
    pixels.fill((0, 0, 0))
    pixels.write()

    spi = SPI(2, baudrate=SPI_HZ, polarity=0, phase=0,
              sck=Pin(SCK), mosi=Pin(MOSI), miso=None)
    tft = st7789.ST7789(
        spi, WIDTH, HEIGHT,
        cs=Pin(CS, Pin.OUT, value=1),
        dc=Pin(DC, Pin.OUT, value=0),
        reset=Pin(RESET, Pin.OUT, value=1),
        backlight=Pin(BACKLIGHT, Pin.OUT, value=0),
        rotations=ROTATIONS,
        # X is the display's physical long, left-to-right axis. Rotation 3
        # is the landscape orientation with the desired visual direction.
        rotation=3,
        color_order=st7789.RGB,
        inversion=False,
    )
    tft.init()
    return tft


def main():
    log("initialising 76x284 TFT")
    tft = make_display()
    # Rotation 1 gives the application a landscape 284 x 76 canvas.
    screen_width = HEIGHT
    screen_height = WIDTH
    tft.fill(st7789.BLACK)
    log("left-to-right animation running; Ctrl-C stops")

    colours = (st7789.RED, st7789.GREEN, st7789.BLUE,
               st7789.YELLOW, st7789.CYAN, st7789.MAGENTA)
    colour_index = 0

    while True:
        colour = colours[colour_index]
        tft.fill_rect(0, 0, BAR_WIDTH, screen_height, colour)
        for x in range(0, screen_width - BAR_WIDTH + 1):
            if not x:
                sleep_ms(FRAME_MS)
                continue
            # Erase only the column which is no longer covered by the bar.
            tft.fill_rect(x - 1, 0, 1, screen_height, st7789.BLACK)
            tft.fill_rect(x + BAR_WIDTH - 1, 0, 1, screen_height, colour)
            sleep_ms(FRAME_MS)

        # Cleanly erase the remaining bar at the right edge before the next run.
        tft.fill_rect(screen_width - BAR_WIDTH, 0, BAR_WIDTH, screen_height,
                      st7789.BLACK)
        colour_index = (colour_index + 1) % len(colours)
        sleep_ms(250)


if __name__ == "__main__":
    main()
