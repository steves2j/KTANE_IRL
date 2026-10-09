"""Physical implementation of the KTANE Simon Says module.

Hardware:
  Buttons: D2 red, D1 green, D0 blue, D7 yellow (active-low with pull-ups).
  Indicator LEDs: D5 red, D4 green, D6 blue, D3 yellow (anode to GPIO).
  One RGB WS2812: D11 / GPIO38.

The serial number will eventually arrive from the CAN master.  Until that
protocol exists, receive_serial_emulated() generates a compatible six-character
serial: O/Y are excluded and its final character is a decimal digit.
"""

from machine import Pin
from time import sleep_ms, ticks_add, ticks_diff, ticks_ms
import neopixel
import os
import sys
import uselect

BUTTON_PINS = (3, 2, 1, 44)  # D2, D1, D0, D7
BUTTON_COLOURS = ("red", "green", "blue", "yellow")

# Anode-connected indicator LEDs: output HIGH illuminates the LED.
LED_PINS = {
    "red": 6,     # D5
    "green": 5,   # D4
    "blue": 43,   # D6
    "yellow": 4,  # D3
}
WS2812_PIN = 38  # XIAO D11; do not confuse this with GPIO11 / CAN MOSI.

FLASH_ON_MS = 400
FLASH_GAP_MS = 180
# The opening ready signal repeats more slowly until the first button press.
OPENING_FLASH_ON_MS = 750
OPENING_FLASH_GAP_MS = 750
BUTTON_POLL_MS = 15
# Keep this short enough for deliberate rapid Simon inputs while filtering
# switch bounce after a release.
DEBOUNCE_MS = 60

# Use modest values to limit current.  Standard WS2812 tuples are RGB.
RGB = {
    "red": (24, 0, 0),
    "green": (0, 24, 0),
    "blue": (0, 0, 24),
    "yellow": (24, 24, 0),
    "white": (18, 18, 18),
    None: (0, 0, 0),
}

# This is the state that the future CAN protocol will expose to the master.
# Keep it independent of the display so it remains meaningful after a solve.
MODULE_STATUS = {
    "passed": False,
    "failed": False,
    "in_progress": False,
    "strikes": 0,
}

# Table keys are the flashed colour; table values are the physical colour that
# must be pressed.  Rows are selected by min(strikes, 2).
MAPPINGS_WITH_VOWEL = (
    {"red": "blue", "blue": "red", "green": "yellow", "yellow": "green"},
    {"red": "yellow", "blue": "green", "green": "blue", "yellow": "red"},
    {"red": "green", "blue": "red", "green": "yellow", "yellow": "blue"},
)
MAPPINGS_WITHOUT_VOWEL = (
    {"red": "blue", "blue": "yellow", "green": "green", "yellow": "red"},
    {"red": "red", "blue": "blue", "green": "yellow", "yellow": "green"},
    {"red": "yellow", "blue": "green", "green": "blue", "yellow": "red"},
)

leds = {colour: Pin(pin, Pin.OUT, value=0) for colour, pin in LED_PINS.items()}
buttons = [Pin(pin, Pin.IN, Pin.PULL_UP) for pin in BUTTON_PINS]
pixel = neopixel.NeoPixel(Pin(WS2812_PIN, Pin.OUT), 1, bpp=3)
console_poll = uselect.poll()
console_poll.register(sys.stdin, uselect.POLLIN)


class DemoRequested(Exception):
    pass


def check_console():
    """Consume console commands without stopping the button/game loop."""
    while console_poll.poll(0):
        command = sys.stdin.readline().strip().lower()
        if not command:
            continue
        print("console command:", command)
        if command == "demo":
            print("demo mode requested")
            raise DemoRequested()
        print("unknown command; supported command: demo")


def sleep_with_console(duration_ms):
    """Sleep while still accepting a line such as 'demo' from the console."""
    deadline = ticks_add(ticks_ms(), duration_ms)
    while ticks_diff(deadline, ticks_ms()) > 0:
        check_console()
        sleep_ms(min(BUTTON_POLL_MS, ticks_diff(deadline, ticks_ms())))


