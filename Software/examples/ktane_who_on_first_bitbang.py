"""Who on First 4.2-inch e-paper/touch test using bit-banged SPI.

This is the bit-bang counterpart to ktane_who_on_first.py.  It has the same
six-button screen and FT6336 touch handling, but it never creates a hardware
SPI object: SSD1683 traffic is clocked manually on D8/SCK and D10/SDI.

Current wiring: RESET D1, BUSY D2, DC D3, CS D7, SCK D8, SDI D10;
FT6336 SDA D4, SCL D5, reset D6.  D9 is not used by this panel.
"""

from machine import I2C, Pin
from time import sleep_ms, sleep_us, ticks_diff, ticks_ms
import framebuf


EPD_RESET = 2
EPD_BUSY = 3
EPD_DC = 4
EPD_CS = 44
EPD_SCK = 7
EPD_SDI = 9
TOUCH_SDA = 5
TOUCH_SCL = 6
TOUCH_RESET = 43

WIDTH = 400
HEIGHT = 300
BYTES_PER_ROW = WIDTH // 8
BUFFER_BYTES = BYTES_PER_ROW * HEIGHT
BUSY_TIMEOUT_MS = 3_000
CLOCK_DELAY_US = 1
FT6336_ADDRESS = 0x38
BUTTON_COLUMNS = 2
BUTTON_ROWS = 3
BUTTON_WIDTH = WIDTH // BUTTON_COLUMNS
BUTTON_HEIGHT = HEIGHT // BUTTON_ROWS


