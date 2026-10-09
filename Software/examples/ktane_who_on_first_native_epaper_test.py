"""Exercise the firmware-built `epaper` module on the GDEY042T81.

The display transport is ESP-IDF hardware SPI (SPI3), not a Python or
MicroPython bit-banged bus.  Touch is deliberately not initialised here.
Each Who's-on-First button rectangle is locally shown until Enter is pressed,
then locally erased before the next rectangle is drawn. Stop with Ctrl-C.
"""

from time import ticks_ms
import framebuf
import epaper


WIDTH = 400
HEIGHT = 300
BYTES_PER_ROW = WIDTH // 8
FRAMEBUFFER_BYTES = BYTES_PER_ROW * HEIGHT
BUTTON_WIDTH = 200
BUTTON_HEIGHT = 100
LABELS = ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX")

# GPIO numbers for the current XIAO wiring.  They are deliberately supplied
# to the native module; the firmware contains no display-board pin mapping.
EPD_CS = 44       # D7
EPD_DC = 4        # D3
EPD_RESET = 2     # D1
EPD_BUSY = 3      # D2
EPD_SCK = 7       # D8
EPD_MOSI = 9      # D10 / panel SDI


def log(*items):
    print("%d ms test:" % ticks_ms(), *items)


def scaled_text(canvas, label, center_x, center_y, scale=4):
    glyph_width = len(label) * 8
    source = bytearray(((glyph_width + 7) // 8) * 8)
    glyphs = framebuf.FrameBuffer(source, glyph_width, 8, framebuf.MONO_HMSB)
    glyphs.text(label, 0, 0, 1)
    x0 = center_x - glyph_width * scale // 2
    y0 = center_y - 4 * scale
    for y in range(8):
        for x in range(glyph_width):
            if glyphs.pixel(x, y):
                canvas.fill_rect(x0 + x * scale, y0 + y * scale, scale, scale, 0)


def blank_frame():
    return bytearray(b"\xff" * FRAMEBUFFER_BYTES)


def button_frame(index):
    frame = blank_frame()
    canvas = framebuf.FrameBuffer(frame, WIDTH, HEIGHT, framebuf.MONO_HMSB)
    x = (index % 2) * BUTTON_WIDTH
    y = (index // 2) * BUTTON_HEIGHT
    border = 10
    canvas.fill_rect(x, y, BUTTON_WIDTH, BUTTON_HEIGHT, 0)
    canvas.fill_rect(x + border, y + border,
                     BUTTON_WIDTH - border * 2, BUTTON_HEIGHT - border * 2, 1)
    scaled_text(canvas, LABELS[index], x + BUTTON_WIDTH // 2, y + BUTTON_HEIGHT // 2)
    return frame


def rectangle(index):
    return ((index % 2) * BUTTON_WIDTH, (index // 2) * BUTTON_HEIGHT,
            BUTTON_WIDTH, BUTTON_HEIGHT)


def main(cycles=None):
    log("Native SSD1683 e-paper test")
    log("initial:", epaper.status())
    epaper.init(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY, EPD_SCK, EPD_MOSI)
    log("after init:", epaper.status())

    blank = blank_frame()
    log("normal full refresh: blank")
    epaper.full(blank)
    log("synchronising current and previous display planes")
    epaper.base_map(blank)
    log("native partial test running; press Enter for next rectangle, Ctrl-C stops")
    completed_cycles = 0
    while cycles is None or completed_cycles < cycles:
        for index, label in enumerate(LABELS):
            rect = rectangle(index)
            log("show", label, rect)
            epaper.partial(button_frame(index), *rect)
            log("display update complete; press Enter to clear", label, "and continue")
            input()
            log("erase", label, rect)
            epaper.partial(blank, *rect)
        completed_cycles += 1
    log("native e-paper test complete")


if __name__ == "__main__":
    main()
