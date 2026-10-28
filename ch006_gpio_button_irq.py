from machine import Pin

BTN_PIN = 21

def irq_btn_click(pin):
    print("Button pressed! ", pin)

btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)
btn.irq(irq_btn_click, Pin.IRQ_FALLING)
