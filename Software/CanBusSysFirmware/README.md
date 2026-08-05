# CAN Bus System Firmware

Custom MicroPython firmware for the Seeed Studio XIAO ESP32S3. Project code
lives outside the `micropython` submodule so an upstream update is explicit and
does not mix local firmware work with vendor source.

## Requirements

On macOS install Xcode Command Line Tools and Homebrew, then:

```bash
xcode-select --install
brew install git cmake ninja python
```

The project pins MicroPython to `v1.28.0` and uses its documented ESP-IDF
recommendation, `v5.5.1`. `scripts/setup-macos.sh` verifies prerequisites,
initialises submodules, and creates/installs ESP-IDF in `.build-tools/` when
needed. That directory and all build outputs are ignored by Git. The XIAO
ESP32S3 board definition is project-owned because that upstream board was added
after MicroPython v1.28.0.

## Setup and build

Commands may be run from any directory:

```bash
cd /path/to/CanBusModule
Software/CanBusSysFirmware/scripts/setup-macos.sh
Software/CanBusSysFirmware/scripts/build.sh
```

The build uses `BOARD=SEEED_XIAO_ESP32S3`, the project board directory, and an
absolute `USER_C_MODULES` path. It rebuilds `mpy-cross` using
`CFLAGS_EXTRA=-fomit-frame-pointer`, the workaround for Apple Clang's frame
pointer interference error. Outputs are in
`micropython/ports/esp32/build-SEEED_XIAO_ESP32S3/`, including `firmware.bin`,
`micropython.elf`, and `micropython.map`.

To clean generated files, run the **CAN firmware: clean** VS Code task or:

```bash
rm -rf Software/CanBusSysFirmware/micropython/mpy-cross/build \
  Software/CanBusSysFirmware/micropython/ports/esp32/build-SEEED_XIAO_ESP32S3
```

## Device operations

Put the XIAO in bootloader mode by holding **BOOT**, briefly pressing **RESET**,
then releasing **BOOT**. Find the port with `ls /dev/cu.*`; it normally looks
like `/dev/cu.usbmodem*`. Set it explicitly when more than one device exists:

```bash
CANBUS_SERIAL_PORT=/dev/cu.usbmodemXXXX Software/CanBusSysFirmware/scripts/erase.sh
CANBUS_SERIAL_PORT=/dev/cu.usbmodemXXXX Software/CanBusSysFirmware/scripts/flash.sh
CANBUS_SERIAL_PORT=/dev/cu.usbmodemXXXX Software/CanBusSysFirmware/scripts/monitor.sh
```

The scripts automatically select a single matching device if one is present.
They do not flash unless `flash.sh` is invoked.

At the REPL, validate the compiled built-in module:

```python
import nativecan
print(nativecan.hello())
# nativecan module loaded
```

## VS Code

Open the repository root in VS Code and run **Tasks: Run Build Task**. The
flash, erase, and monitor tasks ask for a port; leave it blank for safe
single-device auto-detection or set `canbus.serialPort` in workspace settings.
The C/C++ extension reads the compile database after the first build.

## Updating deliberately

Do not advance the submodule incidentally. Review upstream release notes and
ESP-IDF requirements, then checkout a chosen tag in `micropython`, update its
submodules, rebuild from clean, and commit the parent repository's changed
submodule pointer together with any board compatibility changes.

## Troubleshooting

- `Interference usage of base pointer/frame pointer`: rerun `build.sh`; it
  always rebuilds `mpy-cross` with `-fomit-frame-pointer`.
- ESP-IDF version error: `setup-macos.sh` requires `v5.5.1` for this pin. Move
  an incompatible `.build-tools/esp-idf` aside and rerun setup, or checkout the
  required tag there.
- No serial port: reconnect the board, enter bootloader mode, and inspect
  `ls /dev/cu.*` before setting `CANBUS_SERIAL_PORT`.
