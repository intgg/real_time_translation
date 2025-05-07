# 优化的文本翻译模块 - 纯文本输出
from datetime import datetime
from wsgiref.handlers import format_date_time
from time import mktime
import hashlib
import base64
import hmac
from urllib.parse import urlencode
import json
import requests
from threading import Lock


class TranslationModule:
    """优化的星火机器翻译模块"""

    def __init__(self, app_id, api_secret, api_key):
        """
        初始化翻译模块

        参数:
            app_id: APPID
            api_secret: APISecret
            api_key: APIKey
        """
        self.app_id = app_id
        self.api_secret = api_secret
        self.api_key = api_key
        self.url = 'https://itrans.xf-yun.com/v1/its'
        self.res_id = "its_en_cn_word"  # 术语资源ID
        self.lock = Lock()  # 线程锁，确保线程安全

    def parse_url(self, request_url):
        """解析URL"""
        stidx = request_url.index("://")
        host = request_url[stidx + 3:]
        schema = request_url[:stidx + 3]
        edidx = host.index("/")
        if edidx <= 0:
            raise Exception("invalid request url:" + request_url)
        path = host[edidx:]
        host = host[:edidx]
        return {"host": host, "path": path, "schema": schema}

    def assemble_auth_url(self, request_url, method="POST"):
        """构建带认证的请求URL"""
        url_parts = self.parse_url(request_url)
        host = url_parts["host"]
        path = url_parts["path"]

        # 生成时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 生成签名
        signature_origin = f"host: {host}\ndate: {date}\n{method} {path} HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode('utf-8'),
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature_sha = base64.b64encode(signature_sha).decode('utf-8')

        # 构建authorization
        authorization_origin = f'api_key="{self.api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha}"'
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')

        # 构建完整URL
        values = {
            "host": host,
            "date": date,
            "authorization": authorization
        }

        return request_url + "?" + urlencode(values)

    def translate(self, text, from_lang="cn", to_lang="en", use_terminology=True):
        """
        执行文本翻译

        参数:
            text: 待翻译文本
            from_lang: 源语言（cn：中文，en：英文）
            to_lang: 目标语言（cn：中文，en：英文）
            use_terminology: 是否使用术语资源

        返回:
            翻译结果字符串，如果出错返回None
        """
        with self.lock:  # 确保线程安全
            try:
                # 检查文本长度
                if len(text) > 5000:
                    raise Exception("文本超过5000字符限制")

                # 构建请求体
                body = {
                    "header": {
                        "app_id": self.app_id,
                        "status": 3
                    },
                    "parameter": {
                        "its": {
                            "from": from_lang,
                            "to": to_lang,
                            "result": {}
                        }
                    },
                    "payload": {
                        "input_data": {
                            "encoding": "utf8",
                            "status": 3,
                            "text": base64.b64encode(text.encode("utf-8")).decode('utf-8')
                        }
                    }
                }

                # 添加术语资源
                if use_terminology:
                    body["header"]["res_id"] = self.res_id

                # 构建请求URL
                request_url = self.assemble_auth_url(self.url, "POST")

                # 设置请求头
                headers = {
                    'content-type': "application/json",
                    'host': 'itrans.xf-yun.com',
                    'app_id': self.app_id
                }

                # 发送请求
                response = requests.post(request_url, data=json.dumps(body), headers=headers)
                result = json.loads(response.content.decode())

                # 解析返回结果
                if 'payload' in result and 'result' in result['payload'] and 'text' in result['payload']['result']:
                    translated_text = base64.b64decode(result['payload']['result']['text']).decode()

                    # 解析JSON格式的响应，只提取翻译文本
                    try:
                        json_result = json.loads(translated_text)
                        # 提取翻译结果
                        if 'trans_result' in json_result and 'dst' in json_result['trans_result']:
                            return json_result['trans_result']['dst']
                        elif 'dst' in json_result:
                            return json_result['dst']
                        else:
                            # 如果找不到预期的字段，返回完整JSON
                            return translated_text
                    except:
                        # 如果不是JSON格式，返回原始文本
                        return translated_text
                else:
                    print(f"翻译API错误: {result}")
                    return None

            except Exception as e:
                print(f"翻译过程出错: {str(e)}")
                return None

    def batch_translate(self, texts, from_lang="cn", to_lang="en"):
        """
        批量翻译文本

        参数:
            texts: 文本列表
            from_lang: 源语言
            to_lang: 目标语言

        返回:
            翻译结果列表
        """
        results = []
        for text in texts:
            result = self.translate(text, from_lang, to_lang)
            results.append(result)
        return results


# 使用示例
if __name__ == "__main__":
    # 你的API密钥（这里使用文档中的示例密钥）
    APP_ID = "86c79fb7"
    API_SECRET = "MDY3ZGFkYWEyZDBiOTJkOGIyOTllOWMz"
    API_KEY = "f4369644e37eddd43adfe436e7904cf1"

    translator = TranslationModule(APP_ID, API_SECRET, API_KEY)

    # 测试中英互译
    print("测试中文到英文翻译：")
    chinese_text = "测试中文转英文"
    english_result = translator.translate(chinese_text, "cn", "en")
    if english_result:
        print(f"中文：{chinese_text}")
        print(f"英文：{english_result}\n")

    print("测试英文到中文翻译：")
    english_text = "Test Chinese to English"
    chinese_result = translator.translate(english_text, "en", "cn")
    if chinese_result:
        print(f"英文：{english_text}")
        print(f"中文：{chinese_result}\n")