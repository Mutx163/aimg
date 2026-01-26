from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QListWidget, QListWidgetItem, QLabel, QWidget)
from PyQt6.QtCore import QTimer, Qt

class QueueDialog(QDialog):
    """ComfyUI队列管理对话框"""
    
    def __init__(self, comfy_client, parent=None):
        super().__init__(parent)
        self.comfy_client = comfy_client
        self.queue_data = {}
        
        self.setWindowTitle("ComfyUI 任务队列")
        self.resize(560, 440)
        
        self.setup_ui()
        self.setup_connections()
        self.setup_timer()
        
        # 立即刷新一次
        self.refresh_queue()
    
    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # 顶部按钮栏
        top_bar = QHBoxLayout()
        
        self.refresh_btn = QPushButton("🔄 刷新")
        self.clear_btn = QPushButton("🗑️ 清空队列")
        self.interrupt_btn = QPushButton("⏸️ 中断当前")
        
        top_bar.addWidget(self.refresh_btn)
        top_bar.addStretch()
        top_bar.addWidget(self.interrupt_btn)
        top_bar.addWidget(self.clear_btn)
        
        layout.addLayout(top_bar)

        self.summary_label = QLabel("队列加载中...")
        self.summary_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self.summary_label)
        
        # 队列列表
        self.queue_list = QListWidget()
        self.queue_list.setSpacing(6)
        self.queue_list.setAlternatingRowColors(True)
        self.queue_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.queue_list.setStyleSheet("QListWidget { border: 1px solid palette(mid); border-radius: 6px; }")
        layout.addWidget(self.queue_list)
        
        # 状态标签
        self.status_label = QLabel("等待刷新...")
        self.status_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.status_label)
    
    def setup_connections(self):
        """设置信号连接"""
        self.refresh_btn.clicked.connect(self.refresh_queue)
        self.clear_btn.clicked.connect(self.clear_queue)
        self.interrupt_btn.clicked.connect(self.interrupt_current)
        
        # 连接ComfyClient信号
        self.comfy_client.queue_updated.connect(self.on_queue_updated)
        self.comfy_client.queue_cleared.connect(self.on_queue_cleared)
        self.comfy_client.task_cancelled.connect(self.on_task_cancelled)
        self.comfy_client.operation_failed.connect(self.on_operation_failed)
    
    def setup_timer(self):
        """设置定时器，每2秒自动刷新"""
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_queue)
        self.timer.start(2000)  # 2秒
    
    def refresh_queue(self):
        """刷新队列状态"""
        self.comfy_client.get_queue()
    
    def on_queue_updated(self, data):
        """队列数据更新"""
        self.queue_data = data
        self.update_list()
    
    def update_list(self):
        """更新列表显示"""
        self.queue_list.clear()
        
        running = self.queue_data.get('queue_running', [])
        pending = self.queue_data.get('queue_pending', [])
        
        self.interrupt_btn.setEnabled(bool(running))
        self.clear_btn.setEnabled(bool(running or pending))

        # 正在执行
        if running:
            header = QListWidgetItem("● 正在执行")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setForeground(Qt.GlobalColor.green)
            self.queue_list.addItem(header)
            
            for task in running:
                self._create_task_item(task, is_running=True)
        
        # 等待中
        if pending:
            header = QListWidgetItem("⏸ 等待中")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setForeground(Qt.GlobalColor.yellow)
            self.queue_list.addItem(header)
            
            for task in pending:
                self._create_task_item(task, is_running=False)
        
        # 空队列
        if not running and not pending:
            empty_item = QListWidgetItem("✨ 队列为空")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setForeground(Qt.GlobalColor.gray)
            self.queue_list.addItem(empty_item)
        
        # 更新状态
        total = len(running) + len(pending)
        self.summary_label.setText(f"总任务 {total} · 执行中 {len(running)} · 等待 {len(pending)}")
        self.status_label.setText("已刷新队列")
    
    def _create_task_item(self, task, is_running):
        """创建任务列表项"""
        if isinstance(task, list) and len(task) >= 2:
            prompt_id = task[1]
            number = task[0]
        else:
            prompt_id = str(task)
            number = "?"
        
        # 创建自定义widget
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12) # 增加间距

        # 尝试提取 Lora 名称 (通用模糊匹配算法)
        lora_names = []
        try:
            # task[2] 通常是 prompt JSON 数据
            if isinstance(task, list) and len(task) >= 3:
                prompt_graph = task[2]
                if isinstance(prompt_graph, dict):
                    for node_id, node_data in prompt_graph.items():
                        c_type = str(node_data.get('class_type', '')).lower()
                        # 核心逻辑：包含 lora 且包含 loader 的节点通常就是目标
                        if 'lora' in c_type and 'loader' in c_type:
                            inputs = node_data.get('inputs', {})
                            for k, v in inputs.items():
                                # 如果值是字符串且包含常见的模型后缀，认定为 LoRA 名称
                                if isinstance(v, str) and v.lower().endswith(('.safetensors', '.ckpt', '.pt')):
                                    # 只保留文件名部分，去除路径
                                    l_name = v.replace('\\', '/').split('/')[-1]
                                    if l_name not in lora_names:
                                        lora_names.append(l_name)
        except Exception as e:
            print(f"[Queue] 提取 LoRA 失败: {e}")

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        title = QLabel(f"任务 #{number}")
        title.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(title)
        
        # 添加 Lora 信息显示 (置于 ID 之上，更醒目)
        if lora_names:
            lora_text = "Lora: " + ", ".join(lora_names)
            lora_lbl = QLabel(lora_text)
            # 使用更鲜亮的颜色，并在背景色较浅时也能清晰可见
            lora_lbl.setStyleSheet("color: #d15100; font-size: 11px; font-weight: bold;")
            lora_lbl.setWordWrap(True)
            left_layout.addWidget(lora_lbl)

        sub = QLabel(f"ID: {prompt_id}")
        sub.setStyleSheet("color: palette(mid); font-size: 10px;")
        left_layout.addWidget(sub)

        layout.addWidget(left, 1)
        
        # 操作按钮
        status = QLabel("执行中" if is_running else "等待中")
        status.setStyleSheet("color: palette(highlight); font-size: 10px;" if is_running else "color: palette(mid); font-size: 10px;")
        layout.addWidget(status)

        if is_running:
            btn = QPushButton("中断")
            btn.clicked.connect(lambda: self.comfy_client.interrupt_current())
        else:
            btn = QPushButton("取消")
            btn.clicked.connect(lambda _, pid=prompt_id: self.comfy_client.cancel_task(pid))

        btn.setMaximumWidth(70)
        layout.addWidget(btn)
        
        # 创建item并添加到列表
        item = QListWidgetItem()
        self.queue_list.addItem(item)
        
        # 绑定Widget
        item.setSizeHint(widget.sizeHint())
        self.queue_list.setItemWidget(item, widget)
        
        return item
    
    def clear_queue(self):
        """清空队列"""
        self.comfy_client.clear_queue()
    
    def interrupt_current(self):
        """中断当前任务"""
        self.comfy_client.interrupt_current()
    
    def on_queue_cleared(self):
        """队列已清空"""
        self.status_label.setText("队列已清空")
        self.refresh_queue()
    
    def on_task_cancelled(self, prompt_id):
        """任务已取消"""
        self.status_label.setText(f"已取消任务: {prompt_id[:12]}...")
        self.refresh_queue()
    
    def on_operation_failed(self, error):
        """操作失败"""
        self.status_label.setText(error)
        self.status_label.setStyleSheet("color: red; font-size: 11px;")
        # 3秒后恢复默认颜色
        QTimer.singleShot(3000, lambda: self.status_label.setStyleSheet("color: gray; font-size: 11px;"))
    
    def closeEvent(self, event):
        """关闭对话框时停止定时器"""
        self.timer.stop()
        super().closeEvent(event)
