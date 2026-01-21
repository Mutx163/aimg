import os
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap

class ThumbnailList(QListWidget):
    """
    显示图片缩略图的列表组件。
    """
    image_selected = pyqtSignal(str) # 发送完整路径
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(128, 128))
        # 设为 Fixed 模式，完全由我们手动通过 adjust_grid_size 掌控
        self.setResizeMode(QListWidget.ResizeMode.Fixed)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionRectVisible(False) # 双重保险
        self.setSpacing(0)
        self.setWordWrap(True) # 允许文件名换行
        
        # 记录上次设置的宽度，防止反馈循环
        self._last_grid_w = 0
        self.setGridSize(QSize(140, 170)) # 增加一点高度给文本
        
        self.itemClicked.connect(self._on_item_clicked)
        
    def mousePressEvent(self, event):
        """
        重写鼠标按下事件，防止点击背景区域触发“框选”导致意外连选。
        """
        item = self.itemAt(event.pos())
        if not item:
            # 点击空白处，清除选择但不要启动拖拽框选
            self.clearSelection()
            # 标记事件已处理，不传递给基类以防启动框选
            event.accept()
            return
            
        # 如果点在项目上，执行标准逻辑
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        重写鼠标移动事件。
        由于基类的 mouseMoveEvent 在 ExtendedSelection 模式下会通过拖拽调整选择范围，
        我们在这里确保如果不是从项目开始的拖拽，就不执行选择。
        """
        # 如果没有当前选中的起始项，或者没有按下左键，直接交给原逻辑（或者忽略）
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return

        # 检查当前鼠标位置是否有项目
        item = self.itemAt(event.pos())
        if not item:
            # 如果拖拽到了空白处，忽略该移动信号，不扩大选区
            event.accept()
            return
            
        super().mouseMoveEvent(event)

    def resizeEvent(self, event):
        """窗口缩放"""
        super().resizeEvent(event)
        # 延迟一丢丢执行，或者直接执行，但内部要有防抖
        self.adjust_grid_size()

    def adjust_grid_size(self):
        """
        动态计算网格大小。
        关键：必须考虑滚动条的出现/消失，避免导致闪烁的反馈循环。
        """
        # 1. 获取总宽度（包括不可见区域）
        total_w = self.width() 
        if total_w <= 0: return
        
        # 2. 始终预留一个固定的滚动条宽度 (通常为 15-20px) + 边距
        # 即使现在没有滚动条，也要假设它存在，这样当它真正出现时不会把第二列挤下去。
        safe_w = total_w - 22 
        
        # 3. 设定每列的切换阈值
        # 如果 safe_w >= 256 (即 128 * 2)，就应该显示两列
        # 为了更顺滑，我们用 130 作为一个基准
        base_threshold = 130
        cols = max(1, safe_w // base_threshold)
        
        # 4. 计算网格宽度：
        # 如果是单列，且宽度过大，限制其无限拉宽导致的“大空白”
        # 或者直接让它撑满。用户想要“去掉空白”，通常是指让列数尽快增加。
        new_grid_w = safe_w // cols
        
        # 5. 防抖逻辑：如果列数没变，且宽度变化很小，不重新布局以节省性能并防止闪烁
        new_grid_h = 170
        if abs(new_grid_w - self._last_grid_w) < 3:
            return
            
        self._last_grid_w = new_grid_w
        self.setGridSize(QSize(new_grid_w, new_grid_h))
        
    def add_image(self, path, index=None, thumbnail=None):
        """添加单个图片到列表，index=0 表示插入到顶部"""
        if not os.path.exists(path):
            return
            
        item = QListWidgetItem(os.path.basename(path))
        
        if thumbnail:
            # 使用预生成的缩略图 (QImage -> QPixmap)
            item.setIcon(QIcon(QPixmap.fromImage(thumbnail)))
        else:
            # V3.3: 使用可见的灰色占位符，让用户知道正在加载
            pix = QPixmap(128, 128)
            pix.fill(Qt.GlobalColor.lightGray)
            # 绘制加载提示
            from PyQt6.QtGui import QPainter, QColor
            painter = QPainter(pix)
            painter.setPen(QColor(100, 100, 100))
            painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "⏳")
            painter.end()
            item.setIcon(QIcon(pix))
            
        item.setData(Qt.ItemDataRole.UserRole, path)
        
        if index is not None:
            self.insertItem(index, item)
        else:
            self.addItem(item)
            
        # 如果是插入到顶部，可能需要滚动上去
        if index == 0:
            self.scrollToItem(item)
        
    def clear_list(self):
        self.clear()
        
    def _on_item_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        self.image_selected.emit(path)
