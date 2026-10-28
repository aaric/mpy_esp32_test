from machine import Pin
from time import sleep_ms

LED_PIN = 14
BTN_PIN = 21

led = Pin(LED_PIN, Pin.OUT)
btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)

print("Button waiting to be triggered...")

while True:
    # LED 状态取反
    led.toggle()

    # 读取按键状态
    btn_state = btn.value()
    print(btn_state)

    # 延时 100 毫秒防抖
    sleep_ms(100)

print("Finished.")
