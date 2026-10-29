from machine import Pin
from time import sleep

LED_PIN = 14

led = Pin(LED_PIN, Pin.OUT)

print("LED starts flashing...")

while True:
    try:
        led.toggle()
        sleep(1)
    except KeyboardInterrupt:
        print("程序被用户中断，退出循环。")
        break

led.off()

print("Finished.")
