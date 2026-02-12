import copy
import json
import uuid
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QByteArray, QTimer
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply, QAbstractSocket

class ComfyClient(QObject):
    """
    ComfyUI 远程通讯客户端
    负责通过 API 提交工作流并监听实时进度
    """
    status_changed = pyqtSignal(str) # 队列状态或错误信息
    progress_updated = pyqtSignal(int, int) # 当前步数, 总步数
    progress_detail_updated = pyqtSignal(dict) # 进度详情 (含 ETA)
    system_stats_updated = pyqtSignal(dict) # 系统资源状态 (显存/内存)
    execution_start = pyqtSignal(str, str) # 节点ID, 节点类型/名称
    execution_done = pyqtSignal(str) # 执行完成的图片路径(或ID)
    prompt_submitted = pyqtSignal(str) # 任务提交成功，携带 prompt_id
    prompt_submitted_with_context = pyqtSignal(str, dict) # (prompt_id, context)
    prompt_executed_images = pyqtSignal(str, list, dict) # (prompt_id, images, context)
    models_fetched = pyqtSignal(list) # 获取到可用模型列表
    
    # 队列管理信号
    queue_updated = pyqtSignal(dict) # 队列状态更新
    task_cancelled = pyqtSignal(str) # 任务已取消，携带prompt_id
    queue_cleared = pyqtSignal() # 队列已清空
    operation_failed = pyqtSignal(str) # 操作失败 (取消、清空等), 携带错误信息

    def __init__(self, server_address="127.0.0.1:8188"):
        super().__init__()
        self.server_address = server_address
        self.client_id = str(uuid.uuid4())
        
        self.ws = QWebSocket()
        self.ws.connected.connect(self._on_connected)
        self.ws.disconnected.connect(self._on_disconnected)
        self.ws.textMessageReceived.connect(self._on_message)
        self.ws.errorOccurred.connect(self._on_error)
        self.current_prompt_graph = {} # 存储当前执行的图
        self._prompt_context_by_id: Dict[str, Dict[str, Any]] = {}
        
        self.nam = QNetworkAccessManager() # 用于非阻塞 HTTP 请求
        self._system_stats_supported = True
        
        # 重连定时器
        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setInterval(3000) # 3秒重连一次
        self.reconnect_timer.timeout.connect(self.connect_server)
        self.system_stats_timer = QTimer(self)
        self.system_stats_timer.setInterval(2000)
        self.system_stats_timer.timeout.connect(self.get_system_stats)

    def connect_server(self):
        """连接 WebSocket 监听状态"""
        # 如果已经连接或正在连接，则跳过
        if self.ws.state() == QAbstractSocket.SocketState.ConnectedState:
            return
            
        ws_url = f"ws://{self.server_address}/ws?clientId={self.client_id}"
        self.ws.open(QUrl(ws_url))
    def _on_connected(self):
        print(f"[Comfy] WebSocket 已连接: {self.server_address}")
        self.status_changed.emit("ComfyUI 已连接")
        # 连接成功后停止重连并同步基础状态
        self.reconnect_timer.stop()
        if self._system_stats_supported and not self.system_stats_timer.isActive():
            self.system_stats_timer.start()
            self.get_system_stats()
        self.fetch_available_models()
        # 重启后尽快同步队列，便于主界面恢复进度展示
        QTimer.singleShot(100, self.get_queue)
    def _on_disconnected(self):
        print(f"[Comfy] WebSocket 连接断开")
        self.status_changed.emit("连接断开，正在重连...")
        if self.system_stats_timer.isActive():
            self.system_stats_timer.stop()
        if not self.reconnect_timer.isActive():
            self.reconnect_timer.start()

    def _on_error(self, error):
        print(f"[Comfy] WebSocket 错误: {error}")
        self.status_changed.emit(f"连接失败: {error}")
        # 发生错误时也尝试重连
        if self.system_stats_timer.isActive():
            self.system_stats_timer.stop()
        if not self.reconnect_timer.isActive():
            self.reconnect_timer.start()

    def _on_message(self, message):
        """处理 WebSocket 消息"""
        try:
            # print(f"[Comfy WS Raw] {message}") # 调试用：查看所有原始消息
            data = json.loads(message)
            msg_type = data.get("type")
            
            # 打印非心跳消息以调试
            if msg_type not in ['crystools.monitor', 'status', 'progress_state', 'progress', 'executing', 'executed']:
                print(f"[Comfy WS] Type: {msg_type}, Data: {data}")
            
            if msg_type == "status":
                queue_remaining = data["data"]["status"]["exec_info"]["queue_remaining"]
                
                # [Real-time] 检测队列余量变化
                if hasattr(self, "_last_queue_remaining"):
                    if queue_remaining != self._last_queue_remaining:
                        # 队列余量变化（可能有新任务或任务完成），立即刷新完整队列数据
                        self.get_queue()
                self._last_queue_remaining = queue_remaining
                
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
                    # [Real-time] node 为 None 表示当前 Prompt 整体执行完毕
                    self.status_changed.emit("所有任务已完成")
                    self.execution_done.emit("")
                    QTimer.singleShot(500, self.get_queue) # 稍作延迟确保后端状态已更新
            
            elif msg_type == "execution_error":
                # [Real-time] 执行报错也需要刷新队列（任务可能被强行中止）
                print(f"[Comfy] 采样过程中发生错误")
                self.get_queue()

            elif msg_type in ("progress", "progress_state"):
                progress_info = self._parse_progress_payload(data.get("data"))
                self.progress_detail_updated.emit(progress_info)
                self.progress_updated.emit(progress_info["value"], progress_info["max"])

            elif msg_type == "executed":
                payload = data.get("data", {}) if isinstance(data, dict) else {}
                prompt_id = str(payload.get("prompt_id") or "")
                output = payload.get("output") if isinstance(payload, dict) else None
                images = self._extract_images_from_output(output)
                if images:
                    context = self._prompt_context_by_id.get(prompt_id, {})
                    self.prompt_executed_images.emit(prompt_id, images, context)
                
        except Exception as e:
            print(f"[Comfy] 消息处理异常: {e}")

    def _extract_images_from_output(self, output: Any) -> List[Dict[str, Any]]:
        """从 executed.output 中提取 images 列表。"""
        images: List[Dict[str, Any]] = []
        if not isinstance(output, dict):
            return images

        direct_images = output.get("images")
        if isinstance(direct_images, list):
            for img in direct_images:
                if isinstance(img, dict):
                    images.append(img)
            return images

        for value in output.values():
            if isinstance(value, dict):
                nested = value.get("images")
                if isinstance(nested, list):
                    for img in nested:
                        if isinstance(img, dict):
                            images.append(img)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        nested = item.get("images")
                        if isinstance(nested, list):
                            for img in nested:
                                if isinstance(img, dict):
                                    images.append(img)
        return images

    def send_prompt(self, workflow_json: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> None:
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
        ctx = dict(context or {})
        reply.finished.connect(lambda: self._handle_prompt_response(reply, workflow_json, ctx))
        
        # 在发送前检查队列状态，方便调试 (异步)
        self.check_system_stats()

    def _handle_prompt_response(
        self,
        reply: QNetworkReply,
        workflow_json: Dict[str, Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """处理发送任务的响应"""
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = json.loads(bytes(reply.readAll()).decode('utf-8'))
                prompt_id = data.get("prompt_id")
                print(f"[Comfy] 任务提交成功, Prompt ID: {prompt_id}")
                if prompt_id:
                    self.prompt_submitted.emit(prompt_id)
                    ctx = dict(context or {})
                    self._prompt_context_by_id[str(prompt_id)] = ctx
                    self.prompt_submitted_with_context.emit(str(prompt_id), ctx)
            else:
                err_msg = reply.errorString()
                print(f"[Comfy] 任务提交失败: {err_msg}")
                
                # 尝试读取服务器返回的详细错误信息
                response_body = bytes(reply.readAll()).decode('utf-8')
                if response_body:
                    try:
                        error_data = json.loads(response_body)
                        if 'error' in error_data:
                            server_error = error_data['error']
                            print(f"[Comfy] 服务器错误详情: {server_error}")
                            
                            # 尝试提取具体的错误类型
                            if isinstance(server_error, dict):
                                error_type = server_error.get('type', '')
                                error_message = server_error.get('message', '')
                                error_details = server_error.get('details', '')
                                
                                print(f"[Comfy] 错误类型: {error_type}")
                                print(f"[Comfy] 错误消息: {error_message}")
                                if error_details:
                                    print(f"[Comfy] 错误详情: {error_details}")
                                    
                                self.status_changed.emit(f"提交失败: {error_message}")
                            else:
                                print(f"[Comfy] 原始错误: {server_error}")
                                self.status_changed.emit(f"提交失败: {server_error}")
                        else:
                            print(f"[Comfy] 服务器响应: {response_body}")
                    except:
                        print(f"[Comfy] 无法解析错误响应: {response_body}")
                
                if workflow_json:
                    print(f"[Comfy] Debug - 提交的 Payload: {json.dumps(workflow_json, indent=2, ensure_ascii=False)}")
                
                if not response_body:
                    self.status_changed.emit(f"提交失败: {err_msg}")
        except Exception as e:
            print(f"[Comfy] 响应解析失败: {e}")
            self.status_changed.emit(f"响应解析错误: {e}")
        finally:
            reply.deleteLater()

    def submit_workflow_batch(
        self,
        workflows: List[Dict[str, Any]],
        contexts: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """按顺序提交多个 workflow，并附带上下文。"""
        if not workflows:
            return

        self.status_changed.emit(f"正在提交 {len(workflows)} 个任务...")
        for idx, workflow in enumerate(workflows):
            context = None
            if contexts and idx < len(contexts):
                context = contexts[idx]
            self.send_prompt(workflow, context=context)

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
                # print(f"[Comfy] 当前队列: Running={len(running)}, Pending={len(pending)}")
                # 可以在这里 emit 信号更新 UI
            else:
                print(f"[Comfy] 获取队列失败: {reply.errorString()}")
        except Exception as e:
            print(f"[Comfy] 队列响应解析失败: {e}")
        finally:
            reply.deleteLater()

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            f = float(value)
            return f if f >= 0 else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _pick_int_from_keys(cls, data: Dict[str, Any], keys: List[str]) -> Optional[int]:
        for key in keys:
            if key in data:
                try:
                    return int(data.get(key))
                except (TypeError, ValueError):
                    continue
        return None

    @classmethod
    def _pick_float_from_keys(cls, data: Dict[str, Any], keys: List[str]) -> Optional[float]:
        for key in keys:
            if key in data:
                value = cls._safe_float(data.get(key))
                if value is not None:
                    return value
        return None

    @staticmethod
    def _dict_candidates(payload_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = [payload_dict]
        for key in ("progress", "state", "status", "exec_info", "data"):
            nested = payload_dict.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)
        return candidates

    @classmethod
    def _parse_progress_payload(cls, payload: Any) -> Dict[str, Any]:
        payload_dict = payload if isinstance(payload, dict) else {}
        value = 0
        max_val = 0
        eta_seconds = None

        for candidate in cls._dict_candidates(payload_dict):
            if not isinstance(candidate, dict):
                continue

            parsed_value = cls._pick_int_from_keys(
                candidate,
                ["value", "current", "step", "current_step", "step_no", "completed_steps"],
            )
            parsed_max = cls._pick_int_from_keys(
                candidate,
                ["max", "total", "steps", "total_steps", "step_count", "max_steps"],
            )
            parsed_eta = cls._pick_float_from_keys(
                candidate,
                [
                    "eta_relative",
                    "eta",
                    "remaining",
                    "eta_seconds",
                    "remaining_seconds",
                    "time_left",
                    "time_remaining",
                ],
            )

            if parsed_value is not None:
                value = max(parsed_value, 0)
            if parsed_max is not None:
                max_val = max(parsed_max, 0)
            if parsed_eta is not None:
                eta_seconds = parsed_eta

            if max_val > 0 or value > 0 or eta_seconds is not None:
                break

        return {
            "value": value,
            "max": max_val,
            "eta_seconds": eta_seconds,
        }

    def get_system_stats(self) -> None:
        """查询 ComfyUI 系统资源状态（显存/内存）"""
        if not self._system_stats_supported:
            return
        url = QUrl(f"http://{self.server_address}/system_stats")
        reply = self.nam.get(QNetworkRequest(url))
        reply.finished.connect(lambda: self._handle_system_stats_response(reply))

    @staticmethod
    def _pick_numeric(data: Dict[str, Any], keys: List[str]) -> Optional[float]:
        for key in keys:
            if key in data:
                value = ComfyClient._safe_float(data.get(key))
                if value is not None:
                    return value
        return None

    @staticmethod
    def _pick_device(devices: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(devices, list):
            return None
        typed_devices = [d for d in devices if isinstance(d, dict)]
        if not typed_devices:
            return None

        for dev in typed_devices:
            dev_type = str(dev.get("type") or "").lower()
            dev_name = str(dev.get("name") or "").lower()
            if "cuda" in dev_type or "cuda" in dev_name or "nvidia" in dev_name:
                return dev
        return typed_devices[0]

    @classmethod
    def _parse_system_stats_payload(cls, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        system = payload.get("system") if isinstance(payload.get("system"), dict) else {}
        device = cls._pick_device(payload.get("devices"))

        ram_total = cls._pick_numeric(system, ["ram_total", "total_ram", "memory_total"])
        ram_free = cls._pick_numeric(system, ["ram_free", "free_ram", "memory_free"])
        ram_used = cls._pick_numeric(system, ["ram_used", "used_ram", "memory_used"])
        if ram_used is None and ram_total is not None and ram_free is not None:
            ram_used = max(ram_total - ram_free, 0.0)

        vram_total = None
        vram_free = None
        vram_used = None
        gpu_name = ""
        if isinstance(device, dict):
            gpu_name = str(device.get("name") or "")
            vram_total = cls._pick_numeric(
                device,
                ["vram_total", "total_vram", "torch_vram_total", "memory_total", "total_memory"],
            )
            vram_free = cls._pick_numeric(
                device,
                ["vram_free", "free_vram", "torch_vram_free", "memory_free", "free_memory"],
            )
            vram_used = cls._pick_numeric(
                device,
                ["vram_used", "used_vram", "memory_used", "used_memory"],
            )
            if vram_used is None and vram_total is not None and vram_free is not None:
                vram_used = max(vram_total - vram_free, 0.0)

        return {
            "gpu_name": gpu_name,
            "ram_used": ram_used,
            "ram_total": ram_total,
            "vram_used": vram_used,
            "vram_total": vram_total,
        }

    def _handle_system_stats_response(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if status_code == 404:
                    self._system_stats_supported = False
                    if self.system_stats_timer.isActive():
                        self.system_stats_timer.stop()
                    print("[Comfy] /system_stats 不可用，已停用资源轮询")
                return

            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            stats = self._parse_system_stats_payload(payload)
            if stats:
                self.system_stats_updated.emit(stats)
        except Exception as e:
            print(f"[Comfy] 系统状态解析失败: {e}")
        finally:
            reply.deleteLater()

    def queue_current_prompt(
        self,
        workflow: Optional[Dict[str, Any]] = None,
        batch_count: int = 1,
        randomize_seed: bool = True
    ) -> None:
        """
        重新提交workflow（修改随机种子）
        如果提供了workflow参数，直接使用；否则从 /history 获取最近的workflow
        """
        if workflow:
            # 直接使用提供的workflow
            print(f"[Comfy] 使用提供的workflow (批量: {batch_count})")
            self.status_changed.emit(f"正在提交 {batch_count} 个任务...")
            
            for i in range(batch_count):
                if randomize_seed:
                    submit_workflow = ComfyClient.randomize_workflow_seeds(workflow)
                else:
                    submit_workflow = copy.deepcopy(workflow)
                self.send_prompt(submit_workflow)
        else:
            # 从历史记录获取
            print("[Comfy] queue_current_prompt: 正在获取最近的工作流...")
            self.status_changed.emit("正在获取最近的工作流...")
            
            # 存储批量计数，供回调使用
            self._pending_batch_count = batch_count
        
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
            prompt_data = latest_entry.get('prompt')
            
            # 尝试从不同位置获取workflow
            workflow = None
            
            # 方法1: 检查meta字段是否包含workflow
            if "meta" in latest_entry:
                meta = latest_entry["meta"]
                # print(f"[Comfy Debug] meta字段内容: {meta}")
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
                # print(f"[Comfy] prompt类型: {type(prompt_data)}, 内容: {prompt_data}")
                self.status_changed.emit("无法获取完整workflow，请在ComfyUI中保存为API格式")
                return
            
            print(f"[Comfy] 成功获取workflow (prompt_id: {latest_prompt_id})")
            
            # 获取批量计数
            batch_count = getattr(self, '_pending_batch_count', 1)
            self._pending_batch_count = 1 # Reset
            
            self.status_changed.emit(f"已获取workflow，正在提交 {batch_count} 个任务...")
            
            for i in range(batch_count):
                # 修改随机种子避免生成相同图片
                modified_workflow = ComfyClient.randomize_workflow_seeds(workflow)
                # 提交到队列
                self.send_prompt(modified_workflow)
            
        except Exception as e:
            import traceback
            print(f"[Comfy] 处理历史记录失败: {e}")
            print(f"[Comfy Debug] 完整错误: {traceback.format_exc()}")
            self.status_changed.emit(f"处理历史记录失败: {e}")
        finally:
            reply.deleteLater()
    
    def fetch_available_models(self):
        """获取ComfyUI可用模型列表"""
        url_str = f"http://{self.server_address}/object_info/CheckpointLoaderSimple"
        # print(f"[Comfy] debug: fetch_available_models 调用, URL: {url_str}")
        
        url = QUrl(url_str)
        request = QNetworkRequest(url)
        # 增加超时设置 (虽不保证NAM生效，但值得尝试)
        request.setTransferTimeout(5000) 
        
        self._model_fetch_reply = self.nam.get(request)
        self._model_fetch_reply.finished.connect(lambda: self._handle_models_response(self._model_fetch_reply))
        self._model_fetch_reply.errorOccurred.connect(lambda err: print(f"[Comfy] ⚠️ 模型请求网络错误: {err}"))

    def _handle_models_response(self, reply: QNetworkReply) -> None:
        """处理模型列表响应"""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                print(f"[Comfy] 获取模型列表失败: {reply.errorString()}")
                return
            
            data = json.loads(bytes(reply.readAll()).decode('utf-8'))
            
            # ComfyUI 返回格式: {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["model1.ckpt", "model2.safetensors"], ...]}}}}
            # 注意 ckpt_name 的值是一个由列表组成的元组，第一个元素是模型文件名列表
            valid_models = []
            
            inputs = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {})
            ckpt_param = inputs.get("ckpt_name")
            
            if ckpt_param and isinstance(ckpt_param, list) and len(ckpt_param) > 0:
                # 第一个元素通常是文件名列表
                models_list = ckpt_param[0]
                if isinstance(models_list, list):
                    valid_models = models_list
            
            if valid_models:
                print(f"[Comfy] 成功获取 {len(valid_models)} 个可用模型")
                self.models_fetched.emit(valid_models)
            else:
                # print("[Comfy] 未解析到任何模型") # Suppress noise
                pass
                
        except Exception as e:
            print(f"[Comfy] 模型列表解析异常: {e}")
        finally:
            reply.deleteLater()

    @staticmethod
    def randomize_workflow_seeds(workflow: Any) -> Any:
        """
        遍历workflow，将所有KSampler节点的seed随机化
        返回修改后的workflow副本
        支持字典格式和列表格式的workflow
        """
        import json
        import random
        
        # 深拷贝
        workflow_copy = json.loads(json.dumps(workflow))
        
        if isinstance(workflow_copy, dict):
            for node_id, node_data in workflow_copy.items():
                ComfyClient._randomize_node_seed(node_id, node_data)
        elif isinstance(workflow_copy, list):
            for node_data in workflow_copy:
                node_id = node_data.get("id", "unknown")
                ComfyClient._randomize_node_seed(node_id, node_data)
        return workflow_copy
    
    @staticmethod
    def _randomize_node_seed(node_id: Any, node_data: Dict[str, Any]) -> None:
        """随机化单个节点的seed"""
        import random
        class_type = node_data.get("class_type", "")
        # 常见的采样器节点类型
        if "sampler" in class_type.lower() or class_type == "KSampler":
            inputs = node_data.get("inputs", {})
            if "seed" in inputs:
                # “超随机种子”实现：使用 OS 级真随机源，保持 18-20 位长度
                ultra_random_seed = random.SystemRandom().randint(10**17, 18446744073709551614)
                inputs["seed"] = ultra_random_seed

    # ========== 队列管理方法 ==========
    
    def get_queue(self):
        """获取当前队列状态"""
        url = QUrl(f"http://{self.server_address}/queue")
        request = QNetworkRequest(url)
        reply = self.nam.get(request)
        reply.finished.connect(lambda: self._handle_queue_response(reply))
    
    def _handle_queue_response(self, reply: QNetworkReply):
        """处理队列查询响应"""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                print(f"[Comfy Queue] 查询失败: {reply.errorString()}")
                return
            
            data = json.loads(bytes(reply.readAll()).decode())
            # print(f"[Comfy Queue] 当前队列: Running={len(data.get('queue_running', []))}, Pending={len(data.get('queue_pending', []))}")
            
            # 发送信号
            self.queue_updated.emit(data)
            
        except Exception as e:
            print(f"[Comfy Queue] 解析队列数据失败: {e}")
        finally:
            reply.deleteLater()
    
    def cancel_task(self, prompt_id: str):
        """取消指定任务"""
        url = QUrl(f"http://{self.server_address}/queue")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        
        data = {"delete": [prompt_id]}
        json_data = QByteArray(json.dumps(data).encode())
        
        reply = self.nam.post(request, json_data)
        reply.finished.connect(lambda: self._handle_cancel_response(reply, prompt_id))
    
    def _handle_cancel_response(self, reply: QNetworkReply, prompt_id: str):
        """处理取消任务响应"""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                err_msg = reply.errorString()
                print(f"[Comfy Queue] 取消任务失败: {err_msg}")
                self.operation_failed.emit(f"取消失败: {err_msg}")
                return
            # 读取响应 (ComfyUI /queue 接口 POST delete 返回类似 {"delete": [id1, id2]})
            resp_raw = reply.readAll()
            try:
                resp_json = json.loads(bytes(resp_raw).decode())
                print(f"[Comfy Queue] 响应: {resp_json}")
            except:
                print(f"[Comfy Queue] 无法解析响应: {resp_raw}")
            
            print(f"[Comfy Queue] 已成功发送取消请求: {prompt_id}")
            self.task_cancelled.emit(prompt_id)
            
        except Exception as e:
            print(f"[Comfy Queue] 取消任务错误: {e}")
        finally:
            reply.deleteLater()
    
    def clear_queue(self):
        """清空队列"""
        url = QUrl(f"http://{self.server_address}/queue")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        
        data = {"clear": True}
        json_data = QByteArray(json.dumps(data).encode())
        
        reply = self.nam.post(request, json_data)
        reply.finished.connect(lambda: self._handle_clear_response(reply))
    
    def _handle_clear_response(self, reply: QNetworkReply):
        """处理清空队列响应"""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                err_msg = reply.errorString()
                print(f"[Comfy Queue] 清空队列失败: {err_msg}")
                self.operation_failed.emit(f"清空失败: {err_msg}")
                return
            
            print(f"[Comfy Queue] 队列已清空")
            self.queue_cleared.emit()
            
        except Exception as e:
            print(f"[Comfy Queue] 清空队列错误: {e}")
        finally:
            reply.deleteLater()
    
    def interrupt_current(self):
        """中断当前任务"""
        url = QUrl(f"http://{self.server_address}/interrupt")
        request = QNetworkRequest(url)
        
        reply = self.nam.post(request, QByteArray())
        reply.finished.connect(lambda: self._handle_interrupt_response(reply))
    
    def _handle_interrupt_response(self, reply: QNetworkReply):
        """处理中断响应"""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                err_msg = reply.errorString()
                print(f"[Comfy Queue] 中断任务失败: {err_msg}")
                self.operation_failed.emit(f"中断失败: {err_msg}")
                return
            
            print(f"[Comfy Queue] 已中断当前任务")
            self.status_changed.emit("已中断当前任务")
            
        except Exception as e:
            print(f"[Comfy Queue] 中断任务错误: {e}")
        finally:
            reply.deleteLater()

