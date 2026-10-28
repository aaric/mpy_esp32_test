from machine import RTC
import time

rtc = RTC()
rtc.datetime((2026, 10, 28, 2, 15, 30, 0, 0))

while True:
    (year, month, day, weekday, hour, minute, second, _) = rtc.datetime()
    print(f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}")
    time.sleep(1)
