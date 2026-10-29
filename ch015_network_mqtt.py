import network
import time
import ssl
from umqtt.robust import MQTTClient # type: ignore

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


# 连接MQTT服务器
ssl_content = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
# ssl_content.load_cert_chain("client-cert.pem", "client-key.pem")
ssl_content.verify_mode = ssl.CERT_NONE
client_id = "esp32-01"
client = MQTTClient(client_id, "127.0.0.1", 8883, "admin", "public", ssl=ssl_content)

my_sub_topic = f"esp32/topic/{client_id}"
my_pub_topic = f"esp32/topic/host"

def on_message(topic, msg):
    print(f"收到消息[{topic.decode()}]：", msg.decode())
    client.publish(my_pub_topic, f"{client_id} Received: {msg.decode()}")

client.set_callback(on_message)

try:
    client.connect()
    print("MQTT服务器连接成功！")

    client.subscribe(my_sub_topic)
    print("已订阅主题：", my_sub_topic)

    my_msg = f"Hello from {client_id}!"
    client.publish(my_pub_topic, my_msg)
except Exception as e:
    print("连接MQTT过程中发生错误：", e)


# 进入主循环，处理业务逻辑
while True:
    try:
        # 检查MQTT新消息
        client.check_msg()
        time.sleep(1)
    except Exception as e:
        print("主循环发生错误：", e)
