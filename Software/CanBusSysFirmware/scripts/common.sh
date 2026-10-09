#!/usr/bin/env bash
# Shared helpers for the repository-local MicroPython build scripts.
set -euo pipefail

project_root() {
    git -C "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" rev-parse --show-toplevel
}

readonly REPO_ROOT="$(project_root)"
readonly FIRMWARE_ROOT="${REPO_ROOT}/Software/CanBusSysFirmware"
readonly MICROPYTHON_DIR="${FIRMWARE_ROOT}/micropython"
readonly ESP_IDF_DIR="${FIRMWARE_ROOT}/.build-tools/esp-idf"
readonly BOARD="SEEED_XIAO_ESP32S3"
readonly BOARD_DIR="${FIRMWARE_ROOT}/boards/${BOARD}"
readonly USER_C_MODULES="${FIRMWARE_ROOT}/usermods/micropython.cmake"
readonly BUILD_DIR="${MICROPYTHON_DIR}/ports/esp32/build-${BOARD}"
readonly IDF_VERSION="v5.5.1"

fail() { echo "error: $*" >&2; exit 1; }

require_command() { command -v "$1" >/dev/null 2>&1 || fail "missing '$1'. ${2:-Install it and retry.}"; }

activate_idf() {
    [[ -f "${ESP_IDF_DIR}/export.sh" ]] || fail "ESP-IDF is missing at ${ESP_IDF_DIR}; run scripts/setup-macos.sh."

    # A command such as scripts/flash.sh starts a fresh Bash process, so it
    # cannot rely on a caller having sourced init.sh.  Always discard a stale
    # IDF virtualenv selection and put the interpreter used to configure this
    # project's build (Homebrew Python 3.14) first on PATH.
    unset IDF_PYTHON_ENV_PATH ESP_PYTHON
    if [[ -x /usr/local/opt/python@3.14/bin/python3 ]]; then
        export PATH="/usr/local/opt/python@3.14/bin:${PATH}"
    else
        fail "Homebrew Python 3.14 is required at /usr/local/opt/python@3.14/bin/python3."
    fi
    # shellcheck disable=SC1091
    source "${ESP_IDF_DIR}/export.sh" >/dev/null
    require_command idf.py "ESP-IDF environment activation failed; run scripts/setup-macos.sh."
}

resolve_serial_port() {
    if [[ -n "${CANBUS_SERIAL_PORT:-}" ]]; then
        [[ -e "${CANBUS_SERIAL_PORT}" ]] || fail "CANBUS_SERIAL_PORT does not exist: ${CANBUS_SERIAL_PORT}"
        printf '%s\n' "${CANBUS_SERIAL_PORT}"
        return
    fi
    local ports=()
    shopt -s nullglob
    ports=(/dev/cu.usbmodem* /dev/cu.SLAB_USBtoUART* /dev/cu.wchusbserial*)
    shopt -u nullglob
    (( ${#ports[@]} == 1 )) || fail "select a serial port with CANBUS_SERIAL_PORT=/dev/cu.usbmodem... (found: ${ports[*]:-none})"
    printf '%s\n' "${ports[0]}"
}
