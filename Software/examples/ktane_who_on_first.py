"""Bring-up test for the KTANE Who's on First 4.2-inch touch e-paper module.

Panel: GooDisplay S-GDEY042T81-FP Touch, 400x300 monochrome, SSD1683.
Touch: FT6336 at I2C address 0x38.

XIAO ESP32-S3 wiring (D-pin labels):
  e-paper: DC D3, SS D7, SCK D8, MISO D9, MOSI D10, BUSY D2, RESET D1
  touch:   SDA D4, SCL D5, RESET D0 (shared with TFT RESET)

This is only a display/touch hardware test. It uses the firmware-built
``epaper`` usermod for SSD1683 transfers, and Python only for the retained
framebuffer and FT6336 touch handling. It is not the Who's on First game.
"""

from machine import I2C, Pin
from time import sleep_ms, ticks_diff, ticks_ms
import framebuf
import epaper
import tft


# XIAO ESP32-S3 GPIO numbers corresponding to the stated D-pin labels.
EPD_DC = 4        # D3; verified by the pin exerciser on the current wiring
EPD_CS = 44       # D7 / SS
EPD_SCK = 7       # D8
EPD_MISO = 8      # D9 (not used by the e-paper controller, kept for SPI)
EPD_MOSI = 9      # D10
TOUCH_SDA = 5     # D4
TOUCH_SCL = 6     # D5
EPD_BUSY = 3      # D2; SSD1683 BUSY is active high on this module
EPD_RESET = 2     # D1
# TP_RESET shares the TFT RESET net. The native TFT initialisation performs the
# one startup reset pulse; Python only probes FT6336 afterwards.
TOUCH_RESET = 1  # D0

# ST7789P3 2.25-inch 76x284 status display. It shares SPI3 SCK/D8, MOSI/D10
# and DC/D3 with the e-paper panel, but has its own CS, reset and backlight.
TFT_CS = 43       # D6
TFT_RESET = 1     # D0
TFT_BACKLIGHT = 13  # D14; low enables this module's backlight
TFT_WIDTH = 76
TFT_HEIGHT = 284
TFT_SPI_HZ = 10_000_000
WS2812_DATA = 10  # D11
WS2812_COUNT = 4

# The 76x284 active area is centred in ST7789P3's 240x320 GRAM.
TFT_ROTATIONS = (
    (0x00, 76, 284, 82, 18),
    (0x60, 284, 76, 18, 82),
    (0xC0, 76, 284, 82, 18),
    (0xA0, 284, 76, 18, 82),
)

WIDTH = 400
HEIGHT = 300
BYTES_PER_ROW = WIDTH // 8
BUFFER_BYTES = BYTES_PER_ROW * HEIGHT
FT6336_ADDRESS = 0x38
BUSY_TIMEOUT_MS = 6_000
BUTTON_COLUMNS = 2
BUTTON_ROWS = 3
BUTTON_WIDTH = WIDTH // BUTTON_COLUMNS
BUTTON_HEIGHT = HEIGHT // BUTTON_ROWS


def log(*items):
    print("%d ms who-first:" % ticks_ms(), *items)


class FT6336:
    """Small polling driver for the two-point FT6336 touch controller."""

    EVENT_NAMES = ("down", "up", "contact", "reserved")

    def __init__(self):
        self.reset_pin = Pin(TOUCH_RESET, Pin.OUT, value=1)
        self.i2c = I2C(0, sda=Pin(TOUCH_SDA), scl=Pin(TOUCH_SCL), freq=400_000)

    def reset(self):
        self.reset_pin.off()
        sleep_ms(10)
        self.reset_pin.on()
        sleep_ms(200)

    def init(self, reset=True):
        if reset:
            self.reset()
        devices = self.i2c.scan()
        if FT6336_ADDRESS not in devices:
            raise RuntimeError("FT6336 not found; I2C scan: %s" % [hex(x) for x in devices])
        firmware = self.i2c.readfrom_mem(FT6336_ADDRESS, 0xA6, 1)[0]
        chip_id = self.i2c.readfrom_mem(FT6336_ADDRESS, 0xA3, 1)[0]
        log("FT6336 ready: chip=0x%02X firmware=0x%02X" % (chip_id, firmware))

    def read_touches(self):
        """Return active touch points as (id, event, x, y) tuples."""
        # 0x02 is count; each contact occupies six bytes beginning at 0x03.
        data = self.i2c.readfrom_mem(FT6336_ADDRESS, 0x02, 13)
        count = min(data[0] & 0x0F, 2)
        touches = []
        for index in range(count):
            offset = 1 + index * 6
            event_code = data[offset] >> 6
            x = ((data[offset] & 0x0F) << 8) | data[offset + 1]
            y = ((data[offset + 2] & 0x0F) << 8) | data[offset + 3]
            touch_id = data[offset + 2] >> 4
            touches.append((touch_id, self.EVENT_NAMES[event_code], x, y))
        return touches


