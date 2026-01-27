import sys
import os
import time
from PyQt6.QtWidgets import QApplication
from src.ui.main_window import MainWindow

def main():
    start_time = time.time()
    print(f"[System] 启动初始化开始...")
    
    app = QApplication(sys.argv)
    app.setApplicationName("AI Image Viewer")

    # 启动移动端 Web 服务 (自动后台运行)
    try:
        import subprocess, atexit, socket
        server_process = subprocess.Popen(
            [sys.executable, "server/app.py"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        atexit.register(server_process.terminate)
        local_ip = socket.gethostbyname(socket.gethostname())
        print(f"[System] 移动端服务已自动启动: http://{local_ip}:8000")
    except Exception as e:
        print(f"[System] 无法启动移动端服务: {e}")
    
    # 确保 assets 目录存在，后续用于加载 styles
    # if os.path.exists("assets/style.qss"):
    #     with open("assets/style.qss", "r") as f:
    #         app.setStyleSheet(f.read())
            
    window = MainWindow()
    window.show()
    
    end_time = time.time()
    print(f"[System] 界面显示完成，耗时: {end_time - start_time:.3f} 秒")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
