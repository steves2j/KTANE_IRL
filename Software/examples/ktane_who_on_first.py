"""Bring-up test for the KTANE Who's on First 4.2-inch touch e-paper module.

Panel: GooDisplay S-GDEY042T81-FP Touch, 400x300 monochrome, SSD1683.
Touch: FT6336 at I2C address 0x38.

XIAO ESP32-S3 wiring (D-pin labels):
  e-paper: DC D3, SS D7, SCK D8, MISO D9, MOSI D10, BUSY D2, RESET D1
  touch:   SDA D4, SCL D5, RESET D0

This is only a display/touch hardware test. It uses the firmware-built
``epaper`` usermod for SSD1683 transfers, and Python only for the retained
framebuffer and FT6336 touch handling. It is not the Who's on First game.
"""

from machine import I2C, Pin
from time import sleep_ms, ticks_diff, ticks_ms
import framebuf
import epaper
import tft
import neopixel
import urandom
try:
    import mcp2518
except ImportError:
    mcp2518 = None


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
TOUCH_RESET = 1  # D0

# ST7789P3 status display shares SPI3 SCK/D8, MOSI/D10 and DC/D3 with the
# e-paper, but uses an independent CS, reset and active-low backlight.
TFT_CS = 43         # D6
TFT_RESET = 1       # D0
TFT_BACKLIGHT = 13  # D14; low enables backlight
WS2812_PIN = 38     # D11 / GPIO38
WS2812_COUNT = 4

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
POSITION_NAMES = ("top-left", "top-right", "middle-left", "middle-right", "bottom-left", "bottom-right")


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
    scale = 2 if len(label) > 6 else (3 if len(label) > 4 else 4)
    draw_centered_text(canvas, label, x + width // 2, y + height // 2, scale)


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


def native_epaper_init():
    """Initialise the compiled C/C++ SSD1683 usermod on SPI3."""
    log("EPD native init: SPI3, CS/D7 DC/D3 RESET/D1 BUSY/D2 SCK/D8 MOSI/D10")
    epaper.init(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY, EPD_SCK, EPD_MOSI)
    log("EPD native status:", epaper.status())


def native_tft_init():
    """Initialise the compiled ST7789P3 usermod, then show its title."""
    log("TFT native init: CS/D6 RESET/D0 BL/D14; SPI3 SCK/D8 MOSI/D10 DC/D3")
    tft.init(TFT_CS, EPD_DC, TFT_RESET, TFT_BACKLIGHT, EPD_SCK, EPD_MOSI)
    log("TFT native status:", tft.status())
    tft.text("Who's on first")


def make_button_screen(labels):
    """Return the six dynamic Who's on First button labels."""
    buffer = bytearray(b"\xFF" * BUFFER_BYTES)  # EPD: 1 is white, 0 is black.
    canvas = framebuf.FrameBuffer(buffer, WIDTH, HEIGHT, framebuf.MONO_HMSB)
    for index, label in enumerate(labels):
        column = index % 2
        row = index // 2
        draw_button(canvas, column * BUTTON_WIDTH, row * BUTTON_HEIGHT,
                    BUTTON_WIDTH, BUTTON_HEIGHT, label)
    return buffer


def make_solved_screen():
    """Six happy faces make the solved, touch-locked state unambiguous."""
    buffer = bytearray(b"\xFF" * BUFFER_BYTES)
    canvas = framebuf.FrameBuffer(buffer, WIDTH, HEIGHT, framebuf.MONO_HMSB)
    for index in range(6):
        column, row = index % 2, index // 2
        x, y = column * BUTTON_WIDTH, row * BUTTON_HEIGHT
        canvas.fill_rect(x, y, BUTTON_WIDTH, BUTTON_HEIGHT, 0)
        canvas.fill_rect(x + 10, y + 10, BUTTON_WIDTH - 20, BUTTON_HEIGHT - 20, 1)
        draw_smiley(canvas, x + BUTTON_WIDTH // 2, y + BUTTON_HEIGHT // 2)
    return buffer


def draw_smiley(canvas, center_x, center_y):
    """Draw a bold monochrome happy face without relying on font glyphs."""
    radius = 34
    inner = (radius - 2) * (radius - 2)
    outer = radius * radius
    for y in range(-radius, radius + 1):
        for x in range(-radius, radius + 1):
            distance = x * x + y * y
            if inner <= distance <= outer:
                canvas.pixel(center_x + x, center_y + y, 0)
    # Eyes.
    for eye_x in (-13, 13):
        for y in range(-15, -6):
            for x in range(eye_x - 4, eye_x + 5):
                if (x - eye_x) * (x - eye_x) + (y + 11) * (y + 11) <= 16:
                    canvas.pixel(center_x + x, center_y + y, 0)
    # U-shaped smile: endpoints rise while the centre sits lower.
    for x in range(-20, 21):
        y = 19 - (x * x) // 25
        canvas.fill_rect(center_x + x - 1, center_y + y - 1, 3, 3, 0)


# Canonical manual Step 1: prompt -> button position (TL, TR, ML, MR, BL, BR).
STEP_1 = {
    "UR": 0, "FIRST": 1, "OKAY": 1, "C": 1,
    "YES": 2, "NOTHING": 2, "THEY ARE": 2, "LED": 2,
    "BLANK": 3, "READ": 3, "RED": 3, "YOU": 3, "YOUR": 3,
    "YOU'RE": 3, "THEIR": 3,
    "EMPTY": 4, "REED": 4, "LEED": 4, "THEY'RE": 4,
    "DISPLAY": 5, "SAYS": 5, "NO": 5, "LEAD": 5, "HOLD ON": 5,
    "YOU ARE": 5, "THERE": 5, "SEE": 5, "CEE": 5,
}

# Canonical manual Step 2: reference label -> priority order.
PRIORITY = {
 "READY":"YES OKAY WHAT MIDDLE LEFT PRESS RIGHT BLANK READY NO FIRST UHHH NOTHING WAIT",
 "FIRST":"LEFT OKAY YES MIDDLE NO RIGHT NOTHING UHHH WAIT READY BLANK WHAT PRESS FIRST",
 "NO":"BLANK UHHH WAIT FIRST WHAT READY RIGHT YES NOTHING LEFT PRESS OKAY NO",
 "BLANK":"WAIT RIGHT OKAY MIDDLE BLANK", "NOTHING":"UHHH RIGHT OKAY MIDDLE YES BLANK NO PRESS LEFT WHAT WAIT FIRST NOTHING",
 "YES":"OKAY RIGHT UHHH MIDDLE FIRST WHAT PRESS READY NOTHING YES", "WHAT":"UHHH WHAT",
 "UHHH":"READY NOTHING LEFT WHAT OKAY YES RIGHT NO PRESS BLANK UHHH", "LEFT":"RIGHT LEFT",
 "RIGHT":"YES NOTHING READY PRESS NO WAIT WHAT RIGHT", "MIDDLE":"BLANK READY OKAY WHAT NOTHING PRESS NO WAIT LEFT MIDDLE RIGHT FIRST UHHH YES",
 "OKAY":"MIDDLE NO FIRST YES UHHH NOTHING WAIT OKAY LEFT READY BLANK PRESS WHAT RIGHT",
 "WAIT":"UHHH NO BLANK OKAY YES LEFT FIRST PRESS WHAT WAIT NOTHING READY RIGHT MIDDLE",
 "PRESS":"RIGHT MIDDLE YES READY PRESS OKAY NOTHING UHHH BLANK LEFT FIRST WHAT NO WAIT",
 "YOU":"SURE YOU ARE YOUR YOU'RE NEXT UH HUH UR HOLD WHAT? YOU UH UH LIKE DONE U",
 "YOU ARE":"YOUR NEXT LIKE UH HUH WHAT? DONE UH UH HOLD YOU U YOU'RE SURE UR YOU ARE",
 "YOUR":"UH UH YOU ARE UH HUH YOUR NEXT UR SURE U YOU'RE YOU WHAT? HOLD LIKE DONE",
 "YOU'RE":"YOU YOU'RE UR NEXT UH UH YOU ARE U YOUR WHAT? UH HUH SURE DONE LIKE HOLD",
 "UR":"DONE U UR UH HUH WHAT? SURE YOUR HOLD YOU'RE LIKE NEXT UH UH YOU ARE YOU",
 "U":"UH HUH SURE NEXT WHAT? YOU'RE UR UH UH DONE U YOU LIKE HOLD YOU ARE YOUR",
 "UH HUH":"UH HUH YOUR YOU ARE YOU DONE HOLD UH UH NEXT SURE LIKE YOU'RE UR U WHAT?",
 "UH UH":"UR U YOU ARE YOU'RE NEXT UH UH DONE YOU UH HUH LIKE YOUR SURE HOLD WHAT?",
 "WHAT?":"YOU HOLD YOU'RE YOUR U DONE UH UH LIKE YOU ARE UH HUH UR NEXT WHAT? SURE",
 "DONE":"SURE UH HUH NEXT WHAT? YOUR UR YOU'RE HOLD LIKE YOU U YOU ARE UH UH DONE",
 "NEXT":"WHAT? UH HUH UH UH YOUR HOLD SURE NEXT LIKE DONE YOU ARE UR YOU'RE U YOU",
 "HOLD":"YOU ARE U DONE UH UH YOU UR SURE WHAT? YOU'RE NEXT HOLD UH HUH YOUR LIKE",
 "SURE":"YOU ARE DONE LIKE YOU'RE YOU HOLD UH HUH UR SURE U WHAT? NEXT YOUR UH UH",
 "LIKE":"YOU'RE NEXT U UR HOLD DONE UH UH WHAT? UH HUH YOU LIKE SURE YOU ARE YOUR",
}
def parse_priority(raw):
    """Keep the manual's multi-word labels intact in compact source tables."""
    tokens = raw.split()
    result = []
    index = 0
    while index < len(tokens):
        if index + 1 < len(tokens) and tokens[index] == "YOU" and tokens[index + 1] == "ARE":
            result.append("YOU ARE")
            index += 2
        elif index + 1 < len(tokens) and tokens[index] == "UH" and tokens[index + 1] in ("HUH", "UH"):
            result.append("UH " + tokens[index + 1])
            index += 2
        else:
            result.append(tokens[index])
            index += 1
    return result


for _key in PRIORITY:
    PRIORITY[_key] = parse_priority(PRIORITY[_key])

BUTTON_WORDS = tuple(PRIORITY)
PROMPTS = tuple(STEP_1)
# Green is preserved under the observed red/blue channel reversal.  Use it for
# both completed-stage indicators and the final solved-status indication.
PIXEL_OFF, PIXEL_STAGE, PIXEL_PASS = (0, 0, 0), (0, 24, 0), (0, 24, 0)
STATUS = {"passed": False, "failed": False, "in_progress": True, "strikes": 0, "stage": 1}
pixels = None


def shuffled_words():
    words = list(BUTTON_WORDS)
    for i in range(len(words) - 1, 0, -1):
        j = urandom.getrandbits(16) % (i + 1)
        words[i], words[j] = words[j], words[i]
    return words


def set_indicators():
    """Pixel 4, then 3, then 2 records completed stages; pixel 1 is status."""
    for i in range(WS2812_COUNT):
        pixels[i] = PIXEL_OFF
    completed = STATUS["stage"] - 1
    for stage in range(completed):
        pixels[3 - stage] = PIXEL_STAGE
    # Pixel 1 is reserved solely for the green solved indication.
    pixels[0] = PIXEL_PASS if STATUS["passed"] else PIXEL_OFF
    pixels.write()


def make_stage():
    prompt = PROMPTS[urandom.getrandbits(16) % len(PROMPTS)]
    labels = shuffled_words()[:6]
    reference_index = STEP_1[prompt]
    reference = labels[reference_index]
    target = next(word for word in PRIORITY[reference] if word in labels)
    return prompt, labels, target, reference


def render_stage(prompt, labels):
    """Update TFT first, then make e-paper's full/base refresh the final bus use."""
    buffer = make_button_screen(labels)
    log("stage", STATUS["stage"], "prompt=", prompt, "labels=", labels)
    epaper.detach()
    try:
        tft.text(prompt)
    except OSError as error:
        log("TFT error", error, "continuing with e-paper")
    epaper.attach()
    return refresh_epaper(buffer)


def refresh_epaper(buffer):
    """Perform one full refresh and establish its RAM as the partial baseline.

    ``epaper.full`` already writes the same image to both SSD1683 image planes
    (0x24/current and 0x26/previous), then performs the visible full update.
    Calling ``base_map`` immediately afterwards repeats that exact full update,
    hence the previous double flash at every stage.
    """
    for attempt in range(1, 4):
        try:
            native_epaper_init()
            epaper.full(buffer)
            return buffer
        except OSError as error:
            log("EPD recovery attempt", attempt, "failed:", error)
            sleep_ms(200)
    log("EPD unavailable after recovery; retaining game state for next reset")
    return buffer


def partial_or_recover(buffer, rect):
    try:
        epaper.partial(buffer, *rect)
        return True
    except OSError as error:
        log("EPD partial error", error, "; redrawing current stage")
        refresh_epaper(buffer)
        return False


def poll_can_reset():
    """RESET on any CAN identifier resets a solved module for the next bomb."""
    if mcp2518 is None:
        return False
    try:
        while True:
            frame = mcp2518.recv()
            if frame is None:
                return False
            identifier, payload = frame
            if bytes(payload).upper().startswith(b"RESET"):
                log("CAN RESET received on id=0x%X" % identifier)
                return True
    except OSError as error:
        log("CAN receive error", error)
        return False


def main():
    log("Who's on First e-paper/touch bring-up (native SSD1683 usermod)")
    log("EPD native SPI: DC D3, SS D7, SCK D8, MOSI D10, BUSY D2, RESET D1")
    log("Touch I2C: SDA D4, SCL D5, RESET D0")

    touch = FT6336()
    touch.init(reset=True)
    if mcp2518 is not None:
        try:
            log("MCP2518 reset listener:", mcp2518.start(), mcp2518.status())
        except OSError as error:
            log("MCP2518 unavailable; CAN RESET disabled:", error)
    # Create the shared SPI3 host, but defer the differential baseline until
    # after TFT setup.  This SSD1683 requires the baseline to be the last
    # display-bus operation before its first partial waveform.
    log("initialising native SSD1683 before TFT setup...")
    native_epaper_init()
    epaper.detach()
    native_tft_init()
    epaper.attach()
    log("reinitialising native SSD1683 and performing final full refresh...")
    native_epaper_init()
    global pixels
    pixels = neopixel.NeoPixel(Pin(WS2812_PIN, Pin.OUT), WS2812_COUNT, bpp=3)
    prompt, labels, target, reference = make_stage()
    buffer = render_stage(prompt, labels)
    set_indicators()
    reference_index = STEP_1[prompt]
    log("RULE: display=%s -> read %s button (%s) -> priority=%s -> press %s" %
        (prompt, POSITION_NAMES[reference_index], reference,
         ", ".join(PRIORITY[reference]), target))

    previous = None
    active_buttons = {}  # FT6336 touch id -> momentarily inverted button index
    while True:
        if STATUS["passed"]:
            # Solved modules ignore physical input until the master explicitly
            # starts the next bomb with a CAN payload beginning RESET.
            if poll_can_reset():
                STATUS.update({"passed": False, "failed": False, "in_progress": True,
                               "strikes": 0, "stage": 1})
                prompt, labels, target, reference = make_stage()
                buffer = render_stage(prompt, labels)
                set_indicators()
                log("module reset; new stage target=", target)
            sleep_ms(40)
            continue
        try:
            touches = touch.read_touches()
        except OSError as error:
            log("touch I2C error", error, "; retrying")
            sleep_ms(100)
            continue
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
                    pressed = labels[button_index]
                    if pressed == target:
                        log("correct:", pressed)
                        STATUS["stage"] += 1
                        if STATUS["stage"] == 4:
                            STATUS["passed"] = True
                            STATUS["in_progress"] = False
                            set_indicators()
                            epaper.detach()
                            tft.text("SOLVED")
                            epaper.attach()
                            buffer = refresh_epaper(make_solved_screen())
                            log("MODULE SOLVED", STATUS)
                        else:
                            set_indicators()
                            prompt, labels, target, reference = make_stage()
                            buffer = render_stage(prompt, labels)
                            reference_index = STEP_1[prompt]
                            log("RULE: display=%s -> read %s button (%s) -> priority=%s -> press %s" %
                                (prompt, POSITION_NAMES[reference_index], reference,
                                 ", ".join(PRIORITY[reference]), target))
                    else:
                        STATUS["strikes"] += 1
                        log("STRIKE pressed=", pressed, "expected=", target, "count=", STATUS["strikes"])
                        set_indicators()
                        buffer = render_stage(prompt, labels)
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
            log("EPD native partial x=%d y=%d w=%d h=%d" % rect)
            partial_or_recover(buffer, rect)

        # Some FT6336 firmware revisions report release as zero touches rather
        # than a final point with event=up. Evaluate that press identically.
        for touch_id in tuple(active_buttons):
            if touch_id not in seen_ids:
                button_index = active_buttons.pop(touch_id)
                pressed = labels[button_index]
                if pressed == target:
                    log("correct:", pressed)
                    STATUS["stage"] += 1
                    if STATUS["stage"] == 4:
                        STATUS["passed"] = True
                        STATUS["in_progress"] = False
                        set_indicators()
                        epaper.detach()
                        tft.text("SOLVED")
                        epaper.attach()
                        buffer = refresh_epaper(make_solved_screen())
                        log("MODULE SOLVED", STATUS)
                    else:
                        set_indicators()
                        prompt, labels, target, reference = make_stage()
                        buffer = render_stage(prompt, labels)
                        reference_index = STEP_1[prompt]
                        log("RULE: display=%s -> read %s button (%s) -> priority=%s -> press %s" %
                            (prompt, POSITION_NAMES[reference_index], reference,
                             ", ".join(PRIORITY[reference]), target))
                else:
                    STATUS["strikes"] += 1
                    log("STRIKE pressed=", pressed, "expected=", target, "count=", STATUS["strikes"])
                    set_indicators()
                    buffer = render_stage(prompt, labels)
        sleep_ms(40)


main()
