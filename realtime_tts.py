# realtime_tts.py - 实时语音合成模块 - 性能优化版 (修复播放问题)
import websocket
import datetime
import hashlib
import base64
import hmac
import json
import ssl
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import _thread as thread
import threading
from queue import Queue
import time
import pyaudio
from concurrent.futures import ThreadPoolExecutor
import gc


class RealtimeTTS:
    """实时语音合成模块 - 性能优化版"""

    def __init__(self, app_id, api_key, api_secret, output_device_index=None):
        # 保存API密钥和设备选择
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.output_device_index = output_device_index
        self.is_playing = False
        self.play_queue = Queue()
        self.current_ws = None  # 当前的WebSocket连接
        self.lock = threading.Lock()  # 用于线程同步的锁
        self.playback_callback = None  # 播放完成回调函数

        # 创建线程池
        self.thread_pool = ThreadPoolExecutor(max_workers=3)

        # 音频播放设置
        self.p = pyaudio.PyAudio()
        self.stream = None

        # 默认参数
        self.default_voice = "x4_gaolengnanshen_talk"  # 中文音色
        self.default_speed = 50
        self.default_volume = 60

        # 垃圾回收控制
        self.last_gc_time = time.time()

        # 支持的音色列表
        self.available_voices = {
            # 中文音色
            "x4_gaolengnanshen_talk": "萧文 [普通话]",
            "x4_panting": "潘婷 [普通话]",
            # 英语音色
            "x4_enus_gavin_assist": "Gavin [英语]",
            "x4_enus_luna_assist": "Luna [英语]",
            # 日语音色
            "qianhui": "千惠 [日语]",
            "x4_jajp_zhongcun_assist": "中村樱 [日语]",
            # 其他语种
            "x2_IdId_Kris": "Kris [印尼语]",
            "x2_HiIn_Mohita": "Mohita [印地语]",
            "x2_ViVn_ThuHien": "ThuHien [越南语]",
            "yingying": "莹莹 [泰语]",
            "x2_spes_aurora": "Aurora [西班牙语]",
            "maria": "玛利亚 [葡萄牙语]",
            "x2_ItIt_Anna": "Anna [意大利语]",
        }

        # 定期进行垃圾回收
        self._start_gc_timer()

    def _start_gc_timer(self):
        """启动垃圾回收定时器"""

        def gc_task():
            while True:
                time.sleep(60)  # 每60秒
                gc.collect()

        gc_thread = threading.Thread(target=gc_task, daemon=True)
        gc_thread.start()

    def create_url(self):
        """生成鉴权URL"""
        url = 'wss://tts-api.xfyun.cn/v2/tts'

        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        signature_origin = "host: " + "ws-api.xfyun.cn" + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v2/tts " + "HTTP/1.1"

        signature_sha = hmac.new(
            self.api_secret.encode('utf-8'),
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature_sha = base64.b64encode(signature_sha).decode('utf-8')

        authorization_origin = f'api_key="{self.api_key}", algorithm="hmac-sha256", ' \
                               f'headers="host date request-line", signature="{signature_sha}"'
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')

        v = {
            "authorization": authorization,
            "date": date,
            "host": "ws-api.xfyun.cn"
        }
        return url + '?' + urlencode(v)

    def speak(self, text, voice=None, speed=None, volume=None, callback=None):
        """直接播放语音（非阻塞），支持播放完成回调"""
        with self.lock:
            # 保存回调函数
            self.playback_callback = callback

            # 判断是否需要等待当前播放完成
            if self.is_playing:
                self.play_queue.put((text, voice, speed, volume, callback))
                return

            self._play_text(text, voice, speed, volume)

    def stop_speaking(self):
        """停止当前播放"""
        print("播放停止中...")

        with self.lock:
            try:
                # 1. 安全地关闭WebSocket连接
                ws_to_close = self.current_ws
                if ws_to_close:
                    self.current_ws = None  # 先清空引用，避免回调中再次访问

                    # 移除回调函数，防止触发额外的回调
                    ws_to_close.on_message = lambda ws, msg: None
                    ws_to_close.on_error = lambda ws, err: None
                    ws_to_close.on_close = lambda ws, code, msg: None

                    # 在单独的线程中关闭，避免阻塞主线程
                    def safe_close():
                        try:
                            ws_to_close.close()
                            print("WebSocket已安全关闭")
                        except Exception as e:
                            print(f"关闭WebSocket出错 (忽略): {e}")

                    close_thread = threading.Thread(target=safe_close)
                    close_thread.daemon = True
                    close_thread.start()

                # 2. 安全地关闭音频流
                stream_to_close = self.stream
                if stream_to_close:
                    self.stream = None  # 先清空引用，避免回调中再次访问

                    # 尝试停止并关闭流
                    try:
                        stream_to_close.stop_stream()
                        stream_to_close.close()
                        print("音频流已安全关闭")
                    except Exception as e:
                        print(f"关闭音频流出错 (忽略): {e}")

                # 3. 标记为非播放状态
                self.is_playing = False

                # 4. 清空回调函数
                self.playback_callback = None

                print("播放已安全停止")

            except Exception as e:
                print(f"停止播放时发生错误 (已处理): {e}")
                self.is_playing = False

    def _play_text(self, text, voice=None, speed=None, volume=None):
        """内部播放方法（非阻塞）"""
        self.is_playing = True

        # 使用默认值
        voice = voice or self.default_voice
        speed = speed if speed is not None else self.default_speed
        volume = volume if volume is not None else self.default_volume

        # 构建请求参数
        d = {
            "common": {"app_id": self.app_id},
            "business": {
                "aue": "raw",
                "auf": "audio/L16;rate=16000",
                "vcn": voice,
                "tte": "utf8",
                "speed": speed,
                "volume": volume
            },
            "data": {
                "status": 2,
                "text": str(base64.b64encode(text.encode('utf-8')), "UTF8")
            }
        }

        # 准备音频流，使用指定的输出设备
        try:
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                output=True,
                output_device_index=self.output_device_index,
                frames_per_buffer=2048
            )
            print("音频流已创建")
        except Exception as e:
            print(f"创建音频流失败: {e}")
            self.is_playing = False
            return

        def on_message(ws, message):
            try:
                message = json.loads(message)
                code = message["code"]
                if code != 0:
                    print(f"TTS错误: {message['message']}")
                    ws.close()
                    return

                # 检查是否是当前活动的连接和流
                with self.lock:
                    if ws is not self.current_ws or not self.is_playing:
                        return

                    # 检查流是否仍然有效
                    if self.stream:
                        # 直接播放解码后的音频
                        audio = base64.b64decode(message["data"]["audio"])
                        try:
                            self.stream.write(audio)
                            print(".", end="", flush=True)  # 输出一个点表示正在播放
                        except Exception as e:
                            print(f"播放音频时出错: {e}")
                            ws.close()
                            return

                    if message["data"]["status"] == 2:
                        # 合成完成，设置标志但不直接关闭流（留给on_close处理）
                        print("\n音频合成完成，关闭连接")
                        ws.close()

            except Exception as e:
                print(f"处理消息时出错: {e}")
                try:
                    ws.close()
                except:
                    pass

        def on_error(ws, error):
            print(f"WebSocket错误: {str(error)}")

        def on_close(ws, close_status_code=None, close_msg=None):
            with self.lock:
                # 只有当ws是当前活动连接时才处理
                if ws is self.current_ws:
                    # 安全地关闭流
                    if self.stream:
                        try:
                            self.stream.stop_stream()
                            self.stream.close()
                            print("音频流已关闭")
                        except Exception as e:
                            print(f"关闭音频流时出错: {e}")
                        finally:
                            self.stream = None

                    self.current_ws = None
                    self.is_playing = False
                    print("连接已关闭")

                    # 执行播放完成回调（如果有）
                    if self.playback_callback:
                        try:
                            callback = self.playback_callback
                            self.playback_callback = None  # 清空回调引用
                            callback()  # 执行回调
                            print("回调已执行")
                        except Exception as e:
                            print(f"执行回调时出错: {e}")

                    # 处理队列中的下一个任务
                    def process_next():
                        try:
                            self._process_queue()
                        except Exception as e:
                            print(f"处理队列时出错: {e}")

                    # 启动一个新线程来处理队列，避免递归调用
                    next_thread = threading.Thread(target=process_next)
                    next_thread.daemon = True
                    next_thread.start()

        def on_open(ws):
            # 发送数据（在线程中发送）
            def run(*args):
                try:
                    print("发送数据...")
                    ws.send(json.dumps(d))
                    print("数据已发送")
                except Exception as e:
                    print(f"发送数据时出错: {e}")
                    try:
                        ws.close()
                    except:
                        pass

            thread.start_new_thread(run, ())

        # 创建WebSocket连接
        try:
            ws_url = self.create_url()
            print(f"创建WebSocket连接... URL长度: {len(ws_url)}")
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open
            )

            # 保存当前的WebSocket连接
            self.current_ws = ws
            print("WebSocket对象已创建")

            # 在单独线程中启动WebSocket连接
            def run_ws():
                try:
                    print("运行WebSocket连接...")
                    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
                    print("WebSocket连接已结束")
                except Exception as e:
                    print(f"WebSocket运行出错: {e}")
                    with self.lock:
                        if ws is self.current_ws:
                            self.current_ws = None
                            self.is_playing = False

            self.ws_thread = threading.Thread(target=run_ws)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            print("WebSocket线程已启动")

        except Exception as e:
            print(f"创建WebSocket连接失败: {e}")
            self.is_playing = False
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except:
                    pass
                self.stream = None

    def _process_queue(self):
        """处理播放队列"""
        with self.lock:
            if not self.is_playing and not self.play_queue.empty():
                text, voice, speed, volume, callback = self.play_queue.get()
                self.playback_callback = callback  # 设置回调
                self._play_text(text, voice, speed, volume)

    def clear_queue(self):
        """清空播放队列"""
        with self.lock:
            while not self.play_queue.empty():
                self.play_queue.get()

    def update_device(self, output_device_index):
        """更新输出设备"""
        with self.lock:
            # 保存新的设备索引
            self.output_device_index = output_device_index
            print(f"输出设备已更新为索引: {output_device_index}")

            # 如果当前有流，需要关闭
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    print(f"关闭音频流时出错: {e}")
                finally:
                    self.stream = None

    def get_voice_list(self):
        """获取可用音色列表"""
        return self.available_voices

    def __del__(self):
        """清理资源"""
        try:
            self.stop_speaking()  # 确保停止所有播放
            time.sleep(0.2)  # 给线程一点时间来清理

            # 关闭线程池
            if hasattr(self, 'thread_pool'):
                self.thread_pool.shutdown(wait=False)

            if hasattr(self, 'p') and self.p:
                try:
                    self.p.terminate()
                except:
                    pass
        except:
            pass  # 忽略析构函数中的任何错误


# 使用示例
if __name__ == "__main__":
    # 你的API密钥
    APP_ID = "86c79fb7"
    API_KEY = "f4369644e37eddd43adfe436e7904cf1"
    API_SECRET = "MDY3ZGFkYWEyZDBiOTJkOGIyOTllOWMz"

    tts = RealtimeTTS(APP_ID, API_KEY, API_SECRET)

    # 测试非阻塞播放
    print("开始测试非阻塞播放...")
    print("播放开始, 但主线程不会被阻塞")


    # 播放完成回调函数
    def playback_finished():
        print("\n播放已完成!")


    # 开始播放
    tts.speak("这是一个测试非阻塞播放功能的示例。这段文本应该比较长，但主线程不会被阻塞，你可以继续在控制台输入内容。",
              callback=playback_finished)

    # 演示主线程可以继续工作
    for i in range(10):
        print(f"主线程工作中... ({i + 1}/10)")
        time.sleep(0.5)

    # 给TTS足够的时间启动和播放
    print("等待播放完成或按Ctrl+C停止...")
    try:
        while tts.is_playing:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n用户中断")
        tts.stop_speaking()

    print("测试完成！")