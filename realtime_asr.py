# 实时语音识别模块 - 讯飞ASR实时版（修复导入）
import base64
import hashlib
import hmac
import json
import time
import threading
import pyaudio
import websocket  # websocket-client包导入时就用websocket
from queue import Queue
from urllib.parse import urlencode


class RealtimeASR:
    def __init__(self, app_id, api_key):
        self.app_id = app_id
        self.api_key = api_key
        self.is_running = False
        self.ws = None
        self.recognition_result = ""
        self.result_queue = Queue()
        self.audio_thread = None

        # 音频参数
        self.chunk = 1280
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000

        # 静音检测参数
        self.silence_threshold = 500  # 静音阈值
        self.silence_frames = 0  # 连续静音帧计数
        self.silence_frames_threshold = 15  # 认定为静音的连续帧数
        self.was_silence = True  # 上一状态是否为静音

    def create_signature(self, ts):
        """生成讯飞API调用签名"""
        base_string = self.app_id + str(ts)
        md5 = hashlib.md5()
        md5.update(base_string.encode('utf-8'))
        md5_str = md5.hexdigest()

        hmac_obj = hmac.new(self.api_key.encode('utf-8'), md5_str.encode('utf-8'), hashlib.sha1)
        signature = base64.b64encode(hmac_obj.digest()).decode('utf-8')
        return signature

    def build_auth_url(self, ts, signature, lang='cn'):
        """构建鉴权URL"""
        params = {
            'appid': self.app_id,
            'ts': str(ts),
            'signa': signature,
            'lang': lang,
        }
        return 'wss://rtasr.xfyun.cn/v1/ws?' + urlencode(params)

    def on_message(self, ws, message):
        """WebSocket消息回调"""
        result = json.loads(message)

        if result["action"] == "started":
            print("连接建立成功")
        elif result["action"] == "result":
            data = json.loads(result["data"])
            text = self.parse_result(data)
            if text:
                self.result_queue.put(text)
        elif result["action"] == "error":
            error_info = f"错误：{result['desc']}, code: {result['code']}"
            print(error_info)
            self.result_queue.put({"error": error_info})
            ws.close()

    def on_error(self, ws, error):
        """WebSocket错误回调"""
        error_info = f"WebSocket错误：{str(error)}"
        print(error_info)
        self.result_queue.put({"error": error_info})

    def on_close(self, ws, close_status_code, close_reason):
        """WebSocket关闭回调"""
        print("连接已关闭")
        self.is_running = False

    def on_open(self, ws):
        """WebSocket连接建立回调"""
        print("开始录音...")
        self.is_running = True
        self.audio_thread = threading.Thread(target=self.record_and_send)
        self.audio_thread.start()

    def parse_result(self, data):
        """解析转写结果"""
        if "cn" in data:
            sentence = ""
            result_type = data["cn"]["st"]["type"]

            for word in data["cn"]["st"]["rt"][0]["ws"]:
                sentence += word["cw"][0]["w"]

            # 返回结果类型和文本
            if result_type == "0":
                return {"text": sentence, "is_final": True}
            else:
                return {"text": sentence, "is_final": False}
        return None

    def detect_silence(self, audio_data):
        """检测是否为静音"""
        # 计算音频数据的振幅
        amplitude = max(abs(int.from_bytes(audio_data[i:i + 2], byteorder='little', signed=True))
                        for i in range(0, len(audio_data), 2))

        # 判断是否为静音
        is_silent = amplitude < self.silence_threshold

        # 更新连续静音帧计数
        if is_silent:
            self.silence_frames += 1
        else:
            self.silence_frames = 0

        # 状态判断逻辑（防止短暂的噪音被误判为有效语音）
        result_is_silent = self.was_silence

        # 如果连续多帧静音，状态转为静音
        if self.silence_frames >= self.silence_frames_threshold:
            result_is_silent = True
        # 如果当前帧非静音，状态转为非静音
        elif not is_silent:
            result_is_silent = False

        # 记录状态变化
        if result_is_silent != self.was_silence:
            self.was_silence = result_is_silent
            if result_is_silent:
                print("检测到静音")
            else:
                print("检测到声音")

        return result_is_silent

    def record_and_send(self):
        """录音并发送到讯飞API"""
        p = pyaudio.PyAudio()

        try:
            stream = p.open(format=self.format,
                            channels=self.channels,
                            rate=self.rate,
                            input=True,
                            frames_per_buffer=self.chunk)

            while self.is_running:
                audio_data = stream.read(self.chunk)

                # 进行静音检测
                is_silent = self.detect_silence(audio_data)

                # 只有在非静音状态才发送数据
                if not is_silent and self.ws:
                    self.ws.send(audio_data, opcode=websocket.ABNF.OPCODE_BINARY)
                elif self.ws:
                    # 在静音状态下仍然发送数据，但可以降低频率
                    # 这里可以每隔几帧发送一次，以保持连接活跃
                    if self.silence_frames % 5 == 0:  # 每5帧发送一次
                        self.ws.send(audio_data, opcode=websocket.ABNF.OPCODE_BINARY)

                time.sleep(0.04)

        except Exception as e:
            error_info = f"录音错误: {str(e)}"
            print(error_info)
            self.result_queue.put({"error": error_info})
        finally:
            # 发送结束标志
            if self.ws:
                end_tag = json.dumps({"end": True})
                self.ws.send(end_tag, opcode=websocket.ABNF.OPCODE_BINARY)

            stream.stop_stream()
            stream.close()
            p.terminate()

    def start(self):
        """启动实时语音识别"""
        ts = int(time.time())
        signature = self.create_signature(ts)
        url = self.build_auth_url(ts, signature)

        print("连接到服务器...")
        self.ws = websocket.WebSocketApp(
            url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )

        # 在新线程中运行WebSocket
        self.ws_thread = threading.Thread(target=self.ws.run_forever)
        self.ws_thread.daemon = True
        self.ws_thread.start()

    def stop(self):
        """停止实时语音识别"""
        self.is_running = False
        if self.ws:
            self.ws.close()

    def get_result(self):
        """获取识别结果"""
        if not self.result_queue.empty():
            return self.result_queue.get()
        return None


# 使用示例
if __name__ == "__main__":
    # 你的讯飞API密钥
    APP_ID = "86c79fb7"
    API_KEY = "acf74303ddb1af7196de01aadd232feb"

    asr = RealtimeASR(APP_ID, API_KEY)

    try:
        # 启动识别
        asr.start()

        # 持续获取结果
        print("\n开始实时语音识别，按Ctrl+C停止...")
        while True:
            result = asr.get_result()
            if result:
                if isinstance(result, dict):
                    if "error" in result:
                        print(f"\n错误: {result['error']}")
                        break
                    elif "text" in result:
                        if result["is_final"]:
                            print(f"\n[最终] {result['text']}")
                        else:
                            print(f"\r[中间] {result['text']}", end="")
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\n停止识别...")
        asr.stop()