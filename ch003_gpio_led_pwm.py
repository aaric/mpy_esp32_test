from machine import Pin, PWM
import time

LED_PIN = 14

led_pwm = PWM(Pin(LED_PIN), freq=5000, duty_u16=0)

# 设置频率为 10Hz
# led_pwm.freq(10)

# 设置占空比，范围是 0 到 65535
# led_pwm.duty_u16(65536 * 3 // 4)  # type: ignore

# 设置亮度，范围是 0 到 1023
# led_pwm.duty(1024 * 3 // 4) # type: ignore


# 示例
while True:
    try:
        # 亮度逐渐增加 (渐亮)
        for duty in range(0, 65536, 1000):
            led_pwm.duty_u16(duty)
            time.sleep_ms(10)

        # 亮度逐渐减小 (渐暗)
        for duty in range(65535, -1, -1000):
            led_pwm.duty_u16(duty)
            time.sleep_ms(10)
    except KeyboardInterrupt:
        print("程序被用户中断，退出循环。")
        break

# 停止 PWM
led_pwm.deinit()

print("Finished.")
