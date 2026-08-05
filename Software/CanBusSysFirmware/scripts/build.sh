#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

"${SCRIPT_DIR}/setup-macos.sh" --check
activate_idf

make -C "${MICROPYTHON_DIR}/mpy-cross" clean
make -C "${MICROPYTHON_DIR}/mpy-cross" CFLAGS_EXTRA="-fomit-frame-pointer"
make -C "${MICROPYTHON_DIR}/ports/esp32" submodules
make -C "${MICROPYTHON_DIR}/ports/esp32" \
    BOARD="${BOARD}" \
    BOARD_DIR="${BOARD_DIR}" \
    USER_C_MODULES="${USER_C_MODULES}"

[[ -f "${BUILD_DIR}/firmware.bin" ]] || fail "firmware.bin was not produced."
[[ -f "${BUILD_DIR}/micropython.elf" ]] || fail "micropython.elf was not produced."
[[ -f "${BUILD_DIR}/micropython.map" ]] || fail "micropython.map was not produced."
echo "Firmware built: ${BUILD_DIR}/firmware.bin"
