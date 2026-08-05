# This board was added upstream after MicroPython v1.28.0.  Keep the small
# definition here so this project can remain pinned to that release.
set(IDF_TARGET esp32s3)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.ble
    boards/sdkconfig.240mhz
    boards/sdkconfig.spiram_oct
)
