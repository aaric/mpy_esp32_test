# ch017 I2S 总线 —— HTTP 网络流式播放 WAV（ESP32-S3-BOX-3B 开发板）
#
# 音频链路：Wi-Fi -> HTTP 流式下载 -> I2S(GPIO17=BCLK, GPIO45=WS, GPIO15=DATA)
#           -> ES8311 编解码器 -> NS4150 功放(GPIO46 使能) -> 喇叭
# 引脚来源：ESP32-S3-BOX-3B.md（原理图矢量提取）
#
# 与 ch016（本地文件播放）的区别：
#   1. play() 参数从本地路径改为网络音频 URL（如 http://10.0.11.208:3005/.../hello-xy.wav）；
#   2. WAV 头解析改为“顺序流式”：RIFF 块结构逐块读取，非 data 块直接读走丢弃（网络流不能 seek）；
#   3. requests.get(url, stream=True) 拿到流式 BodyStream，边下载边写 I2S，
#      内存占用固定（约 12KB），与音频文件大小无关。
#
# 固件实测 API（MicroPython v1.29）：
#   - requests.get(url, stream=True, timeout=10) 返回 Response，resp.raw 为 BodyStream
#   - BodyStream.readinto(memoryview切片) 会阻塞读满整个切片才返回，EOF 返回 0
#
# ES8311 时钟方案（与 ch016 相同）：
#   machine.I2S 无 mck 参数 -> ES8311 用 BCLK 作时钟源，BCLK = 采样率 x 32（16bit 立体声），
#   必须命中 lib/es8311.py coeff_div 时钟表：支持 22050/32000/44100/48000/64000/88200/96000 Hz。
#
# WavNetworkPlayer 用法：
#   player = WavNetworkPlayer(volume=70)
#   player.play("http://10.0.11.208:3005/ai-test/resources/audios/hello-xy.wav")
#   player.volume = 30        # 实时调音量(0~100)
#   player.stop()             # 中途停止(可在定时器/按键中断里调用)

import gc
import time
import network
import requests
from machine import Pin, I2C, I2S
from es8311 import ES8311, ES8311ClockConfig  # type: ignore # 驱动位于开发板 /lib/es8311.py

# --- 引脚定义（ESP32-S3-BOX-3B）---
PIN_I2C_SCL = 18   # I2C 时钟（ES8311/ES7210/IMU/触摸共用总线）
PIN_I2C_SDA = 8    # I2C 数据
PIN_I2S_BCLK = 17  # I2S 位时钟
PIN_I2S_WS = 45    # I2S 帧时钟(左右声道)
PIN_I2S_DOUT = 15  # I2S 数据输出（接 ES8311 DAC 输入）
PIN_PA_EN = 46     # NS4150 功放使能（高电平打开）

# BCLK 作 ES8311 时钟源时，时钟表支持的采样率
SUPPORTED_RATES = (22050, 32000, 44100, 48000, 64000, 88200, 96000)


def wav_parse_stream(stream):
    """从顺序流（requests 的 BodyStream）解析 WAV 头

    返回 (声道数, 采样率, 位深, 数据长度)，返回时流正好停在 data 块数据起始处。
    与本地文件不同：网络流不能 seek，跳过 LIST/fact 等附加块改为“读走丢弃”。
    依赖 BodyStream 的 readinto“读满即返回”语义（MicroPython v1.29 实测）。
    """
    def read_exact(n):
        buf = bytearray(n)
        got = stream.readinto(memoryview(buf))
        if got != n:
            raise ValueError("WAV 头不完整")
        return buf

    hdr = read_exact(12)
    if hdr[:4] != b"RIFF" or hdr[8:12] != b"WAVE":
        raise ValueError("不是 WAV 音频流")
    channels = rate = bits = 0
    while True:
        head = read_exact(8)
        cid, size = head[:4], int.from_bytes(head[4:], "little")
        if cid == b"fmt ":
            d = read_exact(size)
            if int.from_bytes(d[:2], "little") != 1:
                raise ValueError("仅支持 PCM 编码（不支持压缩格式）")
            channels = int.from_bytes(d[2:4], "little")
            rate = int.from_bytes(d[4:8], "little")
            bits = int.from_bytes(d[14:16], "little")
            if size % 2:  # 奇数长度块的 1 字节对齐填充
                read_exact(1)
        elif cid == b"data":
            data_size = 0 if size == 0xFFFFFFFF else size  # 部分流式服务不填长度，留 0 给调用方兜底
            return channels, rate, bits, data_size
        else:  # 读走丢弃 LIST / fact 等附加块（同样含奇数对齐填充）
            to_skip = size + (size & 1)
            while to_skip > 0:
                read_exact(min(to_skip, 512))
                to_skip -= 512


