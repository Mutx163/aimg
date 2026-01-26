from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListView, 
                             QPushButton, QLabel, QFrame, QWidget, QLineEdit)

class ImageGalleryDialog(QDialog):
    """
    图片库展开视图弹窗，以大网格形式展示所有图片。
    """
    image_selected = pyqtSignal(str) # 当在画廊中选择图片时发出

    def __init__(self, image_model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片库视图")
        self.resize(1000, 700)
        self.image_model = image_model
        
        self.setup_ui()
        # 安装事件过滤器，以便在 QListView 真正获得尺寸时进行调整
        self.list_view.viewport().installEventFilter(self)
        self._initial_adjusted = False
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        
        # 顶部栏：标题与搜索/关闭
        header = QHBoxLayout()
        title = QLabel("全部图片")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: palette(highlight);")
        header.addWidget(title)
        
        header.addStretch()
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("在库中搜索...")
        self.search_bar.setFixedWidth(250)
        self.search_bar.textChanged.connect(self._on_search)
        header.addWidget(self.search_bar)
        
        btn_close = QPushButton("关闭")
        btn_close.setFixedWidth(80)
        btn_close.clicked.connect(self.accept)
        header.addWidget(btn_close)
        
        layout.addLayout(header)
        
        # 图片网格列表
        self.list_view = QListView()
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setMovement(QListView.Movement.Static)
        self.list_view.setSpacing(10)
        self.list_view.setGridSize(QSize(160, 200)) # 略大于主界面的网格
        self.list_view.setIconSize(QSize(140, 140))
        self.list_view.setWordWrap(True)
        
        # 复用主界面的 Model
        self.list_view.setModel(self.image_model)
        
        # 样式 - 保持与主界面一致
        self.list_view.setStyleSheet("""
            QListView {
                background-color: palette(base);
                border: 1px solid palette(midlight);
                border-radius: 4px;
                padding: 0px;
            }
            QListView::item {
                border: 1px solid transparent;
                border-radius: 4px;
            }
            QListView::item:hover {
                background-color: palette(alternate-base);
            }
            QListView::item:selected {
                background-color: palette(highlight);
                color: white;
            }
        """)
        
        self.list_view.clicked.connect(self._on_item_clicked)
        # 初始状态隐藏，直到对齐计算完成（可选，使视觉更平滑）
        # self.list_view.setOpacity(0) 
        layout.addWidget(self.list_view)
        
        # 底部信息
        self.info_label = QLabel(f"共 {self.image_model.rowCount()} 张图片")
        self.info_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.info_label)

    def _on_item_clicked(self, index):
        if index.isValid():
            path = self.image_model.get_path(index.row())
            if path:
                self.image_selected.emit(path)
                # 用户点击后跳转并保持弹窗开启，还是直接关闭？
                # 按照一般逻辑，展开视图是为了寻找图片，找到后点击跳转，弹窗可以保留也可以关闭。
                # 简单起见，点击后跳转。
    
    def _on_search(self, text):
        pass

    def eventFilter(self, obj, event):
        """监听 viewport 的大小变化，解决初始显示宽度不准确的问题"""
        if obj == self.list_view.viewport() and event.type() == event.Type.Resize:
            # 当视口大小发生变化（包括第一次显示）时触发
            self._adjust_grid_size()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        """对话框本身大小变化时"""
        super().resizeEvent(event)
        # 这里的 super 已经会触发 list_view 的 resize，进而触发 eventFilter
        # 但为了双重保险，也可以手动调用一次
        self._adjust_grid_size()

    def _adjust_grid_size(self):
        """计算并设置网格大小，消除右侧缝隙"""
        if not hasattr(self, 'list_view'):
            return
            
        width = self.list_view.viewport().width()
        if width <= 0:
            return
            
        # 获取视口真实宽度
        viewport_width = self.list_view.viewport().width()
        if viewport_width <= 20: # 过滤掉极小的初始伪尺寸
            return
            
        # 最小网格宽度
        min_cell_width = 160
        spacing = 4 
        self.list_view.setSpacing(spacing)
        
        # 计算每行理想列数
        cols = max(1, (viewport_width - spacing) // (min_cell_width + spacing))
        
        # 计算每个项目应占用的实际宽度，使其完美填满总宽度
        # 逻辑：(视口总宽 - (列数+1)*间距) / 列数
        actual_cell_width = (viewport_width - (cols + 1) * spacing) // cols
        
        # 更新网格大小
        item_height = 210
        new_grid_size = QSize(int(actual_cell_width), item_height)
        
        # 只有在尺寸确实变化时才更新，避免无限递归
        if self.list_view.gridSize() != new_grid_size:
            self.list_view.setGridSize(new_grid_size)
            
            # 同时调整图标大小适配新宽度
            icon_padding = 16
            icon_w = actual_cell_width - icon_padding
            icon_h = 150
            self.list_view.setIconSize(QSize(int(icon_w), int(icon_h)))
