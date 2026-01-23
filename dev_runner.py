import sys
import time
import subprocess
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class RestartHandler(FileSystemEventHandler):
    def __init__(self, script_path):
        self.script_path = script_path
        self.process = None
        self.last_restart_time = 0
        self.debounce_interval = 1.0 # 1 second debounce
        self.start_process()

    def start_process(self):
        if self.process:
            try:
                print(f"[HotReload] 🛑 正在停止旧进程 (PID: {self.process.pid})...")
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                print("[HotReload] ⚠️ 进程未响应，强制终止...")
                self.process.kill()
            except Exception as e:
                print(f"[HotReload] 错误: {e}")
        
        print(f"[HotReload] 🚀 正在启动 {self.script_path}...")
        # Use python from current environment
        self.process = subprocess.Popen([sys.executable, self.script_path])

    def on_any_event(self, event):
        # Filter for file types
        valid_ext = ('.py', '.qss', '.json')
        if not event.src_path.endswith(valid_ext):
            return
            
        # Ignore some directories
        if '__pycache__' in event.src_path or '.git' in event.src_path:
            return

        current_time = time.time()
        if current_time - self.last_restart_time < self.debounce_interval:
            return

        self.last_restart_time = current_time
        print(f"\n[HotReload] 🔄 检测到文件变更: {os.path.basename(event.src_path)}")
        self.start_process()

if __name__ == "__main__":
    # Ensure we are in the script's directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    path = "."
    script = "main.py"
    
    print(f"[HotReload] 🔥 开发热重载模式已启动")
    print(f"[HotReload] 📂 监控目录: {os.path.abspath(path)}")
    print(f"[HotReload] 📝 目标脚本: {script}")
    
    event_handler = RestartHandler(script)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[HotReload] 👋 正在退出...")
        if event_handler.process:
            event_handler.process.terminate()
        observer.stop()
    observer.join()