class SSD1683BitBang:
    """SSD1683 driver using manual SPI mode 0 and a shared SDI pin."""

    def __init__(self):
        self.cs = Pin(EPD_CS, Pin.OUT, value=1)
        self.dc = Pin(EPD_DC, Pin.OUT, value=0)
        self.clock = Pin(EPD_SCK, Pin.OUT, value=0)
        self.reset_pin = Pin(EPD_RESET, Pin.OUT, value=1)
        self.busy = Pin(EPD_BUSY, Pin.IN)
        self.sdi = Pin(EPD_SDI, Pin.OUT, value=0)

    def _sdi_output(self, value=0):
        self.sdi = Pin(EPD_SDI, Pin.OUT, value=value)

    def _sdi_input(self):
        self.sdi = Pin(EPD_SDI, Pin.IN)

    def _write_byte(self, value):
        for bit in range(7, -1, -1):
            self.sdi.value((value >> bit) & 1)
            sleep_us(CLOCK_DELAY_US)
            self.clock.on()
            sleep_us(CLOCK_DELAY_US)
            self.clock.off()

    def _write(self, is_data, values):
        if isinstance(values, int):
            values = bytes((values,))
        self._sdi_output()
        self.dc.value(1 if is_data else 0)
        # The supplied GooDisplay demo strobes CS for every byte.
        for value in values:
            self.cs.off()
            self._write_byte(value)
            self.cs.on()

    def command(self, value):
        self._write(False, value)

    def data(self, values):
        self._write(True, values)

    def read_register(self, command, count=1):
        """Read SSD1683 data back on its shared D10/SDI line."""
        self._sdi_output()
        self.cs.on()
        self.dc.off()
        self.cs.off()
        self._write_byte(command)
        self.dc.on()
        self._sdi_input()
        values = bytearray(count)
        for index in range(count):
            value = 0
            for _ in range(8):
                self.clock.on()
                sleep_us(CLOCK_DELAY_US)
                self.clock.off()
                sleep_us(CLOCK_DELAY_US)
                value = (value << 1) | self.sdi.value()
            values[index] = value
        self.cs.on()
        self._sdi_output()
        print("SSD1683 SDI read 0x%02X ->" % command,
              " ".join("0x%02X" % value for value in values))
        return values

    def wait_ready(self, label, timeout_ms=BUSY_TIMEOUT_MS):
        started = ticks_ms()
        print("EPD waiting:", label, "BUSY=", self.busy.value())
        while self.busy.value():
            if ticks_diff(ticks_ms(), started) > timeout_ms:
                print("EPD timeout:", label, "after", timeout_ms, "ms")
                return False
            sleep_ms(10)
        print("EPD ready:", label, "after", ticks_diff(ticks_ms(), started), "ms")
        return True

    def reset(self):
        print("EPD reset: RESET/D1 low then high")
        self.reset_pin.off()
        sleep_ms(10)
        self.reset_pin.on()
        sleep_ms(10)

    def _configure_ram(self):
        self.command(0x21)
        self.data(bytes((0x40, 0x00)))
        self.command(0x3C)
        self.data(0x05)
        self.command(0x11)
        self.data(0x01)
        self.command(0x44)
        self.data(bytes((0x00, 0x31)))
        self.command(0x45)
        self.data(bytes((0x2B, 0x01, 0x00, 0x00)))
        self.command(0x4E)
        self.data(0x00)
        self.command(0x4F)
        self.data(bytes((0x2B, 0x01)))

    def init(self):
        """Normal SSD1683 init; retry reset if BUSY does not clear."""
        attempt = 0
        while True:
            attempt += 1
            print("EPD init attempt", attempt, "(bit-bang)")
            self.reset()
            if not self.wait_ready("hardware reset"):
                continue
            self.command(0x12)
            if not self.wait_ready("software reset"):
                continue
            self._configure_ram()
            if self.wait_ready("RAM pointer setup"):
                return

    def _write_framebuffer(self, buffer):
        # The panel scan is right-to-left relative to MONO_HMSB rows.
        for row_start in range(0, BUFFER_BYTES, BYTES_PER_ROW):
            for offset in range(BYTES_PER_ROW - 1, -1, -1):
                self.data(buffer[row_start + offset])

    def display(self, buffer):
        if len(buffer) != BUFFER_BYTES:
            raise ValueError("wrong framebuffer size")
        print("EPD full refresh: bit-bang writing", len(buffer), "bytes x2")
        self.command(0x24)
        self._write_framebuffer(buffer)
        self.command(0x26)
        self._write_framebuffer(buffer)
        self.command(0x22)
        self.data(0xF7)
        self.command(0x20)
        if not self.wait_ready("full refresh"):
            print("EPD full refresh timed out; reinitialising")
            self.init()
            self.display(buffer)

    def init_fast(self):
        """Manufacturer fast-refresh setup used before local updates."""
        while True:
            self.reset()
            if not self.wait_ready("fast hardware reset"):
                continue
            self.command(0x12)
            if not self.wait_ready("fast software reset"):
                continue
            self.command(0x21)
            self.data(bytes((0x40, 0x00)))
            self.command(0x3C)
            self.data(0x05)
            self.command(0x1A)
            self.data(0x6E)
            self.command(0x22)
            self.data(0x91)
            self.command(0x20)
            if not self.wait_ready("fast temperature load"):
                continue
            self.command(0x11)
            self.data(0x01)
            self.command(0x44)
            self.data(bytes((0x00, 0x31)))
            self.command(0x45)
            self.data(bytes((0x2B, 0x01, 0x00, 0x00)))
            self.command(0x4E)
            self.data(0x00)
            self.command(0x4F)
            self.data(bytes((0x2B, 0x01)))
            if self.wait_ready("fast RAM pointer setup"):
                return

    def set_partial_base_map(self, buffer):
        self.init_fast()
        print("EPD partial base map: bit-bang writing", len(buffer), "bytes x2")
        self.command(0x24)
        self._write_framebuffer(buffer)
        self.command(0x26)
        self._write_framebuffer(buffer)
        self.command(0x22)
        self.data(0xC7)
        self.command(0x20)
        if not self.wait_ready("fast base-map refresh"):
            self.set_partial_base_map(buffer)

    def display_partial(self, buffer, x, y, width, height):
        if x % 8 or width % 8:
            raise ValueError("partial X and width must be divisible by 8")
        source_x_start = x // 8
        source_x_end = source_x_start + width // 8 - 1
        ram_x_start = BYTES_PER_ROW - 1 - source_x_end
        ram_x_end = BYTES_PER_ROW - 1 - source_x_start
        ram_y_start = HEIGHT - 1 - y
        ram_y_end = HEIGHT - (y + height)
        print("EPD partial bit-bang x=%d y=%d w=%d h=%d" %
              (x, y, width, height))
        self.reset()
        if not self.wait_ready("partial hardware reset"):
            return self.display_partial(buffer, x, y, width, height)
        self.command(0x21)
        self.data(bytes((0x00, 0x00)))
        self.command(0x3C)
        self.data(0x80)
        self.command(0x11)
        self.data(0x01)
        self.command(0x44)
        self.data(bytes((ram_x_start, ram_x_end)))
        self.command(0x45)
        self.data(bytes((ram_y_start & 0xFF, ram_y_start >> 8,
                         ram_y_end & 0xFF, ram_y_end >> 8)))
        self.command(0x4E)
        self.data(ram_x_start)
        self.command(0x4F)
        self.data(bytes((ram_y_start & 0xFF, ram_y_start >> 8)))
        self.command(0x24)
        for row in range(y, y + height):
            row_start = row * BYTES_PER_ROW
            for source_x in range(source_x_end, source_x_start - 1, -1):
                self.data(buffer[row_start + source_x])
        self.command(0x22)
        self.data(0xFF)
        self.command(0x20)
        if not self.wait_ready("partial refresh"):
            return self.display_partial(buffer, x, y, width, height)


