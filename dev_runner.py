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
        # 再次检查，防止并发
        if self.process and self.process.poll() is None:
            self.stop_process_tree()
        
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
        # 增加防抖时间到 1.5s，避免某些编辑器连续保存触发多次
        if current_time - self.last_restart_time < 2.0:
            return

        self.last_restart_time = current_time
        print(f"\n[HotReload] 🔄 检测到文件变更: {os.path.basename(event.src_path)}")
        
        # 确保完全杀死旧进程后再启动
        if self.process:
             # 双重保障：先尝试停止
             self.stop_process_tree()
             time.sleep(0.5) # 给一点时间让窗口消失
             
        self.start_process()

    def stop_process_tree(self):
        """专门提取的停止逻辑"""
        if not self.process: return
        try:
            pid = self.process.pid
            print(f"[HotReload] 🛑 正在清理旧进程 (PID: {pid})...")
            if sys.platform == 'win32':
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
            else:
                self.process.terminate()
                self.process.wait(timeout=1)
        except Exception as e:
            print(f"[HotReload] ⚠️ 清理进程异常: {e}")

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
