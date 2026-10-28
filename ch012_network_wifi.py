import network
import time

# 工作模式AP
# ap = network.WLAN(network.AP_IF)
# # ap.config(ssid="ESP32-S3-WIFI")
# ap.config(ssid="ESP32-S3-WIFI", authmode=network.AUTH_WPA_WPA2_PSK, password="12345678") # type: ignore
# ap.config(max_clients=3)
# ap.active(True)
#
# print("AP模式已启动，等待客户端连接...")


# 工作模式STA
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.scan()

if not wlan.isconnected():
    wlan.connect("your-wifi-ssid", "password")
    print(wlan.config("mac"))
    print(wlan.ipconfig("addr4"))

while not wlan.isconnected():
    print("正在连接Wi-Fi...")
    time.sleep(1)

print("Wi-Fi连接成功！")