class TFTButtonDisplay:
    """Show the latest e-paper button number on the ST7789 status TFT."""

    def init(self):
        log("TFT init: ST7789P3 CS/D6 RESET/D0 BL/D14; shared SPI3/DC D3")
        tft.init(TFT_CS, EPD_DC, TFT_RESET, TFT_BACKLIGHT, EPD_SCK, EPD_MOSI)
        # Startup wording belongs to the module's Python program.  The native
        # usermod receives the text and performs the low-level TFT transfer.
        tft.text("Who's on first")
        log("TFT native status:", tft.status())
        log("TFT ready: touch a numbered e-paper button to update it")

    def show_number(self, number):
        tft.show_digit(number)
        log("TFT showing button", number)


def draw_centered_text(canvas, label, center_x, center_y, scale=4):
    """Draw a centred, scaled built-in MicroPython text label."""
    glyph_width = len(label) * 8
    glyph_height = 8
    source_bytes = (glyph_width + 7) // 8 * glyph_height
    source = bytearray(source_bytes)
    glyphs = framebuf.FrameBuffer(source, glyph_width, glyph_height, framebuf.MONO_HMSB)
    glyphs.text(label, 0, 0, 1)

    x_origin = center_x - (glyph_width * scale) // 2
    y_origin = center_y - (glyph_height * scale) // 2
    for y in range(glyph_height):
        for x in range(glyph_width):
            if glyphs.pixel(x, y):
                canvas.fill_rect(x_origin + x * scale, y_origin + y * scale, scale, scale, 0)