def module_status():
    """Return a copy of the state for a future CAN status response."""
    return dict(MODULE_STATUS)


def send_can_action(action):
    """Temporary CAN transport stub; replace with the master CAN protocol."""
    print("CAN STUB action=", action, "status=", module_status())


def handle_can_status_request():
    """Future CAN receive handler should call this for a status request."""
    send_can_action("status")


def fail_module():
    """Future master/game logic may call this to mark the module failed."""
    MODULE_STATUS["passed"] = False
    MODULE_STATUS["failed"] = True
    MODULE_STATUS["in_progress"] = False
    print("MODULE FAILED", module_status())
    send_can_action("failed")


def random_serial():
    """Match the serial format used by epaper_ee05_message.py."""
    letters = "ABCDEFGHJKLMNPQRSTUVWXZ"  # No O or Y.
    digits = "0123456789"
    alphabet = digits + letters
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


def receive_serial_emulated():
    """Temporary replacement for the future CAN serial-number receive path."""
    serial = random_serial()
    print("CAN serial receive is not implemented; emulating serial:", serial)
    return serial


def serial_has_vowel(serial):
    return any(character in "AEIOU" for character in serial)


def set_display(colour):
    """Show one physical colour through its indicator LED and RGB WS2812."""
    for led_colour, led in leds.items():
        led.value(1 if led_colour == colour else 0)
    pixel[0] = RGB[colour]
    pixel.write()


def flash(colour):
    print("flash", colour)
    set_display(colour)
    sleep_ms(FLASH_ON_MS)
    set_display(None)
    sleep_ms(FLASH_GAP_MS)


def flash_sequence(sequence):
    print("showing sequence:", " ".join(sequence))
    sleep_ms(400)
    for colour in sequence:
        flash(colour)


def poll_button_press(previous_values, last_press_ms):
    """Return a debounced press if one occurred, otherwise None."""
    check_console()
    now = ticks_ms()
    for index, button in enumerate(buttons):
        value = button.value()
        if previous_values[index] and not value and ticks_diff(now, last_press_ms) >= DEBOUNCE_MS:
            return BUTTON_COLOURS[index], now
        previous_values[index] = value
    return None


def flash_until_button(colour):
    """Continuously flash the opening colour until a player presses a button."""
    print("waiting for first input; repeatedly flashing", colour)
    wait_for_buttons_released()
    previous_values = [button.value() for button in buttons]
    last_press_ms = ticks_add(ticks_ms(), -DEBOUNCE_MS)

    while True:
        print("flash", colour)
        set_display(colour)
        deadline = ticks_add(ticks_ms(), OPENING_FLASH_ON_MS)
        while ticks_diff(deadline, ticks_ms()) > 0:
            press = poll_button_press(previous_values, last_press_ms)
            if press is not None:
                set_display(None)
                return press
            sleep_ms(BUTTON_POLL_MS)

        set_display(None)
        deadline = ticks_add(ticks_ms(), OPENING_FLASH_GAP_MS)
        while ticks_diff(deadline, ticks_ms()) > 0:
            press = poll_button_press(previous_values, last_press_ms)
            if press is not None:
                return press
            sleep_ms(BUTTON_POLL_MS)


def flash_opening_for(colour, duration_ms):
    """Flash the normal opening signal for a fixed duration (used by demo)."""
    print("demo countdown: flashing opening colour", colour)
    end_time = ticks_add(ticks_ms(), duration_ms)
    while ticks_diff(end_time, ticks_ms()) > 0:
        set_display(colour)
        sleep_with_console(min(OPENING_FLASH_ON_MS, ticks_diff(end_time, ticks_ms())))
        set_display(None)
        remaining = ticks_diff(end_time, ticks_ms())
        if remaining > 0:
            sleep_with_console(min(OPENING_FLASH_GAP_MS, remaining))


