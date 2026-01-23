import json
import uuid
import urllib.request
from PyQt6.QtCore import QObject, pyqtSignal, QUrl
from PyQt6.QtWebSockets import QWebSocket

class ComfyClient(QObject):
    """
    ComfyUI 远程通讯客户端
    负责通过 API 提交工作流并监听实时进度
    """
    status_changed = pyqtSignal(str) # 队列状态或错误信息
    progress_updated = pyqtSignal(int, int) # 当前步数, 总步数
    execution_start = pyqtSignal(str, str) # 节点ID, 节点类型/名称
    execution_done = pyqtSignal(str) # 执行完成的图片路径(或ID)

    def __init__(self, server_address="127.0.0.1:8188"):
        super().__init__()
        self.server_address = server_address
        self.client_id = str(uuid.uuid4())
        
        self.ws = QWebSocket()
        self.ws.connected.connect(self._on_connected)
        self.ws.textMessageReceived.connect(self._on_message)
        self.ws.errorOccurred.connect(self._on_error)
        self.current_prompt_graph = {} # 存储当前执行的图
        
    def connect_server(self):
        """连接 WebSocket 监听状态"""
        ws_url = f"ws://{self.server_address}/ws?clientId={self.client_id}"
        self.ws.open(QUrl(ws_url))

    def _on_connected(self):
        print(f"[Comfy] WebSocket 已连接: {self.server_address}")
        self.status_changed.emit("ComfyUI 已连接")

    def _on_error(self, error):
        print(f"[Comfy] WebSocket 错误: {error}")
        self.status_changed.emit(f"连接失败: {error}")

    def _on_message(self, message):
        """处理 WebSocket 消息"""
        """处理 WebSocket 消息"""
        try:
            # print(f"[Comfy WS Raw] {message}") # 调试用：查看所有原始消息
            data = json.loads(message)
            msg_type = data.get("type")
            
            # 打印非心跳消息以调试
            if msg_type not in ['crystools.monitor', 'status']:
                print(f"[Comfy WS] Type: {msg_type}, Data: {data}")
            
            if msg_type == "status":
                queue_remaining = data["data"]["status"]["exec_info"]["queue_remaining"]
                if queue_remaining > 0:
                    self.status_changed.emit(f"队列待处理: {queue_remaining}")
            
            elif msg_type == "executing":
                node_id = data["data"]["node"]
                if node_id:
                    node_type = "Unknown"
                    if node_id in self.current_prompt_graph:
                        node_type = self.current_prompt_graph[node_id].get('class_type', 'Unknown')
                    self.execution_start.emit(node_id, node_type)
                else:
                    self.status_changed.emit("所有任务已完成")
                    self.execution_done.emit("")
            
            elif msg_type == "progress":
                value = data["data"]["value"]
                max_val = data["data"]["max"]
                self.progress_updated.emit(value, max_val)
                
        except Exception as e:
            print(f"[Comfy] 消息处理异常: {e}")

    def send_prompt(self, workflow_json):
        """
        向 ComfyUI 发送提示词任务
        workflow_json: 完整的工作流字典
        """
        try:
            self.current_prompt_graph = workflow_json # 保存当前图用于名称解析
            p = {"prompt": workflow_json, "client_id": self.client_id}
            data = json.dumps(p).encode('utf-8')
            
            req = urllib.request.Request(f"http://{self.server_address}/prompt", data=data)
            req.add_header('Content-Type', 'application/json')
            
            # 在发送前检查队列状态，方便调试
            self.check_system_stats()
            
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                prompt_id = result.get("prompt_id")
                print(f"[Comfy] 任务提交成功, Prompt ID: {prompt_id}")
                return prompt_id
        except Exception as e:
            print(f"[Comfy] 任务提交失败: {e}")
            self.status_changed.emit(f"生成失败: {e}")
            return None

    def get_history(self, prompt_id):
        """获取任务执行历史（用于解析生成结果）"""
        try:
            with urllib.request.urlopen(f"http://{self.server_address}/history/{prompt_id}") as response:
                return json.loads(response.read().decode('utf-8'))
        except:
            return None

    def check_system_stats(self):
        """检查系统状态（队列等）"""
        try:
            with urllib.request.urlopen(f"http://{self.server_address}/queue") as response:
                queue_data = json.loads(response.read().decode('utf-8'))
                pending = queue_data.get('queue_pending', [])
                running = queue_data.get('queue_running', [])
                print(f"[Comfy] 当前队列: Running={len(running)}, Pending={len(pending)}")
                return len(running), len(pending)
        except Exception as e:
            print(f"[Comfy] 获取队列失败: {e}")
            return 0, 0
