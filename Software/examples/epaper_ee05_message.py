"""Show a message on a XIAO-connected 2.13 inch B/W/R/Y ePaper panel.

Panel: 2.13 inch B/W/R/Y, JD79676 (Seeed GFX screen combo 513).

The program performs one full refresh and puts the panel into deep sleep.  It
therefore leaves the image visible without continuously consuming power.
"""

from machine import Pin, SPI
from time import sleep_ms, ticks_diff, ticks_ms
import framebuf
import os


# Wiring for the attached XIAO ePaper driver board.  These are GPIO numbers
# for the XIAO ESP32-S3, not the D-pin labels printed on the board.
SCK = 7       # XIAO D8
MOSI = 9      # XIAO D10
CS = 2        # XIAO D1
DC = 4        # XIAO D3
BUSY = 3      # XIAO D2; low while the panel is busy
RESET = 1     # XIAO D0

# The controller is physically 128 x 250.  Draw the label on a 250 x 128
# landscape canvas, then rotate it clockwise while transmitting to the panel.
PANEL_WIDTH = 128
PANEL_HEIGHT = 250
WIDTH = PANEL_HEIGHT
HEIGHT = PANEL_WIDTH

WHITE = 1
BLACK = 0
RED = 3
YELLOW = 2
LED = 21  # XIAO ESP32-S3 built-in LED



