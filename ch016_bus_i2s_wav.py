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

import time
from machine import Pin, I2C, I2S
from es8311 import ES8311, ES8311ClockConfig  # type: ignore # 驱动位于开发板 /lib/es8311.py

WAV_FILE = "test.wav"
VOLUME = 70  # 播放音量 0~100

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


def main():
    # --- 0. 解析 WAV ---
    f, channels, rate, bits, data_size = wav_parse(WAV_FILE)
    byte_rate = rate * channels * bits // 8
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

    # --- 1. 初始化 ES8311 编解码器（I2C 配置：时钟锁相、I2S 格式、DAC、音量）---
    i2c = I2C(0, scl=Pin(PIN_I2C_SCL), sda=Pin(PIN_I2C_SDA), freq=400000)
    devices = i2c.scan()
    print("I2C 设备:", [hex(a) for a in devices])
    if 0x18 not in devices:
        f.close()
        raise OSError("未找到 ES8311(0x18)，请检查 I2C 引脚/接线")

    codec = ES8311(i2c, 0x18)
    codec.init(
        ES8311ClockConfig(mclk_from_mclk_pin=False, sample_frequency=rate),  # 时钟取自 BCLK
        ES8311.ES8311_RESOLUTION_16,  # ADC 分辨率（本实验未用）
        ES8311.ES8311_RESOLUTION_16,  # DAC 分辨率
    )
    codec.microphone_config(False)  # 写 REG14=0x1A：模拟输入 + DAC 到输出路由
    codec.voice_volume_set(VOLUME)
    print("ES8311 初始化完成, 音量 {}".format(VOLUME))

    # --- 2. 初始化 I2S 发送端（ESP32-S3 作主机，ES8311 作从机）---
    audio = I2S(
        0,
        sck=Pin(PIN_I2S_BCLK),
        ws=Pin(PIN_I2S_WS),
        sd=Pin(PIN_I2S_DOUT),
        mode=I2S.TX,  # type: ignore # I2S.TX 是 Final 常量，Pylance 误报
        bits=16,
        format=I2S.STEREO,  # type: ignore
        rate=rate,
        ibuf=65536,  # DMA 环形缓冲，越大抗抖动越强
    )

    # --- 3. 最后再打开功放，避免编解码器上电杂音被放大 ---
    pa = Pin(PIN_PA_EN, Pin.OUT, value=0)
    time.sleep_ms(100)
    pa(1)

    # --- 4. 流式播放：分块读文件 -> 写 I2S（内存占用与文件大小无关）---
    FRAMES = 2048  # 每块帧数
    wbuf = bytearray(FRAMES * 4)          # 写缓冲：16bit x 立体声 = 4 字节/帧
    rbuf = bytearray(FRAMES * 2)          # 单声道文件用（16bit = 2 字节/帧）
    frame_bytes = channels * 2            # 源文件每帧字节数
    stereo = channels == 2
    sent = 0
    t0 = time.ticks_ms()
    print("开始播放...")
    while sent < data_size:
        want = min(FRAMES * frame_bytes, data_size - sent)
        want -= want % frame_bytes  # 按整帧对齐
        if stereo:
            n = f.readinto(wbuf, want)  # readinto(buf, n)：最多读 n 字节
        else:
            n = f.readinto(rbuf, want)
        if not n:
            break
        if stereo:
            audio.write(memoryview(wbuf)[:n])
        else:  # 单声道 -> 立体声：每帧复制到左右两个声道
            mv = memoryview(rbuf)
            wv = memoryview(wbuf)
            for i in range(0, n, 2):
                wv[i * 2] = mv[i]
                wv[i * 2 + 1] = mv[i + 1]
                wv[i * 2 + 2] = mv[i]
                wv[i * 2 + 3] = mv[i + 1]
            audio.write(memoryview(wbuf)[: n * 2])
        sent += n
        print("进度 {}%".format(sent * 100 // data_size), end="\r")
    print()

    # 等待 DMA 缓冲中残余数据播完再关功放
    played = time.ticks_diff(time.ticks_ms(), t0) / 1000
    expect = data_size / byte_rate + 65536 / byte_rate
    if played < expect:
        time.sleep(expect - played)
    pa(0)
    audio.deinit()
    f.close()
    print("播放完成: 实际 {:.1f}s / 理论 {:.1f}s".format(played, data_size / byte_rate))


main()