def strike_feedback():
    print("STRIKE", "count", MODULE_STATUS["strikes"])
    send_can_action("strike")
    for _ in range(3):
        for led in leds.values():
            led.value(1)
        pixel[0] = RGB["white"]
        pixel.write()
        sleep_ms(120)
        set_display(None)
        sleep_ms(120)


def solve_feedback():
    print("MODULE SOLVED")
    for _ in range(5):
        for led in leds.values():
            led.value(1)
        pixel[0] = RGB["white"]
        pixel.write()
        sleep_ms(150)
        set_display(None)
        sleep_ms(120)
    # A solved module has no discrete indicator lit; the RGB is the pass lamp.
    for led in leds.values():
        led.value(0)
    pixel[0] = RGB["green"]
    pixel.write()


def mapping_for(has_vowel, strikes):
    tables = MAPPINGS_WITH_VOWEL if has_vowel else MAPPINGS_WITHOUT_VOWEL
    return tables[min(strikes, 2)]


def wait_for_buttons_released():
    """Avoid treating a button held during the playback as an answer."""
    while any(not button.value() for button in buttons):
        sleep_ms(BUTTON_POLL_MS)


def wait_for_button_press(previous_values, last_press_ms):
    """Return (colour, timestamp) for one debounced active-low button press."""
    while True:
        press = poll_button_press(previous_values, last_press_ms)
        if press is not None:
            return press
        sleep_ms(BUTTON_POLL_MS)


def run_game():
    MODULE_STATUS["passed"] = False
    MODULE_STATUS["failed"] = False
    MODULE_STATUS["in_progress"] = True
    MODULE_STATUS["strikes"] = 0
    serial = receive_serial_emulated()
    has_vowel = serial_has_vowel(serial)
    total_stages = 3 + (os.urandom(1)[0] % 3)  # KTANE Simon Says uses 3–5 stages.
    sequence = [BUTTON_COLOURS[os.urandom(1)[0] % len(BUTTON_COLOURS)]]

    print("Simon Says started")
    print("serial:", serial, "contains vowel:", has_vowel, "stages:", total_stages)
    print("button order D2,D1,D0,D7 =", ",".join(BUTTON_COLOURS))

    stage = 1
    while stage <= total_stages:
        strikes = MODULE_STATUS["strikes"]
        mapping = mapping_for(has_vowel, strikes)
        expected = [mapping[colour] for colour in sequence]
        print("stage", stage, "strikes", strikes, "mapping", mapping)
        print("expected input:", " ".join(expected))

        correct = True
        position = 1
        if stage == 1 and strikes == 0:
            # The first colour is the game's ready signal: repeat it until the
            # player responds, then use that press as the first sequence input.
            received, last_press_ms = flash_until_button(sequence[0])
            wanted = expected[0]
            print("input", position, "received", received, "expected", wanted)
            # Show the selected colour only while its physical button is held.
            set_display(received)
            wait_for_buttons_released()
            set_display(None)
            if received != wanted:
                MODULE_STATUS["strikes"] += 1
                strike_feedback()
                print("replay stage", stage, "with mapping for", min(MODULE_STATUS["strikes"], 2), "strike(s)")
                correct = False
            else:
                position = 2
        else:
            set_display(None)
            flash_sequence(sequence)
            wait_for_buttons_released()
            previous_values = [button.value() for button in buttons]
            last_press_ms = ticks_add(ticks_ms(), -DEBOUNCE_MS)

        if correct:
            for position, wanted in enumerate(expected[position - 1:], position):
                received, last_press_ms = wait_for_button_press(previous_values, last_press_ms)
                print("input", position, "received", received, "expected", wanted)
                set_display(received)
                wait_for_buttons_released()
                set_display(None)
                previous_values = [button.value() for button in buttons]
                if received != wanted:
                    MODULE_STATUS["strikes"] += 1
                    strike_feedback()
                    print("replay stage", stage, "with mapping for", min(MODULE_STATUS["strikes"], 2), "strike(s)")
                    correct = False
                    break

        if not correct:
            continue

        print("stage", stage, "complete")
        stage += 1
        if stage <= total_stages:
            next_colour = BUTTON_COLOURS[os.urandom(1)[0] % len(BUTTON_COLOURS)]
            sequence.append(next_colour)
            print("next sequence colour appended:", next_colour)

    MODULE_STATUS["passed"] = True
    MODULE_STATUS["in_progress"] = False
    print("pass status", module_status())
    send_can_action("passed")
    solve_feedback()
    print("Simon Says is disarmed; press reset to play a new game")
    while True:
        sleep_with_console(1000)


