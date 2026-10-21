import sys
import machine
import time

# 获取并打印 CPU 频率 (单位转换为 MHz)
freq = machine.freq() / 1000000
print(f"Device Info: {sys.platform}\nCPU Freq: {freq} MHz")

count = 0

while True:
    # 打印当前计数值
    print(f"Hello World! {count}")
    count += 1
    # 延时 1 秒
    time.sleep(1)
