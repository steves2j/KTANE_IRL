#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

check_only=false
[[ "${1:-}" == "--check" ]] && check_only=true
[[ $# -le 1 ]] || fail "usage: $0 [--check]"

[[ "$(uname)" == "Darwin" ]] || fail "this setup script is for macOS."
require_command git "Install Xcode Command Line Tools: xcode-select --install"
require_command brew "Install Homebrew from https://brew.sh/."
for tool in cmake ninja python3; do
    require_command "${tool}" "Install prerequisites: brew install cmake ninja python"
done

[[ -d "${MICROPYTHON_DIR}/.git" || -f "${MICROPYTHON_DIR}/.git" ]] || fail "MicroPython submodule is absent; run git submodule update --init --recursive from ${REPO_ROOT}."
[[ -f "${BOARD_DIR}/mpconfigboard.cmake" ]] || fail "project board definition is missing: ${BOARD_DIR}"
[[ -f "${USER_C_MODULES}" ]] || fail "custom-module CMake file is missing: ${USER_C_MODULES}"

if [[ ! -d "${ESP_IDF_DIR}/.git" ]]; then
    if "${check_only}"; then
        fail "ESP-IDF is missing at ${ESP_IDF_DIR}; run scripts/setup-macos.sh."
    fi
    mkdir -p "$(dirname "${ESP_IDF_DIR}")"
    git clone --branch "${IDF_VERSION}" --depth 1 --recursive https://github.com/espressif/esp-idf.git "${ESP_IDF_DIR}"
fi

actual_idf="$(git -C "${ESP_IDF_DIR}" describe --tags --exact-match 2>/dev/null || true)"
[[ "${actual_idf}" == "${IDF_VERSION}" ]] || fail "ESP-IDF must be ${IDF_VERSION}, found ${actual_idf:-unknown} at ${ESP_IDF_DIR}."

# The parent repository records the MicroPython revision. Do not run a broad
# `git submodule update` here: it would replace an intentionally staged pin
# with the old committed pointer before the user has made the pin commit.
git -C "${MICROPYTHON_DIR}" submodule update --init --recursive

if ! "${check_only}"; then
    "${ESP_IDF_DIR}/install.sh" esp32s3
fi
activate_idf
echo "Environment ready: MicroPython v1.28.0, ESP-IDF ${IDF_VERSION}, board ${BOARD}."
