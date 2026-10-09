"""SSD1683 bit-banged SPI and single-wire SDI readback test.

This test intentionally does not initialise or access the FT6336 touch panel.
It uses the current verified e-paper wiring:

  RESET D1/GPIO2, BUSY D2/GPIO3, D/C D3/GPIO4,
  CS D7/GPIO44, SCK D8/GPIO7, SDI D10/GPIO9.

The SSD1683 uses a single bidirectional SDA/SDI pin for 4-wire SPI reads.
D9/MISO is not used: it is not connected to the panel.  For read commands,
this script sends the command on D10, releases D10 as an input, and clocks the
returned bits from that same pin.  The console prints command 0x2F status and
command 0x1B temperature-register readback, then cycles partial-refresh
rectangles through the six future button positions.
"""

from machine import Pin
from time import sleep_ms, sleep_us, ticks_diff, ticks_ms
import framebuf


EPD_RESET = 2  # D1
EPD_BUSY = 3   # D2, active high
EPD_DC = 4     # D3
EPD_CS = 44    # D7
EPD_SCK = 7    # D8
EPD_SDI = 9    # D10, bidirectional panel SDA

WIDTH = 400
HEIGHT = 300
BYTES_PER_ROW = WIDTH // 8
BUFFER_BYTES = BYTES_PER_ROW * HEIGHT
BUSY_TIMEOUT_MS = 10_000
CLOCK_DELAY_US = 1
BUTTON_COLUMNS = 2
BUTTON_ROWS = 3
BUTTON_WIDTH = WIDTH // BUTTON_COLUMNS
BUTTON_HEIGHT = HEIGHT // BUTTON_ROWS
SHOW_TIME_MS = 2_000


class SSD1683BitBang:
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
        """SPI mode-0, MSB-first bit-banged byte; CS is already low."""
        for bit in range(7, -1, -1):
            self.sdi.value((value >> bit) & 1)
            sleep_us(CLOCK_DELAY_US)
            self.clock.on()
            sleep_us(CLOCK_DELAY_US)
            self.clock.off()

    def _write_transaction(self, is_data, value):
        """Match the vendor demo: CS is strobed for every write byte."""
        self.cs.on()
        self.dc.value(1 if is_data else 0)
        self.cs.off()
        self._write_byte(value)
        self.cs.on()

    def command(self, value):
        self._sdi_output()
        self._write_transaction(False, value)

    def data(self, values):
        if isinstance(values, int):
            values = bytes((values,))
        self._sdi_output()
        for value in values:
            self._write_transaction(True, value)

    def wait_ready(self, label, timeout_ms=BUSY_TIMEOUT_MS):
        started = ticks_ms()
        print("EPD wait", label, "BUSY=", self.busy.value())
        while self.busy.value():
            if ticks_diff(ticks_ms(), started) > timeout_ms:
                raise RuntimeError("BUSY stayed high during " + label)
            sleep_ms(10)
        print("EPD ready", label, "after", ticks_diff(ticks_ms(), started), "ms")

    def reset(self):
        print("EPD hardware reset")
        self.reset_pin.off()
        sleep_ms(10)
        self.reset_pin.on()
        sleep_ms(10)
        self.wait_ready("hardware reset")

    def read_register(self, command, count=1):
        """Read an SSD1683 register through D10, not through D9/MISO.

        The datasheet's 4-wire SPI read procedure requires CS to remain low:
        command with D/C low, then release SDA and clock input bits with D/C
        high.  Data is sampled immediately after each falling SCK edge.
        """
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
        print("SDI read command 0x%02X ->" % command, " ".join("0x%02X" % x for x in values))
        return values

    def init(self):
        self.reset()
        self.command(0x12)
        self.wait_ready("software reset")
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
        self.wait_ready("RAM pointer setup")

    def display(self, buffer):
        print("bit-bang write: 0x24 black/white plane", len(buffer), "bytes")
        self.command(0x24)
        self._write_framebuffer(buffer)
        print("bit-bang write: 0x26 old-image plane", len(buffer), "bytes")
        self.command(0x26)
        self._write_framebuffer(buffer)
        self.command(0x22)
        self.data(0xF7)
        self.command(0x20)
        self.wait_ready("full refresh")
        print("bit-bang display refresh completed")

    def init_fast(self):
        """Load the manufacturer fast-refresh configuration."""
        self.reset()
        self.command(0x12)
        self.wait_ready("fast software reset")
        self.command(0x21)
        self.data(bytes((0x40, 0x00)))
        self.command(0x3C)
        self.data(0x05)
        self.command(0x1A)
        self.data(0x6E)  # Manufacturer's 1.5-second waveform setting.
        self.command(0x22)
        self.data(0x91)  # Load temperature value.
        self.command(0x20)
        self.wait_ready("fast temperature load")
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
        self.wait_ready("fast RAM pointer setup")

    def set_partial_base_map(self, buffer):
        """Prime both RAM planes before local SSD1683 partial updates."""
        print("bit-bang partial base-map: writing both full image planes")
        self.init_fast()
        self.command(0x24)
        self._write_framebuffer(buffer)
        self.command(0x26)
        self._write_framebuffer(buffer)
        self.command(0x22)
        self.data(0xC7)  # Manufacturer EPD_Update_Fast() waveform.
        self.command(0x20)
        self.wait_ready("fast base-map refresh")
        print("bit-bang partial base-map ready")

    def display_partial(self, buffer, x, y, width, height):
        """Write and refresh one byte-aligned rectangle with the fast LUT."""
        if x % 8 or width % 8:
            raise ValueError("partial rectangle X and width must be byte aligned")
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT and
                x + width <= WIDTH and y + height <= HEIGHT):
            raise ValueError("partial rectangle is outside the display")

        source_x_start = x // 8
        source_x_end = source_x_start + width // 8 - 1
        ram_x_start = BYTES_PER_ROW - 1 - source_x_end
        ram_x_end = BYTES_PER_ROW - 1 - source_x_start
        ram_y_start = HEIGHT - 1 - y
        ram_y_end = HEIGHT - (y + height)
        print("bit-bang partial rect x=%d y=%d w=%d h=%d" %
              (x, y, width, height))

        # Exact rectangle setup/waveform from GooDisplay's partial example.
        self.reset()
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
        self.data(0xFF)  # Manufacturer partial-display waveform.
        self.command(0x20)
        self.wait_ready("partial refresh")
        print("bit-bang partial refresh completed")

    def _write_framebuffer(self, buffer):
        # The panel's X scan is opposite a conventional FrameBuffer row.
        for row_start in range(0, BUFFER_BYTES, BYTES_PER_ROW):
            for offset in range(BYTES_PER_ROW - 1, -1, -1):
                self.data(buffer[row_start + offset])


