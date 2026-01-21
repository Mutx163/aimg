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
