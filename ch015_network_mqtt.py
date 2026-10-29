import network
import time
import ssl
from umqtt.simple import MQTTClient # type: ignore

# 工作模式STA
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.scan()

if not wlan.isconnected():
    # wlan.connect("your-wifi-ssid", "your-password")
    wlan.connect("BlueAzure-DEVICE", "Blue@2025@Azure")

while not wlan.isconnected():
    print("正在连接Wi-Fi...")
    time.sleep(1)

print("Wi-Fi连接成功！")
print("MAC: ", ":".join("{:02x}".format(b) for b in wlan.config("mac")))
print("IP: ", wlan.ipconfig("addr4")[0], "Subnet: ", wlan.ipconfig("addr4")[1], "Gateway: ", wlan.ipconfig("gw4"))


# 连接MQTT服务器
ssl_content = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
# ssl_content.load_cert_chain("client-cert.pem", "client-key.pem")
ssl_content.verify_mode = ssl.CERT_NONE
client_id = "esp32-01"
client = MQTTClient(client_id, "10.0.11.208", 8883, "admin", "Blue2026", ssl=ssl_content)

try:
    # 连接服务器
    client.connect()
    print("EMQX连接成功！")
except Exception as e:
    print("连接EMQX过程中发生错误：", e)
