import network
import time
import requests

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

# 请求网络数据
try:
    response = requests.get("https://acs.m.taobao.com/gw/mtop.common.getTimestamp")
    if response.status_code == 200:
        print("响应内容：", response.json())
    else:
        print("请求失败，状态码：", response.status_code)
except Exception as e:
    print("请求过程中发生错误：", e)
