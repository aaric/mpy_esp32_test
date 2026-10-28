from machine import Pin

LED_PIN = 14
BTN_PIN = 21
led = Pin(LED_PIN, Pin.OUT)
btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)

# 示例1
# def irq_btn_click(pin):
    # print("irq object: ", pin)


# 示例2
flag = 0

def irq_btn_click(pin):
    print("irq object: ", pin)
    global flag
    led.value(flag)
    flag = not flag

btn.irq(irq_btn_click, Pin.IRQ_FALLING)
