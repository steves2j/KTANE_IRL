#define MICROPY_HW_BOARD_NAME "Seeed XIAO ESP32S3"
#define MICROPY_HW_MCU_NAME "ESP32-S3"

// Native USB CDC is the default REPL. UART0 remains available to applications.
#define MICROPY_HW_I2C0_SCL (6)
#define MICROPY_HW_I2C0_SDA (5)
#define MICROPY_HW_SPI1_MOSI (9)
#define MICROPY_HW_SPI1_MISO (8)
#define MICROPY_HW_SPI1_SCK (7)
