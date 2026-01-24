import json
import uuid
from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QByteArray
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

class ComfyClient(QObject):
    """
    ComfyUI 远程通讯客户端
    负责通过 API 提交工作流并监听实时进度
    """
    status_changed = pyqtSignal(str) # 队列状态或错误信息
    progress_updated = pyqtSignal(int, int) # 当前步数, 总步数
    execution_start = pyqtSignal(str, str) # 节点ID, 节点类型/名称
    execution_done = pyqtSignal(str) # 执行完成的图片路径(或ID)
    prompt_submitted = pyqtSignal(str) # 任务提交成功，携带 prompt_id

    def __init__(self, server_address="127.0.0.1:8188"):
        super().__init__()
        self.server_address = server_address
        self.client_id = str(uuid.uuid4())
        
        self.ws = QWebSocket()
        self.ws.connected.connect(self._on_connected)
        self.ws.textMessageReceived.connect(self._on_message)
        self.ws.errorOccurred.connect(self._on_error)
        self.current_prompt_graph = {} # 存储当前执行的图
        
        self.nam = QNetworkAccessManager() # 用于非阻塞 HTTP 请求
        
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

    def send_prompt(self, workflow_json: Dict[str, Any]) -> None:
        """
        向 ComfyUI 发送提示词任务 (异步)
        workflow_json: 完整的工作流字典
        """
        self.current_prompt_graph = workflow_json # 保存当前图用于名称解析
        p = {"prompt": workflow_json, "client_id": self.client_id}
        
        url = QUrl(f"http://{self.server_address}/prompt")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        
        json_data = json.dumps(p).encode('utf-8')
        reply = self.nam.post(request, QByteArray(json_data))
        reply.finished.connect(lambda: self._handle_prompt_response(reply))
        
        # 在发送前检查队列状态，方便调试 (异步)
        self.check_system_stats()

    def _handle_prompt_response(self, reply: QNetworkReply) -> None:
        """处理发送任务的响应"""
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = json.loads(bytes(reply.readAll()).decode('utf-8'))
                prompt_id = data.get("prompt_id")
                print(f"[Comfy] 任务提交成功, Prompt ID: {prompt_id}")
                if prompt_id:
                    self.prompt_submitted.emit(prompt_id)
            else:
                err_msg = reply.errorString()
                print(f"[Comfy] 任务提交失败: {err_msg}")
                self.status_changed.emit(f"提交失败: {err_msg}")
        except Exception as e:
            print(f"[Comfy] 响应解析失败: {e}")
            self.status_changed.emit(f"响应解析错误: {e}")
        finally:
            reply.deleteLater()

    def get_history(self, prompt_id: str) -> None:
        """获取任务执行历史（异步，暂未完全实现信号回调，仅用于兼容性）"""
        # 注意：如果外部通过返回值调用此方法，将会失败。
        # 鉴于代码审查显示此方法未被使用，我们暂时保留异步实现但不处理返回值。
        print(f"[Comfy] Warning: get_history called but async return not implemented.")
        # 如果将来需要，应添加 history_received 信号

    def check_system_stats(self) -> None:
        """检查系统状态（异步）"""
        url = QUrl(f"http://{self.server_address}/queue")
        reply = self.nam.get(QNetworkRequest(url))
        reply.finished.connect(lambda: self._handle_stats_response(reply))

    def _handle_stats_response(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                queue_data = json.loads(bytes(reply.readAll()).decode('utf-8'))
                pending = queue_data.get('queue_pending', [])
                running = queue_data.get('queue_running', [])
                print(f"[Comfy] 当前队列: Running={len(running)}, Pending={len(pending)}")
                # 可以在这里 emit 信号更新 UI
            else:
                print(f"[Comfy] 获取队列失败: {reply.errorString()}")
        except Exception as e:
            print(f"[Comfy] 队列响应解析失败: {e}")
        finally:
            reply.deleteLater()

    def queue_current_prompt(self, workflow: Optional[Dict[str, Any]] = None) -> None:
        """
        重新提交workflow（修改随机种子）
        如果提供了workflow参数，直接使用；否则从 /history 获取最近的workflow
        """
        if workflow:
            # 直接使用提供的workflow
            print("[Comfy] 使用提供的workflow")
            self.status_changed.emit("正在提交workflow...")
            modified_workflow = self._randomize_seeds(workflow)
            self.send_prompt(modified_workflow)
        else:
            # 从历史记录获取
            print("[Comfy] queue_current_prompt: 正在获取最近的工作流...")
            self.status_changed.emit("正在获取最近的工作流...")
        
            # 启动异步请求获取历史记录
            self._fetch_latest_workflow()
    
    def _fetch_latest_workflow(self) -> None:
        """从 /history 获取最近执行的workflow（异步）"""
        url = QUrl(f"http://{self.server_address}/history")
        reply = self.nam.get(QNetworkRequest(url))
        reply.finished.connect(lambda: self._handle_history_response(reply))
    
    def _handle_history_response(self, reply: QNetworkReply) -> None:
        """处理历史记录响应"""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                err_msg = reply.errorString()
                print(f"[Comfy] 获取历史失败: {err_msg}")
                self.status_changed.emit(f"获取历史失败: {err_msg}")
                return
            
            data = json.loads(bytes(reply.readAll()).decode('utf-8'))
            
            # history 返回格式: { "prompt_id_1": {...}, "prompt_id_2": {...}, ... }
            # 按时间排序找到最新的
            if not data:
                print("[Comfy] 没有历史记录，请先在ComfyUI执行一次生成")
                self.status_changed.emit("没有历史记录，请先在ComfyUI执行一次生成")
                return
            
            # 获取最新的prompt_id (假设dict已按时间排序，或者我们取第一个)
            latest_prompt_id = list(data.keys())[0]
            latest_entry = data[latest_prompt_id]
            
            # 提取workflow定义
            # ComfyUI /history 的结构比较复杂，prompt字段可能不是完整workflow
            prompt_data = latest_entry.get("prompt")
            
            # 调试：打印所有可用字段
            print(f"[Comfy Debug] latest_entry 的键: {latest_entry.keys()}")
            
            # 尝试从不同位置获取workflow
            workflow = None
            
            # 方法1: 检查meta字段是否包含workflow
            if "meta" in latest_entry:
                meta = latest_entry["meta"]
                print(f"[Comfy Debug] meta字段内容: {meta}")
                if isinstance(meta, dict) and "workflow_api" in meta:
                    workflow = meta["workflow_api"]
                    print("[Comfy] 从meta.workflow_api获取到workflow")
            
            # 方法2: 如果prompt是字典格式，直接使用
            if workflow is None and isinstance(prompt_data, dict):
                workflow = prompt_data
                print("[Comfy] 使用prompt字段作为workflow")
            
            # 方法3: prompt可能不是我们需要的，可能需要从outputs重建
            # 但这太复杂了，让我们用更简单的方法
            
            if workflow is None:
                print(f"[Comfy] 无法从历史记录获取完整workflow")
                print(f"[Comfy] prompt类型: {type(prompt_data)}, 内容: {prompt_data}")
                self.status_changed.emit("无法获取完整workflow，请在ComfyUI中保存为API格式")
                return
            
            print(f"[Comfy] 成功获取workflow (prompt_id: {latest_prompt_id})")
            self.status_changed.emit("已获取workflow，正在提交...")
            
            # 修改随机种子避免生成相同图片
            modified_workflow = self._randomize_seeds(workflow)
            
            # 提交到队列
            self.send_prompt(modified_workflow)
            
        except Exception as e:
            import traceback
            print(f"[Comfy] 处理历史记录失败: {e}")
            print(f"[Comfy Debug] 完整错误: {traceback.format_exc()}")
            self.status_changed.emit(f"处理历史记录失败: {e}")
        finally:
            reply.deleteLater()
    
    def _randomize_seeds(self, workflow: Any) -> Any:
        """
        遍历workflow，将所有KSampler节点的seed随机化
        返回修改后的workflow副本
        支持字典格式和列表格式的workflow
        """
        import random
        
        # 深拷贝
        workflow_copy = json.loads(json.dumps(workflow))
        
        # ComfyUI的workflow可能是两种格式：
        # 1. 字典格式: {node_id: {class_type: ..., inputs: {...}}, ...}
        # 2. 列表格式: [{id: ..., class_type: ..., inputs: {...}}, ...]
        
        if isinstance(workflow_copy, dict):
            # 字典格式
            for node_id, node_data in workflow_copy.items():
                self._randomize_node_seed(node_id, node_data)
        elif isinstance(workflow_copy, list):
            # 列表格式
            for node_data in workflow_copy:
                node_id = node_data.get("id", "unknown")
                self._randomize_node_seed(node_id, node_data)
        else:
            print(f"[Comfy] 警告: 未知的workflow格式: {type(workflow_copy)}")
        
        return workflow_copy
    
    def _randomize_node_seed(self, node_id: Any, node_data: Dict[str, Any]) -> None:
        """随机化单个节点的seed"""
        import random
        class_type = node_data.get("class_type", "")
        # 常见的采样器节点类型
        if "sampler" in class_type.lower() or class_type == "KSampler":
            inputs = node_data.get("inputs", {})
            if "seed" in inputs:
                # 生成新的随机种子（ComfyUI通常使用较大的整数）
                inputs["seed"] = random.randint(1, 2**32 - 1)
                print(f"[Comfy] 已随机化节点 {node_id} ({class_type}) 的seed")

