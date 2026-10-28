from machine import Pin, SPI

spi = SPI(1, baudrate=1000000, sck=Pin(41), mosi=Pin(42), miso=Pin(40))
print(spi)
