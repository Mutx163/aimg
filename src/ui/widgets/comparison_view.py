from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QSplitter
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
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
        # 关键修复：先重置两侧视图状态，避免复用上一轮的缩放/滚动导致裁切
        self.viewer_left.auto_fit = True
        self.viewer_right.auto_fit = True
        self.viewer_left.resetTransform()
        self.viewer_right.resetTransform()
        self.viewer_left.horizontalScrollBar().setValue(0)
        self.viewer_left.verticalScrollBar().setValue(0)
        self.viewer_right.horizontalScrollBar().setValue(0)
        self.viewer_right.verticalScrollBar().setValue(0)

        self.viewer_left.load_image(left_path)
        self.viewer_right.load_image(right_path)

        # 异步加载完成后再同步，避免在图片未就绪时把旧transform套到新图上
        self._sync_retry_count = 0
        QTimer.singleShot(80, self._sync_after_load)

    def _sync_after_load(self):
        left_ready = not self.viewer_left.pixmap_item.pixmap().isNull()
        right_ready = not self.viewer_right.pixmap_item.pixmap().isNull()

        if not (left_ready and right_ready):
            self._sync_retry_count += 1
            if self._sync_retry_count <= 12:
                QTimer.singleShot(80, self._sync_after_load)
            return

        self.viewer_left.fit_to_window()
        self.viewer_right.fit_to_window()
        self.viewer_right.sync_view(
            self.viewer_left.transform(),
            (
                self.viewer_left.horizontalScrollBar().value(),
                self.viewer_left.verticalScrollBar().value(),
            ),
        )

    def clear(self):
        self.viewer_left.clear_view()
        self.viewer_right.clear_view()
