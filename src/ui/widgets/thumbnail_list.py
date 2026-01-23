from PyQt6.QtWidgets import QListView, QAbstractItemView
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from src.ui.widgets.image_model import ImageModel

class ThumbnailList(QListView):
    """
    显示图片缩略图的列表组件 (高性能 QListView 版)。
    """
    image_selected = pyqtSignal(str) # 发送完整路径
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSpacing(6)
        self.setWordWrap(True)
        self.setWrapping(True)
        
        # 启用抗锯齿和流畅滚动
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        
        # 图标大小 (逻辑上由网格控制，但这里设置基准)
        self.setIconSize(QSize(128, 128))
        self.setGridSize(QSize(148, 170)) # 紧凑网格 (160->148, 190->170)
        
        # 初始化模型
        self.image_model = ImageModel(self)
        self.setModel(self.image_model)
        
        # 监听选区变化而非点击，确保键盘导航也能触发，且避免双重信号
        if self.selectionModel():
            self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        
    def _on_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        if indexes:
            # 单选模式下取第一个
            index = indexes[0]
            path = self.image_model.get_path(index.row())
            if path:
                self.image_selected.emit(path)

    def add_image(self, path, index=None, thumbnail=None):
        """代理模型添加图片"""
        self.image_model.add_image(path, thumb=thumbnail, index=index)
        
    def clear_list(self):
        self.image_model.clear()
        
    def setCurrentRow(self, row):
        """兼容旧接口"""
        if 0 <= row < self.image_model.rowCount():
            idx = self.image_model.index(row)
            self.setCurrentIndex(idx)
            
    def count(self):
        """兼容旧接口"""
        return self.image_model.rowCount()

    def item(self, row):
        """兼容旧接口，返回一个模拟对象"""
        class MockItem:
            def __init__(self, path):
                self._path = path
            def data(self, role):
                return self._path
        path = self.image_model.get_path(row)
        return MockItem(path) if path else None

    # 重写这些是为了保持原有的网格自适应感
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # QListView 的 IconMode 会自动流式布局，这里可以补充更精细的网格控制
        # 暂时保持默认，由 setGridSize 驱动

    def wheelEvent(self, event):
        """重写滚轮事件以实现细腻顺滑的滚动体验"""
        # 如果按住了 Ctrl，则保持默认行为 (通常是缩放)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return

        # 获取垂直滚动条
        vbar = self.verticalScrollBar()
        if not vbar or not vbar.isVisible():
            return

        # 获取滚轮增量 (通常一格是 120)
        delta = event.angleDelta().y()
        
        # 定义滚动系数: 将 120 的 delta 映射为多少像素
        # 原生通常较快 (比如 60-100px)，改为 30px 以实现"非常细腻"
        scroll_step_per_notch = 30 
        
        # 计算目标步长 (注意: delta > 0 是向上滚，value 应该减小)
        # 120 -> -30
        pixels_to_scroll = - (delta / 120.0) * scroll_step_per_notch
        
        # 应用滚动
        vbar.setValue(vbar.value() + int(pixels_to_scroll))
        event.accept()