def reset_module_status():
    MODULE_STATUS["passed"] = False
    MODULE_STATUS["failed"] = False
    MODULE_STATUS["in_progress"] = True
    MODULE_STATUS["strikes"] = 0


def demo_press(colour, description):
    """Show a simulated button press without reading the physical buttons."""
    print("demo", description, "press", colour)
    set_display(colour)
    sleep_with_console(150)
    set_display(None)


def demo_wrong_colour(expected_colour):
    """Choose a valid button colour that is guaranteed to be incorrect."""
    choices = [colour for colour in BUTTON_COLOURS if colour != expected_colour]
    return choices[os.urandom(1)[0] % len(choices)]


def demonstrate_correct_sequence(expected):
    for position, colour in enumerate(expected, 1):
        demo_press(colour, "correct input %d" % position)


def run_demo():
    """Continuously demonstrate two strikes followed by a three-stage solve."""
    print("DEMO MODE: stages 1 and 2 strike once; stage 3 is solved cleanly")
    while True:
        reset_module_status()
        serial = receive_serial_emulated()
        has_vowel = serial_has_vowel(serial)
        sequence = [BUTTON_COLOURS[os.urandom(1)[0] % len(BUTTON_COLOURS)]]
        print("demo starting in 5 seconds; serial:", serial, "vowel:", has_vowel)
        flash_opening_for(sequence[0], 5000)

        for stage in range(1, 4):
            mapping = mapping_for(has_vowel, MODULE_STATUS["strikes"])
            expected = [mapping[colour] for colour in sequence]
            print("demo stage", stage, "sequence:", " ".join(sequence), "expected:", " ".join(expected))
            set_display(None)
            flash_sequence(sequence)
            print("demo pause: 2 seconds after sequence")
            sleep_with_console(2000)

            if stage < 3:
                # Demonstrate a strike at a random point in this stage, then
                # replay under the strike-adjusted Simon Says mapping.
                fail_position = os.urandom(1)[0] % len(expected)
                print("demo stage", stage, "will strike at input", fail_position + 1)
                for position in range(fail_position):
                    demo_press(expected[position], "correct input %d" % (position + 1))
                sleep_with_console(250 + (os.urandom(1)[0] % 1001))
                demo_press(demo_wrong_colour(expected[fail_position]), "intentional incorrect input %d" % (fail_position + 1))
                MODULE_STATUS["strikes"] += 1
                strike_feedback()

                mapping = mapping_for(has_vowel, MODULE_STATUS["strikes"])
                expected = [mapping[colour] for colour in sequence]
                print("demo replay stage", stage, "expected:", " ".join(expected))
                flash_sequence(sequence)
                print("demo pause: 2 seconds after replay")
                sleep_with_console(2000)

            demonstrate_correct_sequence(expected)
            print("demo stage", stage, "complete")
            if stage < 3:
                sequence.append(BUTTON_COLOURS[os.urandom(1)[0] % len(BUTTON_COLOURS)])

        MODULE_STATUS["passed"] = True
        MODULE_STATUS["in_progress"] = False
        print("demo pass status", module_status())
        send_can_action("passed")
        solve_feedback()
        print("demo solved; next new demonstration starts in 5 seconds")
        sleep_with_console(5000)


def main():
    while True:
        try:
            run_game()
        except DemoRequested:
            run_demo()


try:
    set_display(None)
    main()
finally:
    # On Ctrl-C or an exception, leave all outputs safely off.
    set_display(None)