def draw_button(canvas, x, y, width, height, label):
    """Draw one white button with a 10-pixel black border and centred text."""
    border = 10
    canvas.fill_rect(x, y, width, height, 0)
    canvas.fill_rect(x + border, y + border, width - border * 2, height - border * 2, 1)
    draw_centered_text(canvas, label, x + width // 2, y + height // 2)


def button_index_for_touch(x, y):
    """Map raw FT6336 coordinates into the matching visible rectangle.

    The touch overlay's origin is opposite the displayed framebuffer origin,
    so transform its coordinates by 180 degrees before button hit-testing.
    """
    x = WIDTH - 1 - x
    y = HEIGHT - 1 - y
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        return None
    column = x // BUTTON_WIDTH
    row = y // BUTTON_HEIGHT
    return row * BUTTON_COLUMNS + column


def invert_button(buffer, button_index):
    """Invert one byte-aligned button rectangle in the retained framebuffer."""
    column = button_index % BUTTON_COLUMNS
    row = button_index // BUTTON_COLUMNS
    x_byte_start = column * BUTTON_WIDTH // 8
    x_byte_end = x_byte_start + BUTTON_WIDTH // 8
    y_start = row * BUTTON_HEIGHT
    y_end = y_start + BUTTON_HEIGHT
    for y in range(y_start, y_end):
        row_start = y * BYTES_PER_ROW
        for x_byte in range(x_byte_start, x_byte_end):
            buffer[row_start + x_byte] ^= 0xFF
    return column * BUTTON_WIDTH, y_start, BUTTON_WIDTH, BUTTON_HEIGHT


def restore_button_with_full_refresh(buffer, button_index):
    """Clear a momentary press with one clean full refresh.

    Native ``epaper.full`` loads both SSD1683 RAM planes before triggering the
    normal waveform, so it is already the required differential-update base.
    Calling ``base_map`` afterwards would trigger a second, unnecessary full
    refresh.
    """
    rect = invert_button(buffer, button_index)
    log("button", button_index + 1, "released; full refresh restoring", rect)
    # The local waveform can retain artefacts outside its nominal window on
    # this panel. A normal full refresh clears those artefacts and restores
    # both controller RAM planes to the retained framebuffer.
    native_epaper_init()
    log("EPD native full refresh:", len(buffer), "bytes")
    epaper.full(buffer)


def native_epaper_init():
    """Initialise the compiled C/C++ SSD1683 usermod on the shared SPI3 bus."""
    log("EPD native init: SPI3, CS/D7 DC/D3 RESET/D1 BUSY/D2 SCK/D8 MOSI/D10")
    epaper.init(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY, EPD_SCK, EPD_MOSI)
    log("EPD native status:", epaper.status())


def make_test_screen():
    """Return the six-button layout used for the future Who's on First UI."""
    buffer = bytearray(b"\xFF" * BUFFER_BYTES)  # EPD: 1 is white, 0 is black.
    canvas = framebuf.FrameBuffer(buffer, WIDTH, HEIGHT, framebuf.MONO_HMSB)
    labels = ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX")
    for index, label in enumerate(labels):
        column = index % 2
        row = index // 2
        draw_button(canvas, column * BUTTON_WIDTH, row * BUTTON_HEIGHT,
                    BUTTON_WIDTH, BUTTON_HEIGHT, label)
    log("framebuffer ready:", len(buffer), "bytes; white=0xFF, black text=0 bits")
    return buffer


def main():
    log("Who's on First e-paper/touch bring-up (native SSD1683 usermod)")
    log("EPD native SPI: DC D3, SS D7, SCK D8, MOSI D10, BUSY D2, RESET D1")
    log("Touch I2C: SDA D4, SCL D5, RESET D0 (shared with TFT RESET)")

    # Native TFT init supplies the shared D0 reset pulse for both TFT and
    # FT6336. Do it before probing the touch controller.
    tft = TFTButtonDisplay()
    tft.init()
    sleep_ms(200)
    touch = FT6336()
    touch.init(reset=False)
    log("initialising native SSD1683 and performing full refresh...")
    native_epaper_init()
    buffer = make_test_screen()
    log("EPD native full refresh:", len(buffer), "bytes")
    epaper.full(buffer)
    # This panel needs the native driver's explicit differential baseline
    # before its first 0xFC partial waveform.  Without it BUSY can remain
    # asserted until the timeout, which then forces a much slower recovery
    # full refresh.  It costs one extra refresh only at boot.
    log("EPD native synchronising partial-update RAM planes")
    epaper.base_map(buffer)
    log("display updated; touch the panel (Ctrl-C to stop)")

    previous = None
    active_buttons = {}  # FT6336 touch id -> momentarily inverted button index
    while True:
        touches = touch.read_touches()
        current = tuple(touches)
        if current != previous:
            if current:
                for touch_id, event, x, y in current:
                    if event in ("contact", "up"):
                        log("touch id=%d event=%s raw=(%d,%d) screen=(%d,%d)" %
                            (touch_id, event, x, y, WIDTH - 1 - x, HEIGHT - 1 - y))
            elif previous:
                log("touch released")
            previous = current

        seen_ids = set()
        for touch_id, event, x, y in touches:
            seen_ids.add(touch_id)
            if event == "up":
                button_index = active_buttons.pop(touch_id, None)
                if button_index is not None:
                    restore_button_with_full_refresh(buffer, button_index)
                continue
            if event != "contact" or touch_id in active_buttons:
                continue
            button_index = button_index_for_touch(x, y)
            if button_index is None:
                log("contact outside button area")
                continue
            rect = invert_button(buffer, button_index)
            active_buttons[touch_id] = button_index
            log("button", button_index + 1, "contact; inverting", rect)
            # The TFT retains the selected number until the next e-paper
            # contact; releasing the e-paper button only restores its visual
            # pressed state.
            tft.show_number(button_index + 1)
            log("EPD native partial x=%d y=%d w=%d h=%d" % rect)
            epaper.partial(buffer, *rect)

        # Some FT6336 firmware revisions report a release as zero touches
        # rather than a final point with event=up.  Restore those too.
        for touch_id in tuple(active_buttons):
            if touch_id not in seen_ids:
                button_index = active_buttons.pop(touch_id)
                restore_button_with_full_refresh(buffer, button_index)
        sleep_ms(40)


main()
