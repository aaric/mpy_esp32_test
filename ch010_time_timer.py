from machine import Timer

time0 = Timer(0)
time0.init(period=1000, mode=Timer.ONE_SHOT, callback=lambda t:print("one shot"))

time1 = Timer(1)
time1.init(period=1000, mode=Timer.PERIODIC, callback=lambda t:print("periodic"))