class FT6336:
    EVENT_NAMES = ("down", "up", "contact", "reserved")

    def __init__(self):
        self.reset_pin = Pin(TOUCH_RESET, Pin.OUT, value=1)
        self.i2c = I2C(0, sda=Pin(TOUCH_SDA), scl=Pin(TOUCH_SCL), freq=400_000)

    def init(self):
        self.reset_pin.off()
        sleep_ms(10)
        self.reset_pin.on()
        sleep_ms(200)
        if FT6336_ADDRESS not in self.i2c.scan():
            raise RuntimeError("FT6336 not found")
        chip = self.i2c.readfrom_mem(FT6336_ADDRESS, 0xA3, 1)[0]
        firmware = self.i2c.readfrom_mem(FT6336_ADDRESS, 0xA6, 1)[0]
        print("FT6336 ready: chip=0x%02X firmware=0x%02X" % (chip, firmware))

    def read_touches(self):
        data = self.i2c.readfrom_mem(FT6336_ADDRESS, 0x02, 13)
        touches = []
        for index in range(min(data[0] & 0x0F, 2)):
            offset = 1 + index * 6
            event = data[offset] >> 6
            x = ((data[offset] & 0x0F) << 8) | data[offset + 1]
            y = ((data[offset + 2] & 0x0F) << 8) | data[offset + 3]
            touches.append((data[offset + 2] >> 4, self.EVENT_NAMES[event], x, y))
        return touches


def draw_centered_text(canvas, label, center_x, center_y, scale=4):
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


def draw_button(canvas, x, y, width, height, label):
    border = 10
    canvas.fill_rect(x, y, width, height, 0)
    canvas.fill_rect(x + border, y + border, width - border * 2, height - border * 2, 1)
    draw_centered_text(canvas, label, x + width // 2, y + height // 2)


def make_screen():
    buffer = bytearray(b"\xFF" * BUFFER_BYTES)
    canvas = framebuf.FrameBuffer(buffer, WIDTH, HEIGHT, framebuf.MONO_HMSB)
    for index, label in enumerate(("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX")):
        x = (index % BUTTON_COLUMNS) * BUTTON_WIDTH
        y = (index // BUTTON_COLUMNS) * BUTTON_HEIGHT
        draw_button(canvas, x, y, BUTTON_WIDTH, BUTTON_HEIGHT, label)
    return buffer


def button_index_for_touch(x, y):
    # The touch-overlay origin is 180 degrees from the displayed framebuffer.
    x = WIDTH - 1 - x
    y = HEIGHT - 1 - y
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        return None
    return (y // BUTTON_HEIGHT) * BUTTON_COLUMNS + x // BUTTON_WIDTH


def invert_button(buffer, index):
    column = index % BUTTON_COLUMNS
    row = index // BUTTON_COLUMNS
    x_byte_start = column * BUTTON_WIDTH // 8
    x_byte_end = x_byte_start + BUTTON_WIDTH // 8
    y_start = row * BUTTON_HEIGHT
    for y in range(y_start, y_start + BUTTON_HEIGHT):
        base = y * BYTES_PER_ROW
        for x_byte in range(x_byte_start, x_byte_end):
            buffer[base + x_byte] ^= 0xFF
    return column * BUTTON_WIDTH, y_start, BUTTON_WIDTH, BUTTON_HEIGHT


def restore_button(display, buffer, index):
    rect = invert_button(buffer, index)
    print("button", index + 1, "released; full refresh restoring", rect)
    display.init()
    display.display(buffer)
    display.set_partial_base_map(buffer)


def main():
    print("Who on First: bit-banged SSD1683 + FT6336 test")
    print("EPD D3/DC D7/CS D8/SCK D10/SDI; touch D4/SDA D5/SCL D6/RESET")
    touch = FT6336()
    touch.init()
    display = SSD1683BitBang()
    display.init()
    display.read_register(0x2F)  # status, returned through the same D10 pin
    buffer = make_screen()
    display.display(buffer)
    display.set_partial_base_map(buffer)
    print("Display ready; touch rectangles. Ctrl-C stops.")
    active = {}
    while True:
        touches = touch.read_touches()
        seen = set()
        for touch_id, event, x, y in touches:
            seen.add(touch_id)
            if event == "up":
                index = active.pop(touch_id, None)
                if index is not None:
                    restore_button(display, buffer, index)
                continue
            if event != "contact" or touch_id in active:
                continue
            index = button_index_for_touch(x, y)
            if index is None:
                continue
            rect = invert_button(buffer, index)
            active[touch_id] = index
            print("button", index + 1, "contact; inverting", rect)
            display.display_partial(buffer, *rect)
        for touch_id in tuple(active):
            if touch_id not in seen:
                restore_button(display, buffer, active.pop(touch_id))
        sleep_ms(40)


try:
    main()
finally:
    Pin(EPD_CS, Pin.OUT, value=1)
    Pin(EPD_SCK, Pin.OUT, value=0)
