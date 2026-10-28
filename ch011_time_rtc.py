from machine import RTC
import time

rtc = RTC()
rtc.datetime((2026, 10, 28, 2, 15, 30, 0, 0))

while True:
    print(rtc.datetime())
    time.sleep(1)
