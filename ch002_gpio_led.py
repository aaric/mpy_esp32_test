from machine import Pin
from utime import sleep

LED_PIN = 14

led = Pin(LED_PIN, Pin.OUT)

print("LED starts flashing...")

while True:
    try:
        led.toggle()
        sleep(1)
    except KeyboardInterrupt:
        break

led.off()
print("Finished.")
