import sys
import time
import subprocess
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- CONFIGURATION ---
ENABLE_HOT_RELOAD = False # Set to False to disable auto-reloading
# ---------------------

class RestartHandler(FileSystemEventHandler):
    def __init__(self, script_path):
        self.script_path = script_path
        self.process = None
        self.last_restart_time = 0
        self.debounce_interval = 1.0 # 1 second debounce
        self.pending_changes = set()  # 待处理的变更文件
        self.restart_scheduled = False  # 是否有待处理的重启
        self.start_process()

    def build_vue(self):
        """构建 Vue 前端项目"""
        web_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        dist_path = os.path.join(web_path, "dist")
        try:
            print("[HotReload] 📦 正在构建 Vue 前端...")
            
            # 尝试查找 npm
            npm_path = None
            # 方法1: 尝试使用 npm.cmd (Windows)
            try:
                result = subprocess.run(["where", "npm.cmd"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    npm_path = result.stdout.strip().split('\n')[0]
                    print(f"[HotReload] 找到 npm.cmd: {npm_path}")
            except: pass
            
            # 方法2: 尝试使用 npm (Windows PowerShell/CMD)
            if not npm_path:
                try:
                    result = subprocess.run(["where", "npm"], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and result.stdout.strip():
                        npm_path = result.stdout.strip().split('\n')[0]
                        print(f"[HotReload] 找到 npm: {npm_path}")
                except: pass
            
            # 方法3: 检查常见路径
            if not npm_path:
                common_paths = [
                    os.path.expandvars("%APPDATA%\\npm\\npm.cmd"),
                    os.path.expandvars("%APPDATA%\\npm\\npm"),
                    "C:\\Program Files\\nodejs\\npm.cmd",
                    "C:\\Program Files (x86)\\nodejs\\npm.cmd",
                ]
                for path in common_paths:
                    if os.path.exists(path):
                        npm_path = path
                        print(f"[HotReload] 在常见路径找到 npm: {npm_path}")
                        break
            
            if not npm_path:
                print("[HotReload] ❌ 未找到 npm，请安装 Node.js")
                print("[HotReload] 💡 下载地址: https://nodejs.org/")
                return False
            
            # 运行构建
            result = subprocess.run(
                [npm_path, "run", "build"],
                cwd=web_path,
                timeout=120
            )
            
            if result.returncode == 0:
                print("[HotReload] ✅ Vue 构建成功")
                if os.path.exists(dist_path):
                    print(f"[HotReload] 📁 构建输出目录: {dist_path}")
                else:
                    print(f"[HotReload] ⚠️ 警告: 构建目录不存在")
                return True
            else:
                print(f"[HotReload] ❌ Vue 构建失败 (返回码: {result.returncode})")
                return False
        except subprocess.TimeoutExpired:
            print("[HotReload] ❌ Vue 构建超时 (2分钟)")
            return False
        except FileNotFoundError:
            print("[HotReload] ❌ 未找到 npm，请安装 Node.js")
            return False
        except Exception as e:
            print(f"[HotReload] ⚠️ 构建异常: {e}")
            return False

    def start_process(self):
        # 再次检查，防止并发
        if self.process and self.process.poll() is None:
            self.stop_process_tree()
        
        # 先构建 Vue
        self.build_vue()
        
        print(f"[HotReload] 🚀 正在启动 {self.script_path}...")
        # Use python from current environment
        self.process = subprocess.Popen([sys.executable, self.script_path])

    def on_any_event(self, event):
        # 0. Global Switch
        if not ENABLE_HOT_RELOAD:
            return

        # Filter for file types (including Vue files)
        valid_ext = ('.py', '.qss', '.json', '.vue', '.js', '.ts')
        if not event.src_path.endswith(valid_ext):
            return
            
        # Ignore some directories
        # IGNORE WEB DIRECTORY: Prevent frontend changes from triggering backend restarts
        # Frontend dev should be handled by `npm run dev` (Vite) or manual build.
        if '__pycache__' in event.src_path or '.git' in event.src_path or 'node_modules' in event.src_path or 'dist' in event.src_path or 'web' in event.src_path:
            return

        current_time = time.time()
        
        # 添加到待处理变更
        self.pending_changes.add(os.path.basename(event.src_path))
        
        # 如果已经有待处理的重启，直接返回
        if self.restart_scheduled:
            return
            
        # 检查是否在防抖时间内（3秒）
        if current_time - self.last_restart_time < 3.0:
            # 标记需要重启，但不立即执行
            self.restart_scheduled = True
            # 安排延迟重启
            def delayed_restart():
                wait_time = 3.0 - (current_time - self.last_restart_time)
                if wait_time > 0:
                    time.sleep(wait_time)
                self._do_restart()
                self.restart_scheduled = False
                self.pending_changes.clear()
            threading.Thread(target=delayed_restart, daemon=True).start()
            return
        
        self._do_restart()
    
    def _do_restart(self):
        """执行重启操作"""
        changes = ", ".join(list(self.pending_changes)[:5])
        if len(self.pending_changes) > 5:
            changes += f" ... (+{len(self.pending_changes) - 5} 个)"
        print(f"\n[HotReload] 🔄 检测到文件变更: {changes}")
        
        self.last_restart_time = time.time()
        
        # 确保完全杀死旧进程后再启动
        if self.process:
            self.stop_process_tree()
            time.sleep(0.5)
            
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
