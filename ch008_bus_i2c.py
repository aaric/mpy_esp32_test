from machine import Pin, I2C

i2c = I2C(scl=Pin(9), sda=Pin(8), freq=400000)
ret = i2c.scan()
print(ret)
