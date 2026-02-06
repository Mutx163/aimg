import sys
import time
import threading
from PyQt6.QtWidgets import QApplication


def main():
    start_time = time.time()
    print("[System] Startup begin...")

    app = QApplication(sys.argv)
    app.setApplicationName("AI Image Viewer")

    from src.core.comfy_launcher import ComfyLauncher
    from src.ui.main_window import MainWindow

    # Start ComfyUI bootstrap in background to avoid blocking first paint.
    threading.Thread(target=ComfyLauncher.ensure_comfy_running, daemon=True).start()

    window = MainWindow()
    window.show()

    end_time = time.time()
    print(f"[System] Window shown in {end_time - start_time:.3f}s")

    ret = app.exec()
    sys.exit(ret)


if __name__ == "__main__":
    main()
