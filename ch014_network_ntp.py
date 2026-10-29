import network
import time
import ntptime
from machine import RTC

# 工作模式STA
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.scan()

if not wlan.isconnected():
    wlan.connect("your-wifi-ssid", "your-password")

while not wlan.isconnected():
    print("正在连接Wi-Fi...")
    time.sleep(1)

print("Wi-Fi连接成功！")
print("MAC: ", ":".join("{:02x}".format(b) for b in wlan.config("mac")))
print("IP: ", wlan.ipconfig("addr4")[0], "Subnet: ", wlan.ipconfig("addr4")[1], "Gateway: ", wlan.ipconfig("gw4"))


# 同步NTP时间
try:
    # 设置UTC时间
    ntptime.host = "ntp.aliyun.com"
    ntptime.settime()
    print("NTP时间同步成功！")
    print("当前UTC时间：", time.localtime())

    # 获取CST时间（中国标准时间，UTC+8）
    cst_time = time.localtime(time.mktime(time.localtime()) + 8 * 3600)
    print("当前CST时间：", cst_time)

    # 设置RTC时间为CST时间
    rtc = RTC()
    rtc.datetime((cst_time[0], cst_time[1], cst_time[2], cst_time[6], cst_time[3], cst_time[4], cst_time[5], 0))
    print("设置RTC时间成功！")

    # 打印RTC时间
    print("RTC时间：", rtc.datetime())
except Exception as e:
    print("同步NTP时间过程中发生错误：", e)
