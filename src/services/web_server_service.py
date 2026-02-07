import os
import sys
import secrets
from PyQt6.QtCore import QObject, pyqtSignal, QProcess, QProcessEnvironment, QSettings
from src.utils.network import get_free_port, get_local_ip

class WebServerService(QObject):
    """
    负责管理 Web 服务进程的生命周期。
    使用 QProcess 启动，支持动态端口和日志捕获。
    """
    service_ready = pyqtSignal(str) # 服务启动成功，携带 URL
    log_message = pyqtSignal(str)   # 服务日志输出
    service_stopped = pyqtSignal()  # 服务已停止

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.port = 8000
        self.host = "127.0.0.1"
        self.is_ready = False
        self.remote_auth_enabled = False
        self.remote_access_code = ""

    def _is_loopback_host(self, host: str) -> bool:
        host = str(host or "").strip().lower()
        return host in ("127.0.0.1", "localhost", "::1")

    def _build_access_code(self, configured_code: str) -> str:
        code = str(configured_code or "").strip().upper()
        if code:
            return code
        alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        return "".join(secrets.choice(alphabet) for _ in range(6))

    def start_server(self):
        """启动 Web 服务"""
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.is_ready = False

        try:
            self.port = get_free_port(8000, 9000)
        except Exception as e:
            self.log_message.emit(f"[Error] 无法获取可用端口: {e}")
            return

        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        
        # Read Comfy Settings
        settings = QSettings("ComfyUIImageManager", "Settings")
        comfy_address = settings.value("comfy_address", "127.0.0.1:8188")
        self.host = settings.value("web_bind", "127.0.0.1")
        self.remote_auth_enabled = not self._is_loopback_host(self.host)
        self.remote_access_code = ""
        if self.remote_auth_enabled:
            self.remote_access_code = self._build_access_code(settings.value("web_auth_code", ""))

        if ":" in comfy_address:
            host, port = comfy_address.split(":", 1)
        else:
            host, port = comfy_address, "8188"

        # 使用 -m server.app 方式启动，确保 imports 正常
        # 传递 --port 参数 和 --no-scan (避免双重扫描导致锁死)
        args = [
            "-m", "server.app", 
            "--host", str(self.host),
            "--port", str(self.port), 
            "--no-scan",
            "--comfy-host", host,
            "--comfy-port", port
        ]
        if self.remote_auth_enabled:
            args.extend(["--remote-access-code", self.remote_access_code])
        self.process.setArguments(args)
        
        # 设置 PYTHONPATH，确保子进程能找到 src
        env = QProcessEnvironment.systemEnvironment()
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env.insert("PYTHONPATH", project_root)
        env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(env)
        
        # 设置工作目录为项目根目录
        self.process.setWorkingDirectory(project_root)

        # 连接信号
        self.process.readyReadStandardOutput.connect(self._handle_stdout)
        self.process.readyReadStandardError.connect(self._handle_stderr)
        self.process.started.connect(self._on_started)
        self.process.finished.connect(self._on_finished)

        self.process.start()

    def stop_server(self):
        """停止 Web 服务"""
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(2000):
                self.process.kill()

    def _check_startup_success(self, data):
        """检查日志中是否包含启动成功的标志"""
        if self.is_ready: return

        if "Application startup complete" in data or "Uvicorn running on" in data:
             self.is_ready = True
             if str(self.host) in ("127.0.0.1", "localhost"):
                 url = f"http://127.0.0.1:{self.port}"
             else:
                 local_ip = get_local_ip()
                 url = f"http://{local_ip}:{self.port}"
                 if self.remote_auth_enabled:
                     self.log_message.emit(f"[Auth] 局域网访问已启用，验证码: {self.remote_access_code}")
             self.service_ready.emit(url)

    def _filter_logs(self, message):
        """过滤掉高频且无用的心跳日志和元数据/缩略图日志，以及常规访问日志"""
        # Filter specific endpoints
        if "/api/comfy/status" in message: return False
        if "/api/metadata" in message: return False
        if "/api/image/thumb" in message: return False
        if "/api/image/raw" in message: return False
        
        # Filter standard access logs (e.g., INFO: 127.0.0.1:12345 - "GET ...")
        # Keep startup logs (Started server process, Waiting for app, etc.)
        if "GET /" in message or "POST /" in message:
             # Allow startup/shutdown logs or critical ones?
             # Uvicorn standard access log format usually contains method and path
             return False
             
        return True

    def _handle_stdout(self):
        data = self.process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        if data:
            self._check_startup_success(data)
            msg = data.strip()
            if self._filter_logs(msg):
                self.log_message.emit(msg)

    def _handle_stderr(self):
        data = self.process.readAllStandardError().data().decode('utf-8', errors='ignore')
        if data:
            self._check_startup_success(data)
            msg = data.strip()
            # Uvicorn 的访问日志通常输出到 stderr
            if self._filter_logs(msg):
                self.log_message.emit(f"[Server Log] {msg}")

    def _on_started(self):
        self.log_message.emit(f"[System] Web 服务进程已启动 (PID: {self.process.processId()})")

    def _on_finished(self, exit_code, exit_status):
        self.is_ready = False
        self.log_message.emit(f"[System] Web 服务已停止 (Code: {exit_code})")
        self.service_stopped.emit()