class WavNetworkPlayer:
    """ESP32-S3-BOX-3B 上的 HTTP 网络流式 WAV 播放器（ES8311 + NS4150）

    - play(url) 阻塞式边下边播，内存占用固定（约 12KB），与音频文件大小无关
    - 自动按音频流采样率重配 ES8311 时钟与 I2S 外设
    - volume 属性可实时调节；stop() 可从定时器/按键中断中调用来中途停止
    """

    def __init__(self, volume=70, quiet=False, bclk=PIN_I2S_BCLK, ws=PIN_I2S_WS,
                 dout=PIN_I2S_DOUT, pa_en=PIN_PA_EN, scl=PIN_I2C_SCL, sda=PIN_I2C_SDA):
        """初始化 I2C 总线、ES8311 驱动实例和功放引脚（此时不出声，也不需要网络）

        volume: 初始音量 0~100
        quiet:  True 时不打印进度信息
        其余参数为引脚号，默认值即 ESP32-S3-BOX-3B 原理图引脚
        """
        self._quiet = quiet
        self._volume = max(0, min(100, volume))
        self._stop = False

        # I2C 总线 + ES8311（只建驱动实例，寄存器初始化推迟到 play()，那时才知道采样率）
        self._i2c = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=400000)
        devices = self._i2c.scan()
        if 0x18 not in devices:
            raise OSError("未找到 ES8311(0x18)，请检查 I2C 引脚/接线, 扫描到: {}".format(
                [hex(a) for a in devices]))
        self._codec = ES8311(self._i2c, 0x18)
        self._codec_rate = 0  # ES8311 已按该采样率初始化

        self._i2s_pins = (bclk, ws, dout)
        self._audio = None
        self._i2s_rate = 0

        self._pa = Pin(pa_en, Pin.OUT, value=0)  # 功放默认关闭

    # ---------- 音量 ----------

    def _set_volume(self, volume):
        """调节音量"""
        if volume < 0:
            volume = 0
        elif volume > 100:
            volume = 100
        self._volume = volume
        if self._codec_rate:  # 编解码器就绪才写寄存器
            self._codec.voice_volume_set(volume)

    @property
    def volume(self):
        """音量 0~100，可读可写，播放中修改立即生效"""
        return self._volume

    @volume.setter
    def volume(self, value):
        self._set_volume(value)

    # ---------- 播放控制 ----------

    def stop(self):
        """请求停止当前播放（可在播放过程中、甚至定时器/按键中断里调用）"""
        self._stop = True

    def play(self, url):
        """阻塞式流式播放网络 WAV 音频，返回实际播放秒数（被 stop() 打断时返回已播时长）"""
        resp = requests.get(url, stream=True, timeout=10)
        if resp.status_code != 200:
            code = resp.status_code
            resp.close()
            raise OSError("HTTP 状态码 {}: {}".format(code, url))
        try:
            channels, rate, bits, data_size = wav_parse_stream(resp.raw)
            # data 块没填长度时，用 HTTP Content-Length 兜底（已消费的头部长度约为
            # 剩余值 = Content-Length - 已读字节数，这里简化为整个 Content-Length 不可靠，直接报错更清晰）
            if data_size == 0:
                raise ValueError("WAV 流未提供 data 块长度")
            byte_rate = rate * channels * bits // 8
            if not self._quiet:
                print("WAV: {}Hz {}bit {}声道, 时长 {:.1f}s".format(
                    rate, bits, channels, data_size / byte_rate))
            if bits != 16:
                raise ValueError("仅支持 16bit PCM")
            if channels not in (1, 2):
                raise ValueError("仅支持单声道/立体声")
            if rate not in SUPPORTED_RATES:
                raise ValueError("采样率 {}Hz 不在 ES8311 BCLK 时钟表内（支持的采样率见文件头注释）".format(rate))

            self._config_codec(rate)
            self._config_i2s(rate)
            audio = self._audio
            assert audio is not None  # 上面的 _config_i2s() 已完成创建

            # 最后再打开功放，避免编解码器上电杂音被放大
            time.sleep_ms(100)
            self._pa(1)

            # 边下边播：分块读网络流 -> 写 I2S（DMA 缓冲 64KB，可吸收约 0.3s 网络抖动）
            FRAMES = 2048  # 每块帧数
            wbuf = bytearray(FRAMES * 4)   # 写缓冲：16bit x 立体声 = 4 字节/帧
            rbuf = bytearray(FRAMES * 2)   # 单声道音频用（16bit = 2 字节/帧）
            frame_bytes = channels * 2     # 源每帧字节数
            stereo = channels == 2
            sent = 0
            self._stop = False
            t0 = time.ticks_ms()
            if not self._quiet:
                print("开始播放...")
            while sent < data_size and not self._stop:
                want = min(FRAMES * frame_bytes, data_size - sent)
                want -= want % frame_bytes  # 按整帧对齐
                n = resp.raw.readinto(memoryview(wbuf if stereo else rbuf)[:want])
                if not n:  # 服务器提前断开
                    break
                if stereo:
                    audio_out = memoryview(wbuf)[:n]
                else:  # 单声道 -> 立体声：每帧复制到左右两个声道
                    src, dst = memoryview(rbuf), memoryview(wbuf)
                    for i in range(0, n, 2):
                        dst[i * 2] = src[i]
                        dst[i * 2 + 1] = src[i + 1]
                        dst[i * 2 + 2] = src[i]
                        dst[i * 2 + 3] = src[i + 1]
                    audio_out = memoryview(wbuf)[: n * 2]
                audio.write(audio_out)
                sent += n
                if not self._quiet:
                    print("进度 {}%".format(sent * 100 // data_size), end="\r")

            # 等待 DMA 缓冲中残余数据播完再关功放（被 stop() 打断则只等一小段）
            played = time.ticks_diff(time.ticks_ms(), t0) / 1000
            remain = data_size / byte_rate + 65536 / byte_rate - played
            if remain > 0:
                time.sleep(min(remain, 0.2) if self._stop else remain)
        finally:
            self._pa(0)
            resp.close()  # 无论正常结束/停止/异常，都关闭连接释放内存
        if not self._quiet:
            print("\n播放完成: 实际 {:.1f}s / 理论 {:.1f}s".format(played, data_size / byte_rate))
        return played

    # ---------- 内部方法 ----------

    def _config_codec(self, rate):
        """按采样率(重)初始化 ES8311：时钟锁相、I2S 格式、DAC 路由、音量"""
        if self._codec_rate != rate:
            self._codec.init(
                ES8311ClockConfig(mclk_from_mclk_pin=False, sample_frequency=rate),  # 时钟取自 BCLK
                ES8311.ES8311_RESOLUTION_16,  # ADC 分辨率（本实验未用）
                ES8311.ES8311_RESOLUTION_16,  # DAC 分辨率
            )
            self._codec.microphone_config(False)  # 写 REG14=0x1A：模拟输入 + DAC 到输出路由
            self._codec_rate = rate
        self._codec.voice_volume_set(self._volume)

    def _config_i2s(self, rate):
        """按采样率(重)创建 I2S 发送端（ESP32-S3 作主机，ES8311 作从机）"""
        if self._i2s_rate != rate:
            if self._audio is not None:
                self._audio.deinit()
            gc.collect()  # 先回收内存碎片，再分配 64KB DMA 缓冲，避免 ENOMEM
            bclk, ws, dout = self._i2s_pins
            self._audio = I2S(
                0,
                sck=Pin(bclk),
                ws=Pin(ws),
                sd=Pin(dout),
                mode=I2S.TX,  # type: ignore # I2S.TX 是 Final 常量，Pylance 误报
                bits=16,
                format=I2S.STEREO,  # type: ignore
                rate=rate,
                ibuf=65536,  # DMA 环形缓冲，越大抗网络抖动越强
            )
            self._i2s_rate = rate

    def deinit(self):
        """释放 I2S 外设（I2C/ES8311 可继续留给其他代码使用）"""
        if self._audio is not None:
            self._audio.deinit()
            self._audio = None
            self._i2s_rate = 0


class NetworkHelper:
    """网络连接助手类"""

    @staticmethod
    def wifi_connect(
        ssid: str,
        password: str
    ) -> dict:
        """连接到Wi-Fi网络"""
        # 工作模式STA
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        wlan.scan()

        if not wlan.isconnected():
            # wlan.connect("your-wifi-ssid", "your-password")
            wlan.connect(ssid, password)

        while not wlan.isconnected():
            print("正在连接Wi-Fi...")
            time.sleep(1)

        # 连接成功后，打印网络信息
        print("Wi-Fi连接成功！")

        # 返回网络信息（MicroPython v1.29 的 ipconfig 仅支持 addr4/addr6，
        # 网关需用传统 ifconfig() 获取，它返回 (ip, 子网掩码, 网关, DNS)）
        ip, subnet = wlan.ipconfig("addr4")
        return {
            "mac": ":".join("{:02x}".format(b) for b in wlan.config("mac")),
            "ip": ip,
            "subnet": subnet,
            "gateway": wlan.ifconfig()[2]
        }


# 连接到Wi-Fi网络
network_info = NetworkHelper.wifi_connect("your-wifi-ssid", "your-password")
print(network_info)

# 播放网络音频
player = WavNetworkPlayer(volume=70)
player.play("http://localhost:8080/static/test.wav")
