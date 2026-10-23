from machine import Pin
from utime import sleep

LED_PIN = 14
BTN_PIN = 21

led = Pin(LED_PIN, Pin.OUT)
btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)

print("Button waiting to be triggered...")

while True:
    led.toggle()
    print(btn.value())
    sleep(1)

print("Finished.")