def draw_scaled_text(canvas, label, center_x, center_y, scale=4):
    width = len(label) * 8
    source = bytearray(((width + 7) // 8) * 8)
    glyphs = framebuf.FrameBuffer(source, width, 8, framebuf.MONO_HMSB)
    glyphs.text(label, 0, 0, 1)
    x0 = center_x - width * scale // 2
    y0 = center_y - 4 * scale
    for y in range(8):
        for x in range(width):
            if glyphs.pixel(x, y):
                canvas.fill_rect(x0 + x * scale, y0 + y * scale, scale, scale, 0)


def button_rectangle(index):
    column = index % BUTTON_COLUMNS
    row = index // BUTTON_COLUMNS
    return column * BUTTON_WIDTH, row * BUTTON_HEIGHT, BUTTON_WIDTH, BUTTON_HEIGHT


def make_blank_screen():
    return bytearray(b"\xFF" * BUFFER_BYTES)


def make_button_screen(index):
    """Return a blank framebuffer containing only one original button area."""
    labels = ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX")
    buffer = make_blank_screen()
    canvas = framebuf.FrameBuffer(buffer, WIDTH, HEIGHT, framebuf.MONO_HMSB)
    x, y, width, height = button_rectangle(index)
    border = 10
    canvas.fill_rect(x, y, width, height, 0)
    canvas.fill_rect(x + border, y + border,
                     width - border * 2, height - border * 2, 1)
    draw_scaled_text(canvas, labels[index], x + width // 2, y + height // 2)
    return buffer


def main():
    print("SSD1683 bit-bang / SDI readback test")
    print("D10 is used for both write and read; D9/MISO is ignored.")
    display = SSD1683BitBang()
    print("initial BUSY/D2=", display.busy.value())
    display.init()

    # 0x2F is documented status-bit read.  0x1B reads the temperature
    # register; it is useful evidence that the panel is returning SDI bits.
    status = display.read_register(0x2F)[0]
    temperature = display.read_register(0x1B)[0]
    print("SSD1683 status=0x%02X temperature-register=0x%02X" % (status, temperature))

    blank = make_blank_screen()
    # A clean full refresh establishes the screen state.  The second base-map
    # pass primes both controller image planes for subsequent local updates.
    display.display(blank)
    display.set_partial_base_map(blank)
    print("Partial test: each rectangle shows for 2 s then blanks for 2 s.")
    print("Ctrl-C stops the test and leaves the last image on the panel.")
    while True:
        for index in range(BUTTON_COLUMNS * BUTTON_ROWS):
            rect = button_rectangle(index)
            print("showing button", index + 1)
            display.display_partial(make_button_screen(index), *rect)
            sleep_ms(SHOW_TIME_MS)
            print("blanking button", index + 1)
            display.display_partial(blank, *rect)
            sleep_ms(SHOW_TIME_MS)


try:
    main()
finally:
    Pin(EPD_CS, Pin.OUT, value=1)
    Pin(EPD_SCK, Pin.OUT, value=0)
