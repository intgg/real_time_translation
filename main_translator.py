# 实时语音翻译系统（多语种非阻塞版本）
import time
import threading
from queue import Queue
import tkinter as tk
from tkinter import ttk, scrolledtext

# 导入我们的模块
from realtime_asr import RealtimeASR
from translation_module import TranslationModule
from realtime_tts import RealtimeTTS


class RealtimeTranslator:
    """实时语音翻译系统"""

    def __init__(self, asr_app_id, asr_api_key, app_id, api_key, api_secret):
        # 初始化三个模块
        self.asr = RealtimeASR(asr_app_id, asr_api_key)
        self.translator = TranslationModule(app_id, api_secret, api_key)
        self.tts = RealtimeTTS(app_id, api_key, api_secret)

        # 状态控制
        self.is_running = False
        self.is_testing = False  # 跟踪是否正在试听
        self.is_speaking = False  # 新增：跟踪TTS是否正在播放
        self.asr_paused = False  # 新增：跟踪ASR是否被暂停
        self.auto_pause_recognition = True  # 新增：是否自动暂停识别的开关
        self.target_language = "en"  # 默认翻译为英文

        # 语音合成设置
        self.current_voice = "aisjiuxu"  # 默认音色
        self.voice_speed = 50  # 默认语速
        self.voice_volume = 60  # 默认音量

        # 支持的语言和对应的音色
        self.supported_languages = {
            "en": {"name": "英语", "code": "en", "default_voice": "aisjiuxu"},
            "cn": {"name": "中文", "code": "cn", "default_voice": "xiaoyan"},
            "id": {"name": "印尼语", "code": "id", "default_voice": "x2_IdId_Kris"},
            "vi": {"name": "越南语", "code": "vi", "default_voice": "xiaoyun"},
            "th": {"name": "泰语", "code": "th", "default_voice": "yingying"},
            "ja": {"name": "日语", "code": "ja", "default_voice": "qianhui"}
        }

        # 语言到音色的映射
        self.language_voices = {
            "en": ["aisjiuxu"],  # 英语音色
            "cn": ["xiaoyan", "aisjiuxu", "aisxping"],  # 中文音色
            "id": ["x2_IdId_Kris"],  # 印尼语音色
            "vi": ["xiaoyun"],  # 越南语音色
            "th": ["yingying"],  # 泰语音色
            "ja": ["qianhui"]  # 日语音色
        }

        # 结果队列
        self.recognition_queue = Queue()
        self.translation_queue = Queue()

        # 创建GUI
        self.create_gui()

        # 设置监控计时器
        self.setup_monitor_timer()

    # 新增方法：暂停语音识别
    def pause_recognition(self):
        if self.is_running and not self.asr_paused:
            print("暂停语音识别...")
            self.asr.stop()  # 停止WebSocket连接
            self.asr_paused = True
            self.update_gui("source", "[系统正在播放语音，识别已暂停]\n")
            self.update_status_display()  # 更新状态显示

    # 新增方法：恢复语音识别
    def resume_recognition(self):
        if self.is_running and self.asr_paused:
            print("恢复语音识别...")
            self.asr.start()  # 重新启动WebSocket连接
            self.asr_paused = False
            self.update_gui("source", "[识别已恢复]\n")
            self.update_status_display()  # 更新状态显示

    # 修改speak方法封装，添加播放前后的处理
    def speak_with_coordination(self, text, voice=None, speed=None, volume=None):
        """根据用户设置协调语音播放和识别"""
        # 标记为正在播放状态
        self.is_speaking = True

        # 仅在用户启用了自动暂停功能时暂停识别
        if self.auto_pause_recognition:
            self.pause_recognition()
        elif not self.asr_paused:
            # 如果没有启用自动暂停，但识别已被其他原因暂停，保持现状
            # 否则更新状态显示
            self.update_status_display()

        # 设置TTS播放完成的回调
        def on_playback_finished():
            self.is_speaking = False

            # 仅在之前由于播放而暂停识别的情况下恢复识别
            if self.auto_pause_recognition and self.asr_paused:
                self.resume_recognition()
            else:
                # 仅更新状态显示
                self.update_status_display()

        # 将回调函数传递给TTS模块
        self.tts.speak(text, voice, speed, volume, callback=on_playback_finished)

    def update_status_display(self):
        """更新状态显示"""
        if not self.is_running:
            self.status_label.config(text="状态: 待机", foreground="gray")
        elif self.is_speaking and self.asr_paused:
            self.status_label.config(text="状态: 播放中 (识别已暂停)", foreground="orange")
        elif self.is_speaking and not self.asr_paused:
            self.status_label.config(text="状态: 播放中 (识别进行中)", foreground="blue")
        elif self.asr_paused:
            self.status_label.config(text="状态: 识别已暂停", foreground="orange")
        else:
            self.status_label.config(text="状态: 运行中", foreground="green")

    def detect_language(self, text):
        """简单的语言检测"""
        # 检测中文
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                return "cn"

        # 这里可以扩展更多语言检测逻辑
        # 暂时默认其他文本为英文
        return "en"

    def create_gui(self):
        """创建图形界面"""
        self.root = tk.Tk()
        self.root.title("多语种实时语音翻译系统")
        self.root.geometry("900x700")

        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 上部分：语言和控制区域
        control_frame = ttk.LabelFrame(main_frame, text="翻译控制")
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # 第一行：语言选择和开始/停止按钮
        lang_control_frame = ttk.Frame(control_frame)
        lang_control_frame.pack(fill=tk.X, padx=5, pady=5)

        # 目标语言选择
        ttk.Label(lang_control_frame, text="目标语言:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)

        # 语言下拉菜单
        self.lang_var = tk.StringVar()
        lang_values = [lang["name"] for lang in self.supported_languages.values()]
        self.lang_combo = ttk.Combobox(lang_control_frame, textvariable=self.lang_var,
                                       values=lang_values, state="readonly", width=10)
        self.lang_combo.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.lang_combo.current(0)  # 默认选择第一个语言（英语）

        # 监听语言选择变化
        self.lang_combo.bind('<<ComboboxSelected>>', self.on_language_change)

        # 音色选择
        ttk.Label(lang_control_frame, text="音色:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.voice_var = tk.StringVar()
        self.voice_combo = ttk.Combobox(lang_control_frame, textvariable=self.voice_var,
                                        state="readonly", width=15)
        self.voice_combo.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W + tk.E)

        # 初始化音色选项（英语音色）
        self.update_voice_options("en")

        # 监听音色变化
        self.voice_combo.bind('<<ComboboxSelected>>', self.on_voice_change)

        # 开始/停止按钮
        self.start_btn = ttk.Button(lang_control_frame, text="开始翻译",
                                    command=self.toggle_translation)
        self.start_btn.grid(row=0, column=4, padx=20, pady=5)

        # 状态显示
        self.status_label = ttk.Label(lang_control_frame, text="状态: 待机", foreground="gray")
        self.status_label.grid(row=0, column=5, padx=5, pady=5)

        # 清空按钮
        clear_btn = ttk.Button(lang_control_frame, text="清空显示", command=self.clear_display)
        clear_btn.grid(row=0, column=6, padx=5, pady=5)

        # 添加播放时暂停识别的选项行
        options_frame = ttk.Frame(control_frame)
        options_frame.pack(fill=tk.X, padx=5, pady=5)

        # 添加播放时暂停识别的复选框
        self.auto_pause_var = tk.BooleanVar(value=True)  # 默认开启
        self.auto_pause_cb = ttk.Checkbutton(
            options_frame,
            text="播放时暂停识别（避免语音干扰）",
            variable=self.auto_pause_var,
            command=self.toggle_auto_pause
        )
        self.auto_pause_cb.pack(side=tk.LEFT, padx=10)

        # 添加提示标签（当禁用时显示）
        self.auto_pause_hint = ttk.Label(
            options_frame,
            text="注意：关闭此选项可能导致系统识别到自己播放的声音",
            foreground="orange"
        )
        # 默认隐藏提示
        if self.auto_pause_var.get():
            self.auto_pause_hint.pack_forget()
        else:
            self.auto_pause_hint.pack(side=tk.LEFT, padx=10)

        # 第二行：语速和音量控制
        voice_control_frame = ttk.Frame(control_frame)
        voice_control_frame.pack(fill=tk.X, padx=5, pady=5)

        # 语速控制
        ttk.Label(voice_control_frame, text="语速:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)

        # 语速滑块（1-10对应0-100）
        def update_speed(val):
            user_speed = int(float(val))
            self.voice_speed = int((user_speed - 1) * (100 / 9))
            self.speed_label.config(text=f"{user_speed}/10")

        self.speed_scale = ttk.Scale(voice_control_frame, from_=1, to=10, orient=tk.HORIZONTAL,
                                     command=update_speed, value=5, length=200)
        self.speed_scale.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W + tk.E)

        self.speed_label = ttk.Label(voice_control_frame, text="5/10")
        self.speed_label.grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)

        # 音量控制
        ttk.Label(voice_control_frame, text="音量:").grid(row=0, column=3, padx=15, pady=5, sticky=tk.W)

        # 音量滑块（1-10对应0-100）
        def update_volume(val):
            user_volume = int(float(val))
            self.voice_volume = int((user_volume - 1) * (100 / 9))
            self.volume_label.config(text=f"{user_volume}/10")

        self.volume_scale = ttk.Scale(voice_control_frame, from_=1, to=10, orient=tk.HORIZONTAL,
                                      command=update_volume, value=6, length=200)
        self.volume_scale.grid(row=0, column=4, padx=5, pady=5, sticky=tk.W + tk.E)

        self.volume_label = ttk.Label(voice_control_frame, text="6/10")
        self.volume_label.grid(row=0, column=5, padx=5, pady=5, sticky=tk.W)

        # 测试和停止按钮
        test_frame = ttk.Frame(voice_control_frame)
        test_frame.grid(row=0, column=6, padx=10, pady=5)

        # 测试按钮
        self.test_btn = ttk.Button(test_frame, text="试听音色",
                                   command=self.test_current_voice)
        self.test_btn.pack(side=tk.LEFT, padx=5)

        # 停止试听按钮
        self.stop_test_btn = ttk.Button(test_frame, text="停止试听",
                                        command=self.stop_test_voice, state=tk.DISABLED)
        self.stop_test_btn.pack(side=tk.LEFT, padx=5)

        # 中间部分：显示区域
        display_frame = ttk.Frame(main_frame)
        display_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=10)

        # 原文显示
        ttk.Label(display_frame, text="语音识别结果:").pack(anchor=tk.W)
        self.source_text = scrolledtext.ScrolledText(display_frame, height=8)
        self.source_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 译文显示
        ttk.Label(display_frame, text="翻译结果:").pack(anchor=tk.W)
        self.translated_text = scrolledtext.ScrolledText(display_frame, height=8)
        self.translated_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 底部：使用说明
        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, padx=5, pady=5)

        # 支持的语言提示
        supported_langs = ", ".join([lang["name"] for lang in self.supported_languages.values()])
        ttk.Label(info_frame,
                  text=f"支持的目标语言: {supported_langs}",
                  foreground="blue").pack(pady=2)

        ttk.Label(info_frame,
                  text="系统会自动检测输入语言，并翻译为所选目标语言",
                  foreground="blue").pack(pady=2)

        # 试听提示 - 修复语法错误，使用英文引号
        ttk.Label(info_frame,
                  text='试听功能: 点击"试听音色"体验当前设置，可随时点击"停止试听"终止播放。试听过程中界面可以正常操作。',
                  foreground="green").pack(pady=2)

        # 初始调用一次语言变更，设置默认值
        self.on_language_change()

    # 添加切换自动暂停的处理方法
    def toggle_auto_pause(self):
        """处理自动暂停识别选项的变化"""
        self.auto_pause_recognition = self.auto_pause_var.get()

        # 更新界面提示
        if self.auto_pause_recognition:
            self.auto_pause_hint.pack_forget()
        else:
            self.auto_pause_hint.pack(side=tk.LEFT, padx=10)

        print(f"{'启用' if self.auto_pause_recognition else '禁用'}播放时暂停识别功能")

        # 如果当前正在播放并且改为不暂停识别，则恢复识别
        if self.is_speaking and not self.auto_pause_recognition and self.asr_paused:
            self.resume_recognition()

    def setup_monitor_timer(self):
        """设置定时器监控播放状态"""

        def check_playing_status():
            # 检查TTS模块的播放状态
            if self.is_testing and not self.tts.is_playing:
                # 如果标记为正在测试，但实际上已经不在播放了
                self.is_testing = False
                self.test_btn.config(state=tk.NORMAL)
                self.stop_test_btn.config(state=tk.DISABLED)

            # 每200毫秒检查一次
            self.root.after(200, check_playing_status)

        # 启动定时器
        self.root.after(200, check_playing_status)

    def on_language_change(self, event=None):
        """处理语言变更"""
        # 获取选择的语言名称
        selected_lang_name = self.lang_var.get()

        # 查找对应的语言代码
        selected_lang_code = None
        for code, info in self.supported_languages.items():
            if info["name"] == selected_lang_name:
                selected_lang_code = code
                break

        if selected_lang_code:
            # 更新目标语言
            self.target_language = selected_lang_code

            # 更新可用的音色选项
            self.update_voice_options(selected_lang_code)

    def update_voice_options(self, lang_code):
        """根据语言更新音色选项"""
        # 获取该语言支持的音色
        voices = self.language_voices.get(lang_code, [])

        # 获取音色名称
        voice_names = []
        for voice_id in voices:
            name = self.tts.available_voices.get(voice_id, voice_id)
            voice_names.append(f"{name} ({voice_id})")

        # 更新下拉菜单
        self.voice_combo['values'] = voice_names

        # 选择默认音色
        default_voice = self.supported_languages[lang_code]["default_voice"]
        self.current_voice = default_voice

        # 找到默认音色的索引
        default_index = 0
        for i, voice_id in enumerate(voices):
            if voice_id == default_voice:
                default_index = i
                break

        # 设置当前选中值
        if voice_names:
            self.voice_combo.current(default_index)

    def on_voice_change(self, event=None):
        """处理音色变更"""
        selected_voice = self.voice_var.get()

        # 从选中值中提取音色ID（假设格式为"名称 (ID)"）
        if selected_voice:
            voice_id = selected_voice.split("(")[-1].strip(")")
            self.current_voice = voice_id

    def test_current_voice(self):
        """测试当前选择的音色（非阻塞）"""
        # 如果正在试听，先停止
        if self.is_testing:
            self.stop_test_voice()

        # 根据当前语言获取测试文本 - 修复语法错误，使用英文引号
        test_texts = {
            "cn": '这是一段中文测试，当前语速和音量设置。你可以随时点击"停止试听"按钮来中断播放。试听过程中，界面可以正常操作。',
            "en": "This is an English test for the current speed and volume settings. You can click the 'Stop Testing' button at any time to interrupt playback. The interface remains fully operational during playback.",
            "id": "Ini adalah tes bahasa Indonesia untuk pengaturan kecepatan dan volume saat ini. Anda dapat mengklik tombol 'Berhenti Mendengarkan' kapan saja untuk menghentikan pemutaran. Antarmuka tetap dapat dioperasikan selama pemutaran.",
            "vi": "Đây là bài kiểm tra tiếng Việt cho cài đặt tốc độ và âm lượng hiện tại. Bạn có thể nhấp vào nút 'Dừng Thử' bất kỳ lúc nào để ngắt phát lại. Giao diện vẫn hoạt động đầy đủ trong quá trình phát lại.",
            "th": "นี่คือการทดสอบภาษาไทยสำหรับการตั้งค่าความเร็วและระดับเสียงปัจจุบัน คุณสามารถคลิกปุ่ม 'หยุดการทดสอบ' เมื่อใดก็ได้เพื่อหยุดการเล่น อินเทอร์เฟซยังคงทำงานได้อย่างเต็มที่ระหว่างการเล่น",
            "ja": "これは現在の速度と音量設定のための日本語テストです。いつでも「試聴停止」ボタンをクリックすると、再生を中断できます。再生中もインターフェースは完全に操作可能です。"
        }

        # 获取当前语言的测试文本，如果没有则使用英文
        test_text = test_texts.get(self.target_language, test_texts["en"])

        # 标记为正在试听
        self.is_testing = True

        # 更新按钮状态
        self.test_btn.config(state=tk.DISABLED)
        self.stop_test_btn.config(state=tk.NORMAL)

        # 非阻塞方式播放测试文本
        self.tts.speak(test_text, voice=self.current_voice,
                       speed=self.voice_speed, volume=self.voice_volume)

    def stop_test_voice(self):
        """停止试听音色"""
        if self.is_testing:
            # 调用TTS的停止方法
            self.tts.stop_speaking()

            # 更新状态和按钮
            self.is_testing = False
            self.test_btn.config(state=tk.NORMAL)
            self.stop_test_btn.config(state=tk.DISABLED)

    def toggle_translation(self):
        """开始/停止翻译"""
        if not self.is_running:
            self.start_translation()
        else:
            self.stop_translation()

    def start_translation(self):
        """开始翻译"""
        # 如果正在试听，先停止
        if self.is_testing:
            self.stop_test_voice()

        self.is_running = True
        self.start_btn.config(text="停止翻译")
        self.status_label.config(text="状态: 运行中", foreground="green")

        # 启动语音识别
        self.asr.start()

        # 启动处理线程
        self.process_thread = threading.Thread(target=self.process_recognition)
        self.process_thread.daemon = True
        self.process_thread.start()

        self.translate_thread = threading.Thread(target=self.process_translation)
        self.translate_thread.daemon = True
        self.translate_thread.start()

        # 更新状态显示
        self.update_status_display()

    def stop_translation(self):
        """停止翻译"""
        self.is_running = False
        self.start_btn.config(text="开始翻译")
        self.status_label.config(text="状态: 待机", foreground="gray")

        # 停止语音识别
        self.asr.stop()

        # 清空播放队列
        self.tts.clear_queue()

        # 更新状态显示
        self.update_status_display()

    def clear_display(self):
        """清空显示区域"""
        self.source_text.delete(1.0, tk.END)
        self.translated_text.delete(1.0, tk.END)

    def process_recognition(self):
        """处理语音识别结果"""
        intermediate_text = ""

        while self.is_running:
            result = self.asr.get_result()
            if result:
                if isinstance(result, dict):
                    if "error" in result:
                        self.update_gui("source", f"错误: {result['error']}")
                        self.stop_translation()
                        break
                    elif "text" in result:
                        if result["is_final"]:
                            # 最终结果
                            text = result["text"]
                            # 如果有中间结果，先清除它
                            if intermediate_text:
                                self.source_text.delete("end-2l", "end-1l")
                                intermediate_text = ""
                            self.update_gui("source", text + "\n")
                            # 将最终结果放入翻译队列
                            if text.strip():
                                self.recognition_queue.put(text)
                        else:
                            # 中间结果 - 显示在同一行
                            text = result["text"]
                            if text != intermediate_text:
                                intermediate_text = text
                                self.update_gui("source", f"[识别中] {text}", append=False)
            time.sleep(0.1)

    def process_translation(self):
        """处理翻译和语音合成"""
        while self.is_running:
            if not self.recognition_queue.empty() and not self.is_speaking:
                text = self.recognition_queue.get()

                # 自动检测源语言
                source_lang = self.detect_language(text)

                # 如果源语言与目标语言相同，直接使用原文
                if source_lang == self.target_language:
                    translated = text
                    # 直接显示在翻译结果区域
                    self.update_gui("translation", translated + "\n")
                    # 使用新的协调方法朗读原文
                    self.speak_with_coordination(translated, voice=self.current_voice,
                                                 speed=self.voice_speed, volume=self.voice_volume)
                else:
                    # 执行翻译
                    translated = self.translator.translate(text, source_lang, self.target_language)

                    if translated:
                        self.update_gui("translation", translated + "\n")
                        # 使用新的协调方法朗读翻译结果
                        self.speak_with_coordination(translated, voice=self.current_voice,
                                                     speed=self.voice_speed, volume=self.voice_volume)
                    else:
                        self.update_gui("translation", "[翻译失败]\n")

            time.sleep(0.1)

    def update_gui(self, widget_type, text, append=True):
        """更新GUI显示"""

        def update():
            if widget_type == "source":
                if append:
                    self.source_text.insert(tk.END, text)
                    self.source_text.see(tk.END)
                else:
                    # 更新最后一行（用于中间结果）
                    self.source_text.delete("end-2l", tk.END)
                    self.source_text.insert(tk.END, text + "\n")
                    self.source_text.see(tk.END)
            elif widget_type == "translation":
                self.translated_text.insert(tk.END, text)
                self.translated_text.see(tk.END)

        # 使用线程安全的方式更新GUI
        self.root.after(0, update)

    def run(self):
        """运行主程序"""
        try:
            self.root.mainloop()
        finally:
            # 确保清理资源
            if self.is_testing:
                self.stop_test_voice()

            if hasattr(self.tts, '__del__'):
                self.tts.__del__()


if __name__ == "__main__":
    # 不同API服务的密钥配置

    # 机器翻译和语音合成使用的密钥
    APP_ID = "86c79fb7"
    API_KEY = "f4369644e37eddd43adfe436e7904cf1"
    API_SECRET = "MDY3ZGFkYWEyZDBiOTJkOGIyOTllOWMz"

    # 实时语音转写使用的密钥
    ASR_APP_ID = "86c79fb7"
    ASR_API_KEY = "acf74303ddb1af7196de01aadd232feb"

    # 创建并运行翻译系统
    translator = RealtimeTranslator(ASR_APP_ID, ASR_API_KEY, APP_ID, API_KEY, API_SECRET)
    translator.run()