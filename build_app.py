import os
import subprocess
import sys

def build():
    print("=== 开始打包 AI Image Viewer Pro ===")
    
    # 1. 检查并安装 pyinstaller
    try:
        import PyInstaller
        print("[Build] PyInstaller 已安装")
    except ImportError:
        print("[Build] 正在安装 PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. 准备打包命令
    # --onefile: 打包成单个 exe
    # --noconsole: 运行时不显示黑色控制台
    # --name: 指定生成的文件名
    # --add-data: 包含 src 目录 (Windows 语法使用分号 ;)
    # --hidden-import: 确保一些动态加载的模块被包含
    
    entry_point = "main.py"
    app_name = "AIImageViewerPro"
    
    # 注意：在 Windows 上使用 --add-data "src;src" 将整个源码包打入
    # 同时也包含默认的图标（如果有的话）
    
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        f"--name={app_name}",
        "--add-data=src;src",
        "--clean",
        entry_point
    ]
    
    print(f"[Build] 执行命令: {' '.join(cmd)}")
    
    try:
        subprocess.check_call(cmd)
        print("\n" + "="*30)
        print(f"🎉 打包成功！")
        print(f"生成的软件位于: {os.path.join(os.getcwd(), 'dist', app_name + '.exe')}")
        print("="*30)
    except subprocess.CalledProcessError as e:
        print(f"❌ 打包失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    build()
