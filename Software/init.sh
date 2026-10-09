# Source this file from Software/CanBusSysFirmware, for example:
#   source ../init.sh
#
# ESP-IDF reuses IDF_PYTHON_ENV_PATH when it is set.  Clear it first so a
# shell that previously used the Python 3.12 IDF environment cannot override
# this project's Python 3.14 build environment.
unset IDF_PYTHON_ENV_PATH
unset ESP_PYTHON

# The existing firmware build was configured with Homebrew Python 3.14.
if [ -x /usr/local/opt/python@3.14/bin/python3 ]; then
    export PATH="/usr/local/opt/python@3.14/bin:$PATH"
else
    echo "warning: Homebrew Python 3.14 was not found at /usr/local/opt/python@3.14/bin" >&2
fi

source .build-tools/esp-idf/export.sh
