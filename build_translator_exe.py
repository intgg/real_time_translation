# build_translator_exe.py
# 将多语种实时翻译系统打包为单个EXE文件

import os
import shutil
import subprocess
import sys


def check_pyinstaller():
    """检查是否安装了PyInstaller"""
    try:
        import PyInstaller
        print("✓ PyInstaller已安装")
        return True
    except ImportError:
        print("✗ 未检测到PyInstaller，将尝试安装...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("✓ PyInstaller安装成功")
            return True
        except subprocess.CalledProcessError:
            print("✗ PyInstaller安装失败")
            return False


def check_required_modules():
    """检查必要的Python模块是否已安装"""
    required_modules = [
        "websocket-client",
        "pyaudio",
        "requests",
        "tkinter"
    ]

    missing_modules = []

    for module in required_modules:
        try:
            if module == "websocket-client":
                import websocket
            elif module == "tkinter":
                import tkinter
            else:
                __import__(module)
            print(f"✓ {module} 已安装")
        except ImportError:
            missing_modules.append(module)
            print(f"✗ {module} 未安装")

    if missing_modules:
        print("\n正在安装缺失的模块...")
        for module in missing_modules:
            module_name = module
            if module == "websocket-client":
                module_name = "websocket-client"

            try:
                subprocess.run([sys.executable, "-m", "pip", "install", module_name], check=True)
                print(f"✓ {module} 安装成功")
            except subprocess.CalledProcessError:
                print(f"✗ {module} 安装失败，请手动安装")
                return False

    return True


def create_config_file():
    """创建配置文件，允许用户在不修改源代码的情况下更改API密钥"""
    config_file = "translator_config.py"

    if os.path.exists(config_file):
        overwrite = input(f"{config_file} 已存在，是否覆盖? (y/n): ").lower() == 'y'
        if not overwrite:
            print(f"将使用现有的 {config_file}")
            return

    with open(config_file, "w", encoding="utf-8") as f:
        f.write("""# 多语种实时翻译系统配置文件
# 在此处设置您的API密钥信息

# 讯飞API密钥 - 机器翻译和语音合成
APP_ID = "86c79fb7"
API_KEY = "f4369644e37eddd43adfe436e7904cf1"
API_SECRET = "MDY3ZGFkYWEyZDBiOTJkOGIyOTllOWMz"

# 讯飞API密钥 - 语音识别
ASR_APP_ID = "86c79fb7"
ASR_API_KEY = "acf74303ddb1af7196de01aadd232feb"
""")
    print(f"✓ 已创建配置文件: {config_file}")


def create_launcher_script():
    """创建启动脚本，用于打包"""
    launcher_file = "translator_launcher.py"

    with open(launcher_file, "w", encoding="utf-8") as f:
        f.write("""# 多语种实时翻译系统启动器
import os
import sys
import traceback

# 尝试导入配置
try:
    from translator_config import APP_ID, API_KEY, API_SECRET, ASR_APP_ID, ASR_API_KEY
except ImportError:
    # 使用默认配置
    APP_ID = "86c79fb7"
    API_KEY = "f4369644e37eddd43adfe436e7904cf1"
    API_SECRET = "MDY3ZGFkYWEyZDBiOTJkOGIyOTllOWMz"
    ASR_APP_ID = "86c79fb7"
    ASR_API_KEY = "acf74303ddb1af7196de01aadd232feb"

# 确保当前目录在路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

def main():
    try:
        # 导入主程序
        from main_translator import RealtimeTranslator

        # 创建并运行翻译系统
        translator = RealtimeTranslator(ASR_APP_ID, ASR_API_KEY, APP_ID, API_KEY, API_SECRET)
        translator.run()

    except Exception as e:
        error_msg = f"启动失败: {str(e)}\\n{traceback.format_exc()}"
        print(error_msg)

        # 显示错误窗口
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("启动错误", error_msg)
            root.destroy()
        except:
            # 如果tkinter无法显示错误，至少将错误保存到文件
            with open("translator_error.log", "w") as f:
                f.write(error_msg)

if __name__ == "__main__":
    main()
""")
    print(f"✓ 已创建启动脚本: {launcher_file}")
    return launcher_file


def build_executable(launcher_script):
    """使用PyInstaller构建可执行文件"""
    print("\n开始构建可执行文件...")

    # 创建spec文件
    spec_file = "translator.spec"
    with open(spec_file, "w", encoding="utf-8") as f:
        f.write(f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{launcher_script}'],
    pathex=[],
    binaries=[],
    datas=[('translator_config.py', '.')],
    hiddenimports=['pyaudio', 'websocket', 'queue', 'threading', 'tkinter', 'realtime_asr', 'realtime_tts', 'translation_module'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='多语种实时翻译系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
""")

    # 运行PyInstaller
    try:
        cmd = ["pyinstaller", "--clean", spec_file]
        subprocess.run(cmd, check=True)
        print("✓ 可执行文件构建成功!")

        # 检查输出文件
        exe_path = os.path.join("dist", "多语种实时翻译系统.exe")
        if os.path.exists(exe_path):
            print(f"\n可执行文件位于: {os.path.abspath(exe_path)}")
            print("\n您可以复制此文件到任何Windows电脑上直接运行!")
        else:
            print("✗ 找不到生成的可执行文件，请检查构建日志。")

    except subprocess.CalledProcessError:
        print("✗ 构建过程中出现错误，请检查PyInstaller输出。")
        return False

    return True


def main():
    print("=" * 60)
    print("     多语种实时翻译系统 - EXE打包工具")
    print("=" * 60)

    # 检查PyInstaller
    if not check_pyinstaller():
        print("\n请手动安装PyInstaller后再运行此脚本:")
        print("pip install pyinstaller")
        return

    # 检查必要模块
    if not check_required_modules():
        print("\n请确保所有必要的模块都已安装后再运行此脚本。")
        return

    # 创建配置文件
    create_config_file()

    # 创建启动脚本
    launcher_script = create_launcher_script()

    # 构建可执行文件
    if build_executable(launcher_script):
        # 清理临时文件
        try:
            if os.path.exists("build"):
                shutil.rmtree("build")
            os.remove("translator.spec")
            print("\n✓ 已清理临时文件")
        except:
            print("\n清理临时文件时出错，请手动删除build目录和spec文件。")

        print("\n=" * 60)
        print("  打包完成! 您可以在dist目录中找到可执行文件。")
        print("=" * 60)


if __name__ == "__main__":
    main()