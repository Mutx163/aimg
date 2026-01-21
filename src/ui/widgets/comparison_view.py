from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QSplitter
from PyQt6.QtCore import Qt, pyqtSignal
from src.ui.widgets.image_viewer import ImageViewer

class ComparisonView(QWidget):
    """
    对比视图：包含两个并列的 ImageViewer，支持联动。
    """
    navigate_request = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.viewer_left = ImageViewer()
        self.viewer_right = ImageViewer()
        
        # 初始隐藏其中一个，或者两个都显示
        self.splitter.addWidget(self.viewer_left)
        self.splitter.addWidget(self.viewer_right)
        
        self.layout.addWidget(self.splitter)
        
        # 联动逻辑
        self.viewer_left.view_changed.connect(self.viewer_right.sync_view)
        self.viewer_right.view_changed.connect(self.viewer_left.sync_view)
        
        # 转发导航信号
        self.viewer_left.navigate_request.connect(self.navigate_request.emit)
        self.viewer_right.navigate_request.connect(self.navigate_request.emit)

    def load_images(self, left_path, right_path):
        """同时加载两张图片"""
        self.viewer_left.load_image(left_path)
        self.viewer_right.load_image(right_path)
        
        # 初始强行同步一次
        self.viewer_right.sync_view(self.viewer_left.transform(), 
                                    (self.viewer_left.horizontalScrollBar().value(), 
                                     self.viewer_left.verticalScrollBar().value()))

    def clear(self):
        self.viewer_left.clear_view()
        self.viewer_right.clear_view()
