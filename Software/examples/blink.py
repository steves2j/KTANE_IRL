from machine import Pin
from time import sleep

led = Pin(21, Pin.OUT)  # XIAO ESP32-S3 built-in LED

while True:
    led.value(not led.value())
    sleep(0.5)