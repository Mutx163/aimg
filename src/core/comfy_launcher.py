import socket
import subprocess
import os
import time
from PyQt6.QtCore import QSettings

class ComfyLauncher:
    @staticmethod
    def is_port_open(host, port):
        """检查端口是否开放 (即服务是否在运行)"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect((host, int(port)))
            s.shutdown(socket.SHUT_RDWR)
            return True
        except:
            return False
        finally:
            s.close()

    @staticmethod
    def start_comfy(run_path):
        """启动 ComfyUI"""
        if not run_path or not os.path.exists(run_path):
            print(f"[Launcher] 错误: 启动路径不存在: {run_path}")
            return False
        
        try:
            working_dir = os.path.dirname(run_path)
            # 使用 start 命令在独立窗口启动
            # start "Title" /D "cwd" "exe"
            cmd = f'start "ComfyUI Console" /D "{working_dir}" "{run_path}"'
            
            # 关键：使用 CREATE_NEW_CONSOLE (0x10) | CREATE_NEW_PROCESS_GROUP (0x200)
            # 加上 CREATE_BREAKAWAY_FROM_JOB (0x01000000) 以逃离 VSCode/调试器的 Job Object 控制
            flags = 0x00000010 | 0x00000200 | 0x01000000
            
            subprocess.Popen(cmd, shell=True, creationflags=flags)
            print(f"[Launcher] 已尝试启动 (Job Breakaway): {run_path}")
            return True
        except Exception as e:
            print(f"[Launcher] 启动失败: {e}")
            return False

    @staticmethod
    def check_window_exists(title):
        """检查是否存在指定标题的窗口 (Windows Only)"""
        try:
            # tasklist /FI "WINDOWTITLE eq Title" /FO CSV /NH
            cmd = ['tasklist', '/FI', f'WINDOWTITLE eq {title}', '/FO', 'CSV', '/NH']
            # 使用 CREATE_NO_WINDOW 避免 tasklist 闪黑框
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
            if result.returncode != 0:
                # 访问受限或命令失败时，不应阻止自动启动
                return False
            # 如果没找到，输出通常包含 "INFO: No tasks..." 或者为空
            if "INFO:" in result.stdout or "ERROR:" in result.stdout or not result.stdout.strip():
                return False
            # 如果找到了，输出会包含进程信息
            return True
        except:
            return False

    @staticmethod
    def ensure_comfy_running():
        """主入口：检查设置并按需启动"""
        settings = QSettings("ComfyUIImageManager", "Settings")
        address = settings.value("comfy_address", "127.0.0.1:8188")
        run_path = settings.value("comfy_run_path", "")
        
        # 解析 host:port
        if ":" in address:
            host, port = address.split(":", 1)
        else:
            host, port = address, "8188"
            
        print(f"[Launcher] 检查 ComfyUI ({host}:{port})...")
        
        # 1. 检查端口是否已占用 (ComfyUI 已完全启动)
        if ComfyLauncher.is_port_open(host, port):
            print(f"[Launcher] ComfyUI 已在运行 (端口畅通)")
            return

        # 2. 检查是否有正在启动中的窗口 (防止在启动过程中重复触发)
        if ComfyLauncher.check_window_exists("ComfyUI Console"):
            print(f"[Launcher] 检测到 ComfyUI 控制台窗口已存在 (可能正在启动中)，等待端口就绪...")
            # 给已存在的窗口一点时间启动服务
            for _ in range(6):
                time.sleep(0.5)
                if ComfyLauncher.is_port_open(host, port):
                    print(f"[Launcher] ComfyUI 已在运行 (端口畅通)")
                    return
            print(f"[Launcher] 控制台窗口存在但端口未就绪，尝试重新启动...")
            
        if not run_path:
            print(f"[Launcher] 未在设置中配置 ComfyUI 启动路径，跳过自动启动")
            return
            
        print(f"[Launcher] ComfyUI 未运行，尝试启动...")
        if ComfyLauncher.start_comfy(run_path):
            # 可选：等待几秒让它初始化，但通常不需要阻塞 UI
            pass
