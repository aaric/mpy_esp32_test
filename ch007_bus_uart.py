from machine import UART
import time

# 创建UART对象，通道编号，通常使用 1 或 2（0 通常保留给 REPL）
uart1 = UART(1, baudrate=115200, tx=17, rx=18)


def iqr_uart_receive(uart):
    if uart.any():
        data = uart.read()
        print("Received:", data)

uart1.irq(handler=iqr_uart_receive, trigger=UART.IRQ_RXIDLE, hard=False) # type: ignore

while True:
    # 发送数据
    uart1.write("hello, world\n")

    # 检查是否有数据可读
    # while uart1.any():
        # 读取数据
        # data = uart1.read()
        # print("Received:", data)

    # 延时 1s
    time.sleep(1)
