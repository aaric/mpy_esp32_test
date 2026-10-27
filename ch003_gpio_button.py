from machine import Pin
from time import sleep_ms

LED_PIN = 14
BTN_PIN = 21

led = Pin(LED_PIN, Pin.OUT)
btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)

print("Button waiting to be triggered...")

while True:
    led.toggle()
    btn_state = btn.value()
    print(btn_state)
    sleep_ms(20)

print("Finished.")
