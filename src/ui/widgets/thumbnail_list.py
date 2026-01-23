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
        self.setSpacing(10)
        self.setWordWrap(True)
        
        # 初始化模型
        self.image_model = ImageModel(self)
        self.setModel(self.image_model)
        
        # 图标大小 (逻辑上由网格控制，但这里设置基准)
        self.setIconSize(QSize(128, 128))
        self.setGridSize(QSize(150, 180))
        
        self.clicked.connect(self._on_clicked)
        
    def _on_clicked(self, index):
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
