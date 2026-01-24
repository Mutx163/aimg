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
        self.resize(500, 400)
        
        self.setup_ui()
        self.setup_connections()
        self.setup_timer()
        
        # 立即刷新一次
        self.refresh_queue()
    
    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        
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
        
        # 队列列表
        self.queue_list = QListWidget()
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
        self.status_label.setText(f"总任务: {total} | 执行中: {len(running)} | 等待: {len(pending)}")
    
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
        layout.setContentsMargins(4, 2, 4, 2)
        
        # 任务信息
        info_label = QLabel(f"Task #{number}: {prompt_id[:12]}...")
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        # 操作按钮
        if is_running:
            btn = QPushButton("中断")
            btn.clicked.connect(lambda: self.comfy_client.interrupt_current())
        else:
            btn = QPushButton("取消")
            btn.clicked.connect(lambda _, pid=prompt_id: self.comfy_client.cancel_task(pid))
        
        btn.setMaximumWidth(60)
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
