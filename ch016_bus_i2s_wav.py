# ch016 I2S 总线 —— 播放 WAV 文件（ESP32-S3-BOX-3B 开发板）
#
# 音频链路：I2S 外设(GPIO17=BCLK, GPIO45=WS, GPIO15=DATA) -> ES8311 编解码器 -> NS4150 功放(GPIO46 使能) -> 喇叭
# 引脚来源：ESP32-S3-BOX-3B.md（原理图矢量提取）
#
# 与裸 I2S 功放(如 MAX98357)的两个关键区别：
#   1. ES8311 挂在 I2C 总线上(SCL=GPIO18, SDA=GPIO8, 7位地址 0x18)，播放前必须先做寄存器初始化，
#      否则完全无声。驱动使用开发板 /lib/es8311.py（源自 M5Stack CoreS3，同为 ES8311+NS4150 方案）。
#   2. MicroPython v1.29 的 machine.I2S 不支持 mck 参数（无法输出 MCLK），
#      因此初始化 ES8311 时选择“由 BCLK 提供时钟”(mclk_from_mclk_pin=False)。
#      此时 BCLK 频率 = 采样率 x 32（16bit 立体声），必须命中 lib/es8311.py coeff_div 时钟表：
#      支持 22050/32000/44100/48000/64000/88200/96000 Hz，不支持 8k/11k/12k/16k/24k（低采样率需 MCLK 方案）。
#
# WavPlayer 用法：
#   player = WavPlayer(volume=70)
#   player.play("test.wav")     # 阻塞式播放，返回实际播放秒数
#   player.volume = 30          # 实时调音量(0~100)
#   player.stop()               # 中途停止(可在定时器/按键中断里调用)

import time
import gc
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


def wav_parse(path):
    """解析 WAV 文件头，返回 (文件对象, 声道数, 采样率, 位深, 数据长度)

    标准 WAV 是 RIFF 块结构：文件头之后由若干块组成，
    必须逐块查找 fmt / data（test.wav 的 fmt 和 data 之间就夹了一个 LIST 块）。
    """
    f = open(path, "rb")
    hdr = f.read(12)
    if hdr[:4] != b"RIFF" or hdr[8:12] != b"WAVE":
        f.close()
        raise ValueError("不是 WAV 文件: " + path)
    channels = rate = bits = 0
    while True:
        head = f.read(8)
        if len(head) < 8:
            f.close()
            raise ValueError("未找到 data 块")
        cid, size = head[:4], int.from_bytes(head[4:], "little")
        if cid == b"fmt ":
            d = f.read(size)
            if int.from_bytes(d[:2], "little") != 1:
                f.close()
                raise ValueError("仅支持 PCM 编码（不支持压缩格式）")
            channels = int.from_bytes(d[2:4], "little")
            rate = int.from_bytes(d[4:8], "little")
            bits = int.from_bytes(d[14:16], "little")
            if size % 2:  # 块长度为奇数时有 1 字节对齐填充
                f.seek(1, 1)
        elif cid == b"data":
            return f, channels, rate, bits, size
        else:  # 跳过 LIST / fact 等附加块
            f.seek(size + (size & 1), 1)


class WavPlayer:
    """ESP32-S3-BOX-3B 上的 I2S WAV 播放器（ES8311 编解码器 + NS4150 功放）

    - play() 为阻塞式流式播放，内存占用固定（约 12KB），与文件大小无关
    - 自动按 WAV 文件采样率重配 ES8311 时钟与 I2S 外设
    - volume 属性可实时调节；stop() 可从定时器/按键中断中调用来中途停止
    """

    def __init__(self, volume=70, quiet=False, bclk=PIN_I2S_BCLK, ws=PIN_I2S_WS,
                 dout=PIN_I2S_DOUT, pa_en=PIN_PA_EN, scl=PIN_I2C_SCL, sda=PIN_I2C_SDA):
        """初始化 I2C 总线、ES8311 驱动实例和功放引脚（此时不出声）

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

    def play(self, path):
        """阻塞式播放一个 WAV 文件，返回实际播放秒数（被 stop() 打断时返回已播时长）"""
        f, channels, rate, bits, data_size = wav_parse(path)
        byte_rate = rate * channels * bits // 8
        if not self._quiet:
            print("WAV: {}Hz {}bit {}声道, 时长 {:.1f}s, {}KB".format(
                rate, bits, channels, data_size / byte_rate, data_size // 1024))
        if bits != 16:
            f.close()
            raise ValueError("仅支持 16bit PCM")
        if channels not in (1, 2):
            f.close()
            raise ValueError("仅支持单声道/立体声")
        if rate not in SUPPORTED_RATES:
            f.close()
            raise ValueError("采样率 {}Hz 不在 ES8311 BCLK 时钟表内（支持的采样率见文件头注释）".format(rate))

        self._config_codec(rate)
        self._config_i2s(rate)
        audio = self._audio
        assert audio is not None  # 上面的 _config_i2s() 已完成创建

        # 最后再打开功放，避免编解码器上电杂音被放大
        time.sleep_ms(100)
        self._pa(1)

        # 流式播放：分块读文件 -> 写 I2S
        FRAMES = 2048  # 每块帧数
        wbuf = bytearray(FRAMES * 4)   # 写缓冲：16bit x 立体声 = 4 字节/帧
        rbuf = bytearray(FRAMES * 2)   # 单声道文件用（16bit = 2 字节/帧）
        frame_bytes = channels * 2     # 源文件每帧字节数
        stereo = channels == 2
        sent = 0
        self._stop = False
        t0 = time.ticks_ms()
        if not self._quiet:
            print("开始播放...")
        while sent < data_size and not self._stop:
            want = min(FRAMES * frame_bytes, data_size - sent)
            want -= want % frame_bytes  # 按整帧对齐
            n = f.readinto(wbuf if stereo else rbuf, want)
            if not n:
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
        self._pa(0)
        f.close()
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
                ibuf=65536,  # DMA 环形缓冲，越大抗抖动越强
            )
            self._i2s_rate = rate

    def deinit(self):
        """释放 I2S 外设（I2C/ES8311 可继续留给其他代码使用）"""
        if self._audio is not None:
            self._audio.deinit()
            self._audio = None
            self._i2s_rate = 0


# --- 使用示例 ---
player = WavPlayer(volume=70)
player.play("test.wav")

# 音量实时调节示例（第二遍用 30% 音量播放）
# player.volume = 30
# player.play("test.wav")
# player.deinit()
