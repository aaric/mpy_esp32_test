from machine import Pin
import neopixel
import time

LED_PIN = 48

np = neopixel.NeoPixel(Pin(LED_PIN), 1)

while True:
    # 红色亮
    np[0] = (255, 0, 0)
    np.write()
    time.sleep(1)

    # 绿色亮
    np[0] = (0, 255, 0)
    np.write()
    time.sleep(1)

    # 蓝色亮
    np[0] = (0, 0, 255)
    np.write()
    time.sleep(1)

    # 关闭LED
    np[0] = (0, 0, 0)
    np.write()
    time.sleep(1)
