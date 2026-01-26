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
        self.setSpacing(4)
        self.setWordWrap(True)
        self.setWrapping(True)
        
        # 启用抗锯齿和流畅滚动
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        
        # 图标大小 (逻辑上由网格控制，但这里设置基准)
        self.setIconSize(QSize(128, 128))
        self.setGridSize(QSize(140, 190)) # 固定紧凑网格 (宽140=128+12, 高190确保文件名显示)
        
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
    
    def update_image_icon(self, index, icon):
        """更新指定索引的图片图标 (代理给 Model)"""
        # SearchController 传递的是 index (int) 和 QImage/QPixmap
        # ImageModel.update_thumbnail 需要 path 和 thumb
        # 但既然我们知道 index，直接通过 Model 获取 Path 似乎多余，不如直接用 update_item
        # 看看 ImageModel，它有 update_thumbnail(path, thumb)
        
        # 修正：SearchController 传递的是 (index, path, thumb)
        # 所以我们可以直接调用 list 的 model
        # 但为了方便，我们在这里封装一下
        # 注意：SearchController 中的 _on_search_thumb_ready(self, index, path, thumb)
        # 直接调用 update_image_icon(index, thumb) 是错误的，因为 Controller 里是
        # self.main.thumbnail_list.update_image_icon(index, thumb)
        # 应该改为 update_thumbnail(path, thumb)
        
        # 既然之前的代码尝试调 update_image_icon，我就加上它，并让它调用 model 的 update_thumbnail
        # 但参数不对齐。
        # 让我看看 SearchController 的调用：
        # self.main.thumbnail_list.update_image_icon(index, thumb) 
        # 它只传了 index 和 thumb，没传 path。
        # 这是一个问题，因为 model.update_thumbnail 是基于 path 的。
        # 不过，我们有 index，可以拿到 path。
        
        path = self.image_model.get_path(index)
        if path:
            self.image_model.update_thumbnail(path, icon)
        
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

    # resizeEvent 已移除，不再动态调整网格大小，避免出现超大间距

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
