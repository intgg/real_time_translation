# -*- coding:utf-8 -*-
#
# 讯飞语音听写（流式版）核心模块
# 实现高效的连续实时语音识别

import websocket
import datetime
import hashlib
import base64
import hmac
import json
from urllib.parse import urlencode
import time
import ssl
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import threading
import pyaudio
import sys
import signal


class XunfeiStreamingASR:
    """讯飞流式语音听写核心模块"""

    def __init__(self, app_id, api_key, api_secret):
        """初始化讯飞语音听写流式识别模块

        Args:
            app_id: 讯飞应用ID
            api_key: 讯飞API密钥
            api_secret: 讯飞API密钥对应的Secret
        """
        # 讯飞API参数
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret

        # 识别状态和连接
        self.ws = None
        self.is_running = False

        # 音频参数
        self.chunk = 1024
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        self.p = pyaudio.PyAudio()
        self.stream = None

        # 识别结果
        self.result_buffer = ""  # 已确认的文本结果
        self.intermediate_result = ""  # 临时中间结果
        self.last_result_id = None  # 上一个结果ID(避免重复)

        # 回调函数
        self.on_result_callback = None  # 结果回调
        self.on_error_callback = None  # 错误回调

        # 帧状态
        self.STATUS_FIRST_FRAME = 0  # 第一帧标识
        self.STATUS_CONTINUE_FRAME = 1  # 中间帧标识
        self.STATUS_LAST_FRAME = 2  # 最后一帧标识

    def create_url(self):
        """生成讯飞WebAPI鉴权URL"""
        url = 'wss://ws-api.xfyun.cn/v2/iat'

        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = "host: " + "ws-api.xfyun.cn" + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v2/iat " + "HTTP/1.1"

        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(self.api_secret.encode('utf-8'),
                                 signature_origin.encode('utf-8'),
                                 digestmod=hashlib.sha256).digest()
        signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')

        authorization_origin = "api_key=\"%s\", algorithm=\"%s\", headers=\"%s\", signature=\"%s\"" % (
            self.api_key, "hmac-sha256", "host date request-line", signature_sha)
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')

        # 将请求的鉴权参数组合为字典
        v = {
            "authorization": authorization,
            "date": date,
            "host": "ws-api.xfyun.cn"
        }
        # 拼接鉴权参数，生成url
        url = url + '?' + urlencode(v)
        return url

    def on_message(self, ws, message):
        """WebSocket消息回调 - 处理识别结果"""
        try:
            message_json = json.loads(message)
            code = message_json["code"]

            if code != 0:
                error_msg = message_json["message"]
                self._handle_error(f"错误: {error_msg} (code: {code})")
                return

            # 检查是否有结果
            if "data" in message_json and "result" in message_json["data"]:
                # 解析结果
                data = message_json["data"]["result"]["ws"]
                sid = message_json["sid"]

                result_text = ""
                for i in data:
                    for w in i["cw"]:
                        result_text += w["w"]

                # 检查是否是最终结果
                is_last = message_json["data"]["result"].get("ls", False)

                # 结果处理逻辑 - 连续流式识别核心
                if result_text:
                    # 生成结果ID(避免重复处理相同结果)
                    result_id = f"{sid}_{len(result_text)}"

                    if is_last and result_id != self.last_result_id:
                        # 累积最终结果
                        if not self.result_buffer.endswith(result_text):
                            self.result_buffer += result_text

                            # 调用结果回调函数(如果存在)
                            if self.on_result_callback:
                                self.on_result_callback(self.result_buffer, result_text, True)

                        # 标记该结果已处理
                        self.last_result_id = result_id
                        self.intermediate_result = ""  # 清空中间结果

                    elif not is_last:
                        # 更新中间结果
                        self.intermediate_result = result_text

                        # 调用结果回调函数(如果存在)
                        if self.on_result_callback:
                            # 传递完整的当前识别状态(包括已确认的文本和正在识别的部分)
                            self.on_result_callback(
                                self.result_buffer,
                                result_text,
                                False
                            )

        except Exception as e:
            self._handle_error(f"处理消息出错: {e}")

    def on_error(self, ws, error):
        """WebSocket错误回调"""
        self._handle_error(f"连接错误: {error}")

    def on_close(self, ws, close_status_code=None, close_reason=None):
        """WebSocket关闭回调"""
        print("WebSocket连接已关闭")
        self.is_running = False

    def on_open(self, ws):
        """WebSocket连接建立回调"""
        print("WebSocket连接已建立，开始录音...")

        # 启动录音线程
        self.audio_thread = threading.Thread(target=self._record_audio)
        self.audio_thread.daemon = True
        self.audio_thread.start()

    def _handle_error(self, error_msg):
        """统一处理错误"""
        print(f"错误: {error_msg}", file=sys.stderr)
        if self.on_error_callback:
            self.on_error_callback(error_msg)

    def _record_audio(self):
        """录制并发送音频 - 核心音频处理循环"""
        print("开始录音 - 连续识别模式...")
        status = self.STATUS_FIRST_FRAME  # 音频的状态信息

        try:
            # 初始化音频流
            self.stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )

            while self.is_running and self.stream and self.ws:
                # 读取音频数据
                audio_data = self.stream.read(self.chunk, exception_on_overflow=False)

                # 第一帧处理
                if status == self.STATUS_FIRST_FRAME:
                    # 发送第一帧音频，带business参数
                    d = {
                        "common": {"app_id": self.app_id},
                        "business": {
                            "domain": "iat",
                            "language": "zh_cn",
                            "accent": "mandarin",
                            "vinfo": 1,
                            "vad_eos": 5000,  # 静音检测参数，5秒
                            "dwa": "wpgs"  # 开启wpgs参数，支持更流畅的实时识别
                        },
                        "data": {
                            "status": 0,  # 第一帧标识
                            "format": "audio/L16;rate=16000",
                            "audio": str(base64.b64encode(audio_data), 'utf-8'),
                            "encoding": "raw"
                        }
                    }
                    status = self.STATUS_CONTINUE_FRAME
                # 中间帧处理
                elif status == self.STATUS_CONTINUE_FRAME:
                    d = {
                        "data": {
                            "status": 1,  # 中间帧标识
                            "format": "audio/L16;rate=16000",
                            "audio": str(base64.b64encode(audio_data), 'utf-8'),
                            "encoding": "raw"
                        }
                    }

                # 发送数据
                if self.ws and self.ws.sock and self.ws.sock.connected:
                    self.ws.send(json.dumps(d))
                    # 控制发送频率，模拟正常的音频采样速率
                    time.sleep(0.04)
                else:
                    # WebSocket连接关闭则退出录音循环
                    break

        except Exception as e:
            self._handle_error(f"录音错误: {e}")
        finally:
            print("录音线程结束")
            # 关闭音频流
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None

    def start(self, on_result=None, on_error=None):
        """启动语音识别

        Args:
            on_result: 结果回调函数，参数为(完整文本, 新增文本, 是否最终结果)
            on_error: 错误回调函数，参数为错误消息
        """
        if self.is_running:
            print("识别已在运行中")
            return False

        # 设置回调函数
        self.on_result_callback = on_result
        self.on_error_callback = on_error

        # 重置状态
        self.is_running = True
        self.result_buffer = ""
        self.intermediate_result = ""
        self.last_result_id = None

        # 开始WebSocket连接
        websocket.enableTrace(False)
        ws_url = self.create_url()

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )

        # 在新线程中运行WebSocket连接
        self.ws_thread = threading.Thread(target=self.ws.run_forever,
                                          kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}})
        self.ws_thread.daemon = True
        self.ws_thread.start()

        print("语音识别已启动")
        return True

    def stop(self):
        """停止语音识别"""
        if not self.is_running:
            print("识别未在运行")
            return False

        self.is_running = False

        # 发送最后一帧数据
        try:
            if self.ws and self.ws.sock and self.ws.sock.connected:
                d = {
                    "data": {
                        "status": 2,  # 最后一帧标识
                        "format": "audio/L16;rate=16000",
                        "audio": str(base64.b64encode(bytes(0)), 'utf-8'),
                        "encoding": "raw"
                    }
                }
                self.ws.send(json.dumps(d))
                time.sleep(0.5)  # 给服务器一点时间处理
        except:
            pass

        # 关闭WebSocket连接
        if self.ws:
            self.ws.close()
            self.ws = None

        # 关闭音频流
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

        print("语音识别已停止")
        return True

    def get_result(self):
        """获取当前完整识别结果"""
        return self.result_buffer

    def reset(self):
        """重置识别结果"""
        self.result_buffer = ""
        self.intermediate_result = ""
        self.last_result_id = None
        print("识别结果已重置")

    def __del__(self):
        """析构函数 - 确保资源释放"""
        if self.is_running:
            self.stop()

        if hasattr(self, 'p') and self.p:
            self.p.terminate()


