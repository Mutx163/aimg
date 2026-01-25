from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QWheelEvent, QColor, QBrush, QPainter

class ImageViewer(QGraphicsView):
    """
    基于 QGraphicsView 的图片查看器。支持自动适配窗口。
    """
    navigate_request = pyqtSignal(int) # -1: Prev, 1: Next
    view_changed = pyqtSignal(object, object) # transform, (h_val, v_val)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        
        # 视觉美化：干净的背景 (跟随主题)
        self.setBackgroundBrush(QBrush(QColor("#0f0f0f")))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setLineWidth(0)
        self.setContentsMargins(0, 0, 0, 0)
        self.viewport().setContentsMargins(0, 0, 0, 0)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setOptimizationFlags(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing)
        
        self.pixmap_item = QGraphicsPixmapItem()
        self.pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene.addItem(self.pixmap_item)
        
        self._zoom_factor = 1.15
        self.auto_fit = True 
        self._is_syncing = False # 防止信号环路

    def set_background_color(self, color_str):
        """设置视图背景色"""
        self.setBackgroundBrush(QBrush(QColor(color_str)))

    def sync_view(self, transform, scroll_pos):
        """同步其他视图的状态"""
        if self._is_syncing: return
        self._is_syncing = True
        self.auto_fit = False
        self.setTransform(transform)
        self.horizontalScrollBar().setValue(scroll_pos[0])
        self.verticalScrollBar().setValue(scroll_pos[1])
        self._is_syncing = False

    def scrollContentsBy(self, dx, dy):
        """当滚动位置改变时发出信号"""
        super().scrollContentsBy(dx, dy)
        if not self._is_syncing:
            self.view_changed.emit(self.transform(), 
                                   (self.horizontalScrollBar().value(), 
                                    self.verticalScrollBar().value()))

    def clear_view(self):
        """清空显示并重置状态"""
        self.pixmap_item.setPixmap(QPixmap())
        self.auto_fit = True
        self.resetTransform()

    def load_image(self, file_path):
        """加载显示图片"""
        # 如果 pixmap_item 被意外删除（例如通过 scene.clear()），重新创建
        try:
            self.pixmap_item.isVisible()
        except RuntimeError:
            self.pixmap_item = QGraphicsPixmapItem()
            self.pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.scene.addItem(self.pixmap_item)

        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            return
            
        self.pixmap_item.setPixmap(pixmap)
        self.setSceneRect(self.pixmap_item.boundingRect()) # 强行限制场景大小与图片一致
        if self.auto_fit:
            self.fit_to_window()

    def fit_to_window(self):
        """适应窗口 (完整显示并居中)"""
        self.auto_fit = True
        if not self.pixmap_item.pixmap().isNull():
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            
    def toggle_fill_mode(self):
        """铺满窗口 (Crop模式，消除所有黑边)"""
        self.auto_fit = True
        if not self.pixmap_item.pixmap().isNull():
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            
    def fit_to_original(self):
        """1:1 原始大小"""
        self.auto_fit = False
        self.resetTransform()
            
    def wheelEvent(self, event: QWheelEvent):
        """处理滚轮"""
        from PyQt6.QtCore import QSettings
        settings = QSettings("ComfyUIImageManager", "Settings")
        wheel_action = settings.value("wheel_action", "zoom")
        
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            wheel_action = "zoom"

        if wheel_action == "navigate":
            delta = event.angleDelta().y()
            if delta > 0: self.navigate_request.emit(-1)
            else: self.navigate_request.emit(1)
        else:
            self.auto_fit = False 
            if event.angleDelta().y() > 0:
                self.scale(self._zoom_factor, self._zoom_factor)
            else:
                self.scale(1 / self._zoom_factor, 1 / self._zoom_factor)
            
            # 发出同步信号
            if not self._is_syncing:
                self.view_changed.emit(self.transform(), 
                                       (self.horizontalScrollBar().value(), 
                                        self.verticalScrollBar().value()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.fit_to_window()


