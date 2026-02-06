import sys
import os
import time
from PyQt6.QtWidgets import QApplication
from src.ui.main_window import MainWindow
from src.services.web_server_service import WebServerService

def main():
    start_time = time.time()
    print(f"[System] 启动初始化开始...")
    
    app = QApplication(sys.argv)
    app.setApplicationName("AI Image Viewer")

    from src.core.comfy_launcher import ComfyLauncher
    
    # 尝试自动启动 ComfyUI
    ComfyLauncher.ensure_comfy_running()

    # 启动移动端 Web 服务 (使用新的服务管理器)
    web_service = WebServerService()
    
    # 连接日志输出到控制台 (或者后续连接到 UI 日志面板)
    import webbrowser
    web_service.log_message.connect(lambda msg: print(f"{msg}"))
    
    def on_service_ready(url):
        local_url = f"http://127.0.0.1:{web_service.port}"
        print(f"[System] Web 服务已就绪:")
        print(f"  - 本机访问: {local_url}")
        print(f"  - 局域网/手机访问: {url}")
        
        # 自动打开浏览器访问 Web 界面 (强制使用 localhost)
        local_url = f"http://127.0.0.1:{web_service.port}"
        webbrowser.open(local_url)
        
    web_service.service_ready.connect(on_service_ready)
    
    try:
        web_service.start_server()
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
    
    ret = app.exec()
    
    # 退出时确保服务停止
    web_service.stop_server()
    sys.exit(ret)

if __name__ == "__main__":
    main()