# 简单的命令行演示
if __name__ == "__main__":
    # 讯飞API密钥
    APP_ID = "86c79fb7"
    API_KEY = "f4369644e37eddd43adfe436e7904cf1"
    API_SECRET = "MDY3ZGFkYWEyZDBiOTJkOGIyOTllOWMz"

    # 终端显示设置
    ALL_RESULT_SHOWN = True  # 是否每次显示完整结果

    # 创建识别器
    asr = XunfeiStreamingASR(APP_ID, API_KEY, API_SECRET)


    # 结果回调函数
    def on_result(complete_text, new_text, is_final):
        if is_final:
            # 最终结果
            if ALL_RESULT_SHOWN:
                # 显示完整文本
                print(f"\r完整识别结果: {complete_text}")
            else:
                # 只显示新增部分
                print(f"\r最终识别: {new_text}")
        else:
            # 中间结果 - 使用\r可以在同一行更新
            print(f"\r当前识别中: {complete_text + new_text}", end="")


    # 设置信号处理 - 优雅退出
    running = True


    def signal_handler(sig, frame):
        global running
        print("\n停止识别...")
        running = False
        asr.stop()


    signal.signal(signal.SIGINT, signal_handler)

    # 启动识别
    asr.start(on_result=on_result)

    print("\n开始语音识别，请对着麦克风说话...")
    print("按Ctrl+C停止")

    # 主循环
    try:
        while running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        asr.stop()
        print("\n识别已结束。完整结果:")
        print(asr.get_result())