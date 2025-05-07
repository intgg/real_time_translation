# 实时语音合成模块 - 非阻塞式播放版（修复崩溃问题）
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
import pyaudio
import threading
from queue import Queue
import time


class RealtimeTTS:
    """实时语音合成模块 - 非阻塞式播放版"""

    def __init__(self, app_id, api_key, api_secret):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_playing = False
        self.play_queue = Queue()
        self.current_ws = None  # 当前的WebSocket连接
        self.ws_thread = None  # WebSocket线程
        self.lock = threading.Lock()  # 用于线程同步的锁
        self.playback_callback = None  # 新增：播放完成回调函数

        # 音频播放设置
        self.p = pyaudio.PyAudio()
        self.stream = None

        # 默认参数
        self.default_voice = "xiaoyan"  # 中文音色
        self.default_speed = 50
        self.default_volume = 60

        # 支持的音色列表
        self.available_voices = {
            # 中文音色
            "xiaoyan": "小燕 [普通话]",
            "aisjiuxu": "许久 [普通话]",
            "aisxping": "小萍 [普通话]",
            # 其他语种
            "x2_IdId_Kris": "Kris [印尼语]",
            "xiaoyun": "ThuHien [越南语]",
            "yingying": "莹莹 [泰语]",
            "qianhui": "千惠 [日语]",
        }

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
        """停止当前播放，修复了崩溃问题"""
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

        # 准备音频流
        try:
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                output=True,
                frames_per_buffer=2048
            )
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
                        except Exception as e:
                            print(f"播放音频时出错: {e}")
                            ws.close()
                            return

                    if message["data"]["status"] == 2:
                        # 合成完成，设置标志但不直接关闭流（留给on_close处理）
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
                        except Exception as e:
                            print(f"关闭音频流时出错: {e}")
                        finally:
                            self.stream = None

                    self.current_ws = None
                    self.is_playing = False

                    # 执行播放完成回调（如果有）
                    if self.playback_callback:
                        try:
                            callback = self.playback_callback
                            self.playback_callback = None  # 清空回调引用
                            callback()  # 执行回调
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
                    ws.send(json.dumps(d))
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
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open
            )

            # 保存当前的WebSocket连接
            self.current_ws = ws

            # 在单独线程中启动WebSocket连接
            def run_ws():
                try:
                    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
                except Exception as e:
                    print(f"WebSocket运行出错: {e}")
                    with self.lock:
                        if ws is self.current_ws:
                            self.current_ws = None
                            self.is_playing = False

            self.ws_thread = threading.Thread(target=run_ws)
            self.ws_thread.daemon = True
            self.ws_thread.start()

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

    def get_voice_list(self):
        """获取可用音色列表"""
        return self.available_voices

    def __del__(self):
        """清理资源"""
        try:
            self.stop_speaking()  # 确保停止所有播放
            time.sleep(0.2)  # 给线程一点时间来清理

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

    # 开始播放
    tts.speak("这是一个测试非阻塞播放功能的示例。这段文本应该比较长，但主线程不会被阻塞，你可以继续在控制台输入内容。")

    # 演示主线程可以继续工作
    for i in range(10):
        print(f"主线程工作中... ({i + 1}/10)")
        time.sleep(0.5)

    # 测试停止功能
    print("正在停止播放...")
    tts.stop_speaking()

    # 等待一下确保停止生效
    time.sleep(1)

    print("测试完成！")