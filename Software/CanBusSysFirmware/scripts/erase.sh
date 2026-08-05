#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

"${SCRIPT_DIR}/setup-macos.sh" --check
activate_idf
port="$(resolve_serial_port)"
make -C "${MICROPYTHON_DIR}/ports/esp32" BOARD="${BOARD}" BOARD_DIR="${BOARD_DIR}" PORT="${port}" erase