class JD79676:
    def __init__(self):
        self.cs = Pin(CS, Pin.OUT, value=1)
        self.dc = Pin(DC, Pin.OUT, value=0)
        self.reset_pin = Pin(RESET, Pin.OUT, value=1)
        self.busy = Pin(BUSY, Pin.IN)
        self.spi = SPI(
            1,
            baudrate=10_000_000,
            polarity=0,
            phase=0,
            sck=Pin(SCK),
            mosi=Pin(MOSI),
        )

    def _write(self, is_data, payload):
        self.dc.value(is_data)
        self.cs.off()
        self.spi.write(payload)
        self.cs.on()

    def command(self, value):
        self._write(0, bytes((value,)))

    def data(self, values):
        if isinstance(values, int):
            values = bytes((values,))
        self._write(1, values)

    def wait_ready(self, timeout_ms=45_000):
        started = ticks_ms()
        while not self.busy.value():
            if ticks_diff(ticks_ms(), started) > timeout_ms:
                raise RuntimeError("ePaper panel stayed busy; check the FPC cable and power switch")
            sleep_ms(10)

    def reset(self):
        self.reset_pin.off()
        sleep_ms(20)
        self.reset_pin.on()
        sleep_ms(50)
        self.wait_ready()

    def init(self):
        self.reset()

        # JD79676 initialisation sequence from Seeed GFX's combo 513 driver.
        self.command(0x4D)
        self.data(0x78)
        self.command(0x00)  # panel setting
        self.data(bytes((0x0F, 0x29)))
        self.command(0x01)  # power setting
        self.data(0x07)
        self.command(0x03)
        self.data(bytes((0x10, 0x54, 0x44)))
        self.command(0x06)
        self.data(bytes((0x0F, 0x0A, 0x2F, 0x25, 0x22, 0x2E, 0x21)))
        self.command(0x50)
        self.data(0x37)
        self.command(0x60)
        self.data(bytes((0x02, 0x02)))
        self.command(0x61)  # physical resolution: 128 x 250
        self.data(bytes((0, PANEL_WIDTH, PANEL_HEIGHT >> 8, PANEL_HEIGHT & 0xFF)))
        self.command(0xE7)
        self.data(0x1C)
        self.command(0xE3)
        self.data(0x22)
        self.command(0xB4)
        self.data(0xD0)
        self.command(0xB5)
        self.data(0x03)
        self.command(0xE9)
        self.data(0x01)
        self.command(0x30)
        self.data(0x08)
        self.command(0x04)  # power on
        self.wait_ready()

    def init_fast(self):
        """Manufacturer's no-flicker *full-frame* refresh initialisation.

        Despite the vendor example calling this a "partial update", it always
        follows this sequence by sending all 8,000 display bytes.  Do not use
        it for a rectangular window update: that command format is not supplied
        for this panel/controller.
        """
        sleep_ms(100)
        self.reset_pin.off()
        sleep_ms(10)
        self.reset_pin.on()
        sleep_ms(10)
        self.wait_ready()

        # EPD_init_Fast() from GooDisplay's ESP32 GDEY0213F52 V2.0 sample.
        self.command(0xE0)
        self.data(0x02)
        self.command(0xE6)
        self.data(90)
        self.command(0xA5)
        self.wait_ready()
        self.command(0xE9)
        self.data(0x01)
        self.command(0x04)
        self.wait_ready()

    def display(self, layers):
        """Full-refresh ordered ``(canvas, colour)`` 1-bit FrameBuffer layers."""
        self._write_window(layers, 0, 0, PANEL_WIDTH, PANEL_HEIGHT)

        self.command(0x12)  # display refresh
        self.data(0x00)
        self.wait_ready()

    def _write_window(self, layers, x_start, y_start, width, height):
        """Send a physical, four-colour pixel window. x bounds are 4-pixel aligned."""
        self.command(0x10)  # four-colour display-data transmission
        row = bytearray(width // 4)  # 2 bits per output pixel
        for y in range(y_start, y_start + height):
            for group in range(width // 4):
                x = x_start + group * 4
                packed = 0
                for pixel_x in range(x, x + 4):
                    # Inverse of a 90-degree clockwise rotation: the physical
                    # portrait pixel comes from the landscape drawing canvas.
                    canvas_x = y
                    canvas_y = HEIGHT - 1 - pixel_x
                    colour = WHITE
                    for canvas, layer_colour in layers:
                        if canvas.pixel(canvas_x, canvas_y):
                            colour = layer_colour
                    packed = (packed << 2) | colour
                row[group] = packed
            self.data(row)

    def display_partial(self, layers, x_start, y_start, width, height):
        """Disabled until the manufacturer fast-refresh command sequence is verified."""
        raise NotImplementedError("JD79676 partial refresh is not yet verified")

    def sleep(self):
        self.command(0x02)  # power off
        self.wait_ready()
        sleep_ms(100)
        self.command(0x07)  # deep sleep
        self.data(0xA5)


def new_canvas():
    """Create a transparent 1-bit drawing layer."""
    # MONO_HLSB pads each row up to a whole byte.  The landscape canvas is
    # 250 pixels wide, so each 128 rows needs 32 bytes (not 31.25).
    backing = bytearray(((WIDTH + 7) // 8) * HEIGHT)
    return framebuf.FrameBuffer(backing, WIDTH, HEIGHT, framebuf.MONO_HLSB)


def draw_scaled_text(canvas, text, x, y, scale):
    """Draw MicroPython's built-in font at an integer scale."""
    glyph_width = len(text) * 8
    backing = bytearray(((glyph_width + 7) // 8) * 8)
    glyphs = framebuf.FrameBuffer(backing, glyph_width, 8, framebuf.MONO_HLSB)
    glyphs.text(text, 0, 0, 1)
    for glyph_y in range(8):
        for glyph_x in range(glyph_width):
            if glyphs.pixel(glyph_x, glyph_y):
                canvas.fill_rect(x + glyph_x * scale, y + glyph_y * scale, scale, scale, 1)


def random_serial():
    """Return a new 6-character serial; O/Y are excluded and the last is a digit."""
    # ``os.urandom`` is backed by ESP32's hardware random-number generator.
    letters = "ABCDEFGHJKLMNPQRSTUVWXZ"
    digits = "0123456789"
    alphabet = digits + letters
    # Guarantee a mixture: one letter and one digit in the first five places,
    # then place them at random positions among the remaining mixed characters.
    first_five = [
        letters[os.urandom(1)[0] % len(letters)],
        digits[os.urandom(1)[0] % len(digits)],
        alphabet[os.urandom(1)[0] % len(alphabet)],
        alphabet[os.urandom(1)[0] % len(alphabet)],
        alphabet[os.urandom(1)[0] % len(alphabet)],
    ]
    for index in range(4, 0, -1):
        swap_index = os.urandom(1)[0] % (index + 1)
        first_five[index], first_five[swap_index] = first_five[swap_index], first_five[index]
    return "".join(first_five) + digits[os.urandom(1)[0] % len(digits)]


def serial_ticket(serial):
    """Render a red-and-white serial-number ticket in the panel's palette."""
    red = new_canvas()
    white = new_canvas()
    black = new_canvas()

    # Edge-to-edge ticket: red top section, white lower section.
    header_height = 48
    red.fill_rect(0, 0, WIDTH, header_height, 1)

    # Full-width white serial area with a black outline.
    white.fill_rect(0, header_height, WIDTH, HEIGHT - header_height, 1)
    black.rect(0, header_height, WIDTH, HEIGHT - header_height, 1)

    # White lettering on the red header -- yellow is not used in this design.
    draw_scaled_text(white, "SERIAL #", (WIDTH - len("SERIAL #") * 16) // 2, 16, 2)
    draw_scaled_text(black, serial, (WIDTH - len(serial) * 32) // 2, 72, 4)
    return ((red, RED), (white, WHITE), (black, BLACK))


def blink(count, on_ms=150, off_ms=150):
    """Use the built-in LED as an execution-progress indicator."""
    led = Pin(LED, Pin.OUT, value=0)
    for _ in range(count):
        led.on()
        sleep_ms(on_ms)
        led.off()
        sleep_ms(off_ms)


def show_new_serial():
    """Generate and full-refresh a new ticket (the first update after boot)."""
    display = JD79676()
    display.init()
    serial = random_serial()
    display.display(serial_ticket(serial))
    display.sleep()
    return serial


def refresh_new_serial():
    """Fast no-flicker update, but still redraws the complete ticket.

    The manufacturer sample sends every physical pixel on each fast refresh;
    the red heading is therefore retransmitted as well, even though unchanged.
    """
    display = JD79676()
    display.init_fast()
    serial = random_serial()
    display.display(serial_ticket(serial))
    display.sleep()
    return serial


# One blink means main.py has started.  Three blinks means the panel reported
# its refresh complete.  Ten rapid blinks means an exception stopped the update.
if __name__ == "__main__":
    blink(1, 500, 100)
    try:
        show_new_serial()
        blink(3)
    except Exception as error:
        # Preserve the failure across reset so it can be retrieved with mpremote.
        import sys
        with open("epaper-error.txt", "w") as error_file:
            sys.print_exception(error, error_file)
        blink(10, 80, 80)
        raise
