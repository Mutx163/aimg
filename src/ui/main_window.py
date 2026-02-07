
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QSplitter, QFileDialog, QToolBar, QMessageBox, 
                             QStatusBar, QLineEdit, QLabel, QTabWidget, QStackedWidget, 
                             QFrame, QComboBox, QPushButton, QAbstractSpinBox, QTextEdit, QApplication,
                             QToolButton, QMenu, QStyle,
                             QProgressBar, QSizePolicy)
from PyQt6.QtCore import Qt, QSize, QSettings, QTimer, QThread, QProcess, pyqtSignal, QUrl
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QImage, QDesktopServices
import time
import os
import webbrowser
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List

from src.core.watcher import FileWatcher
from src.core.database import DatabaseManager
from src.ui.widgets.image_viewer import ImageViewer
from src.ui.widgets.thumbnail_list import ThumbnailList
from src.ui.widgets.param_panel import ParameterPanel
from src.ui.widgets.model_explorer import ModelExplorer
from src.ui.widgets.comparison_view import ComparisonView
from src.core.comfy_client import ComfyClient
from src.ui.settings_dialog import SettingsDialog
from src.core.cache import ThumbnailCache
from src.ui.controllers.file_controller import FileController
from src.ui.controllers.search_controller import SearchController
from src.ui.dialogs.image_gallery_dialog import ImageGalleryDialog
from src.ui.dialogs.compare_popup_dialog import ComparePopupDialog
from src.services.web_server_service import WebServerService


@dataclass
class CompareSession:
    session_id: str
    name: str
    mode: str
    expected_count: int
    completed_count: int = 0
    variants: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    prompt_to_variant: Dict[str, str] = field(default_factory=dict)
    items: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class MainWindow(QMainWindow):
    COMPARE_LAST_SESSION_KEY = "compare_last_session_v1"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Image Viewer Pro")
        self.settings = QSettings("ComfyUIImageManager", "Settings")
        legacy_settings = QSettings("Antigravity", "AIImageViewer")
        legacy_keys = legacy_settings.allKeys()
        if legacy_keys:
            for key in legacy_keys:
                if not self.settings.contains(key):
                    self.settings.setValue(key, legacy_settings.value(key))
            self.settings.sync()
        
        # 恢复窗口状态 (优先恢复几何形状)
        if not self.settings.value("window/geometry"):
            self.resize(1600, 900)
        
        # 状态数据
        self.current_folder = None
        self.current_model = "ALL"
        self.current_lora = "ALL"
        self.compare_dialog = None
        self.last_compare_session: CompareSession | None = None
        self.compare_sessions: Dict[str, CompareSession] = {}
        self._load_last_compare_session()
        
        # 初始化数据库与缓存
        self.db_manager = DatabaseManager()
        self.thumb_cache = ThumbnailCache()
        
        # 核心组件初始化
        self.watcher = FileWatcher()
        self.current_sort_by = self.settings.value("sort_by", "time_desc")
        self._is_scanning = False # 扫描状态锁
        
        # 控制器初始化
        self.search_controller = SearchController(self)
        self.file_controller = FileController(self)

        # Web 服务控制（按需启动）
        self.web_service = WebServerService()
        self.web_service.service_ready.connect(self._on_web_service_ready)
        self.web_service.service_stopped.connect(self._on_web_service_stopped)
        self.web_service.log_message.connect(self._on_web_service_log)
        self._web_last_url = None
        
        # 连接监控信号 (需在控制器初始化后)
        self.watcher.get_signal().connect(lambda p: self.file_controller.on_new_image_detected(p))
        
        self.setup_ui()
        self.apply_theme()
        
        # 恢复窗口状态
        # 优先恢复几何形状（窗口位置和大小）
        saved_geometry = self.settings.value("window/geometry")
        if saved_geometry:
            self.restoreGeometry(saved_geometry)
            print(f"[Window] 已恢复窗口几何形状")
        
        # 恢复分割器状态（面板宽度比例）
        saved_main_splitter = self.settings.value("window/main_splitter")
        if saved_main_splitter:
            self.splitter.restoreState(saved_main_splitter)
            print(f"[Window] 已恢复主分割器状态")
        
        saved_left_splitter = self.settings.value("window/left_splitter")
        if saved_left_splitter:
            self.left_splitter.restoreState(saved_left_splitter)
            print(f"[Window] 已恢复左侧分割器状态")
            
        # 安装全局事件过滤器以捕获所有键盘事件
        # 必须安装在 QApplication 上才能捕获所有窗口的事件
        QApplication.instance().installEventFilter(self)
        
        # 初始化 ComfyUI 客户端
        self.comfy_client = ComfyClient(self.settings.value("comfy_address", "127.0.0.1:8188"))
        self.comfy_client.status_changed.connect(lambda msg: self.statusBar().showMessage(f"[Comfy] {msg}", 3000))
        self.comfy_client.progress_updated.connect(self._on_comfy_progress)
        self.comfy_client.prompt_submitted.connect(self._on_prompt_submitted)
        
        # 绑定模型列表获取信号
        self.comfy_client.models_fetched.connect(lambda models: self.param_panel.set_available_models(models))
        
        self.comfy_client.connect_server()
        # 尝试获取可用模型
        QTimer.singleShot(1000, self.comfy_client.fetch_available_models)
        
        # 监听队列状态以更新右下角计数
        self.comfy_client.queue_updated.connect(self._update_queue_button)
        self._has_realtime_progress = False
        self.queue_sync_timer = QTimer(self)
        self.queue_sync_timer.setInterval(1000)
        self.queue_sync_timer.timeout.connect(self.comfy_client.get_queue)
        # 初始获取一次队列
        QTimer.singleShot(2000, self.comfy_client.get_queue)
        
        # 绑定参数面板的远程生成请求
        self.param_panel.remote_gen_requested.connect(self.on_remote_gen_requested)
        self.param_panel.compare_generate_requested.connect(self.on_compare_generate_requested)
        self.comfy_client.execution_start.connect(self._on_comfy_node_start)
        self.comfy_client.execution_done.connect(self._on_comfy_done)
        self.comfy_client.prompt_submitted_with_context.connect(self._on_prompt_submitted_with_context)
        self.comfy_client.prompt_executed_images.connect(self._on_prompt_executed_images)
        
        # 日志系统:使用定时器轮询param_panel的日志列表
        self.log_poll_timer = QTimer(self)
        self.log_poll_timer.timeout.connect(self._poll_logs)
        self.log_poll_timer.start(500)  # 每500ms检查一次新日志
        self.last_log_count = 0  # 记录上次已处理的日志数量

        # 图片选择同步定时器 (解决快速切换不跟手 bug)
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.timeout.connect(self._sync_image_selection)
        self._pending_selection_path = None
        self._last_selection_time = 0

        
        # 将恢复流程延后到事件循环启动后，优先显示首屏。
        QTimer.singleShot(0, self._restore_last_session)

    def _restore_last_session(self):
        """在首屏显示后恢复上次文件夹与相关状态。"""
        # 如果用户已主动选择过文件夹，则跳过自动恢复。
        if self.current_folder:
            return

        last_folder = self.settings.value("last_folder")
        if not (last_folder and os.path.exists(last_folder)):
            return

        self.current_folder = last_folder
        self.file_controller.load_folder(last_folder)

        # 这些查询可能较慢，统一放在首屏之后执行。
        self._load_historical_resolutions()
        self._load_historical_samplers()
        self._load_historical_schedulers()

        watch_recursive = self.settings.value("watch_recursive", False, type=bool)
        if self.watcher.start_monitoring(last_folder, recursive=watch_recursive):
            mode = "递归" if watch_recursive else "非递归"
            self.statusBar().showMessage(f"正在监控(上次位置): {last_folder} ({mode})")



    def setup_ui(self):
        # 1. 工具栏 - Windows 原生风格
        self.top_toolbar = QToolBar("Main Toolbar")
        toolbar = self.top_toolbar
        toolbar.setObjectName("TopToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        
        # 顶栏仅保留功能菜单，避免与系统标题栏形成“双标题”视觉。

        def add_menu_button(title: str, menu: QMenu) -> QToolButton:
            btn = QToolButton(self)
            btn.setObjectName("TopBarMenuButton")
            btn.setText(title)
            btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            btn.setMenu(menu)
            toolbar.addWidget(btn)
            return btn

        file_menu = QMenu(self)
        file_menu.addAction("打开文件夹", self.select_folder)
        file_menu.addAction("刷新列表", self.refresh_folder)
        file_menu.addSeparator()
        file_menu.addAction("打开输出文件夹", self.open_output_folder)
        file_menu.addAction("打开 LoRA 文件夹", self.open_lora_folder)
        file_menu.addSeparator()
        file_menu.addAction("设置", self.open_settings)
        self.file_menu_btn = add_menu_button("文件", file_menu)

        view_menu = QMenu(self)
        self.action_compare = QAction("打开对比弹窗", self)
        self.action_compare.triggered.connect(self.open_compare_popup)
        view_menu.addAction(self.action_compare)
        view_menu.addAction("图片画廊", self.show_image_gallery)
        self.view_menu_btn = add_menu_button("查看", view_menu)

        self._zoom_options = [
            ("适应窗口", "fit"),
            ("铺满窗口", "fill"),
            ("100% 原始大小", "1.0"),
            ("50%", "0.5"),
            ("200%", "2.0"),
            ("400%", "4.0"),
        ]
        self.current_zoom_mode = self.settings.value("zoom_mode", "fit", type=str)
        self.zoom_menu = QMenu(self)
        self.zoom_action_group = QActionGroup(self)
        self.zoom_action_group.setExclusive(True)
        self.zoom_actions = {}
        for label, value in self._zoom_options:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, v=value: self._set_zoom_mode(v))
            self.zoom_action_group.addAction(act)
            self.zoom_menu.addAction(act)
            self.zoom_actions[value] = act
        self.zoom_menu_btn = add_menu_button("缩放", self.zoom_menu)
        self._set_zoom_mode(self.current_zoom_mode, apply=False)

        self._sort_options = [
            ("时间倒序 (最新在前)", "time_desc"),
            ("时间正序 (最旧在前)", "time_asc"),
            ("名称 A-Z", "name_asc"),
            ("名称 Z-A", "name_desc"),
        ]
        self.sort_menu = QMenu(self)
        self.sort_action_group = QActionGroup(self)
        self.sort_action_group.setExclusive(True)
        self.sort_actions = {}
        for label, value in self._sort_options:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, v=value: self._set_sort_mode(v))
            self.sort_action_group.addAction(act)
            self.sort_menu.addAction(act)
            self.sort_actions[value] = act
        self.sort_menu_btn = add_menu_button("排序", self.sort_menu)
        self._set_sort_mode(self.current_sort_by, trigger_search=False)

        toolbar.addSeparator()
        toolbar_spacer = QWidget()
        toolbar_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(toolbar_spacer)

        tool_menu = QMenu(self)
        self.action_web = QAction("启动 Web", self)
        self.action_web.triggered.connect(self.toggle_web_service)
        tool_menu.addAction(self.action_web)
        self.tool_menu_btn = add_menu_button("服务", tool_menu)
        
        self.addToolBar(toolbar)
        
        # 5. 状态栏 (终极一体化功能区 - 物理锁定在最右侧)
        status_bar = self.statusBar()
        
        # 强制清理状态栏，防止有幽灵控件残留
        for child in status_bar.findChildren(QWidget):
            status_bar.removeWidget(child)
            
        # 创建一个坚实的原子容器（这就是右侧唯一的盒子）
        self.right_status_box = QFrame()
        self.right_status_box.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        box_lay = QHBoxLayout(self.right_status_box)
        box_lay.setContentsMargins(0, 0, 5, 0) # 右侧留一点缝隙
        box_lay.setSpacing(4) # 再次缩小间距，确保紧凑
        # 移除 box_lay.addStretch()，依靠 addPermanentWidget 自动靠右
        
        # --- 日志按钮 ---
        self.log_btn = QPushButton("📜 日志")
        self.log_btn.setFixedWidth(60)
        self.log_btn.setFixedHeight(22)
        self.log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_btn.clicked.connect(self._show_log_dialog)
        self.log_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid palette(mid);
                border-radius: 4px;
                color: palette(text);
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: palette(midlight);
                border-color: palette(highlight);
            }
        """)
        box_lay.addWidget(self.log_btn)

        # --- 进度组 (容器内并排放置 Bar 和 取消按钮) ---
        from PyQt6.QtWidgets import QGridLayout
        self.progress_container = QWidget()
        self.progress_container.setVisible(False)
        self.progress_container.setFixedWidth(200) # 回归 200px 宽度
        prog_lay = QGridLayout(self.progress_container) # 回归叠加布局
        prog_lay.setContentsMargins(0, 0, 0, 0)
        prog_lay.setSpacing(0)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setFixedWidth(200) 
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter) 
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid palette(mid);
                border-radius: 4px;
                text-align: center;
                background-color: palette(alternate-base);
                color: #000000; 
                font-weight: bold;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #ff4d00;
                border-radius: 3px;
            }
        """)
        prog_lay.addWidget(self.progress_bar, 0, 0)
        
        self.interrupt_btn = QPushButton("✕")
        self.interrupt_btn.setFixedWidth(24) 
        self.interrupt_btn.setFixedHeight(18)
        self.interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.interrupt_btn.clicked.connect(lambda: self.comfy_client.interrupt_current())
        self.interrupt_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #000000; /* 高对比度纯黑，无背景方块 */
                font-weight: 900;
                font-size: 13px;
                text-align: center;
                padding-right: 5px;
            }
            QPushButton:hover { color: #ff4d00; }
        """)
        prog_lay.addWidget(self.interrupt_btn, 0, 0, Qt.AlignmentFlag.AlignRight)
        self.interrupt_btn.raise_()
        
        box_lay.addWidget(self.progress_container)
        
        # --- 队列按钮 ---
        self.queue_btn = QPushButton("📋 队列")
        self.queue_btn.setFixedWidth(85) # 恢复到较窄的宽度，平衡审美与可见性
        self.queue_btn.setFixedHeight(22)
        self.queue_btn.clicked.connect(self._show_queue_dialog)
        box_lay.addWidget(self.queue_btn)
        
        # 将整个容器作为一个原子级的 PermanentWidget 添加到右侧
        status_bar.addPermanentWidget(self.right_status_box)

        # 6. 中央分割器设置 (恢复被意外删除的部分)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(2) # 细分割线
        self.splitter.setChildrenCollapsible(False) # 禁止折叠
        self.splitter.setFocusPolicy(Qt.FocusPolicy.NoFocus) # 禁止获得焦点
        self.setCentralWidget(self.splitter)
        
        # 左侧列表面板 (增加搜索框)
        left_widget = QWidget()
        left_widget.setMinimumWidth(320)
        left_widget.setMaximumWidth(340) # 限制最大宽度，防止右侧出现过多空白 (适配 140x190 网格双列)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(8, 8, 8, 0)
        left_layout.setSpacing(6)
        
        # 搜索栏 + 重置按钮
        search_layout = QHBoxLayout()
        search_layout.setSpacing(4)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("🔍 搜索提示词/模型/文件名...")
        self.search_bar.textChanged.connect(self.search_controller.on_search_changed)
        search_layout.addWidget(self.search_bar)
        
        btn_gallery = QPushButton("展开图库")
        btn_gallery.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_gallery.setToolTip("展开全屏图库浏览")
        btn_gallery.setFixedWidth(70)
        btn_gallery.clicked.connect(self.show_image_gallery)
        search_layout.addWidget(btn_gallery)
        
        btn_reset = QPushButton("Reset")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.setToolTip("Reset Filters")
        btn_reset.setObjectName("GhostButton")
        btn_reset.setMinimumWidth(60)
        btn_reset.clicked.connect(self.search_controller.reset_filters)
        search_layout.addWidget(btn_reset)
        
        left_layout.addLayout(search_layout)
        
        # 使用 QSplitter 整合“筛选区”和“图库列表”
        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.left_splitter.setHandleWidth(2)
        
        # 模型筛选器
        self.model_explorer = ModelExplorer()
        self.model_explorer.filter_requested.connect(self.search_controller.on_filter_requested)
        self.left_splitter.addWidget(self.model_explorer)
        
        # 缩略图图库
        self.thumbnail_list = ThumbnailList()
        self.thumbnail_list.image_selected.connect(self.on_image_selected)
        self.left_splitter.addWidget(self.thumbnail_list)
        
        self.left_splitter.setStretchFactor(0, 2)
        self.left_splitter.setStretchFactor(1, 8)
        
        left_layout.addWidget(self.left_splitter)
        self.splitter.addWidget(left_widget)
        
        # 中间：主展示区 (使用 Stack 进行单图/对比切换)
        self.view_stack = QStackedWidget()
        self.view_stack.setContentsMargins(0, 0, 0, 0)
        
        self.viewer = ImageViewer()
        self.viewer.navigate_request.connect(self.navigate_image)
        self.view_stack.addWidget(self.viewer)
        
        self.comparison_view = ComparisonView()
        self.comparison_view.navigate_request.connect(self.navigate_image)
        self.comparison_view.setContentsMargins(0, 0, 0, 0)
        self.view_stack.addWidget(self.comparison_view)
        
        self.splitter.addWidget(self.view_stack)
        
        self.param_panel = ParameterPanel()
        self.param_panel.setMinimumWidth(380)
        self.param_panel.setMaximumWidth(600)
        self.splitter.addWidget(self.param_panel)
        
        # 设置伸缩因子：只允许中间的内容区 (index 1) 随窗口缩放，左右侧边栏固定
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        
        # 设置 Splitter 初始比例
        if not self.settings.value("window/main_splitter"):
            self.splitter.setSizes([340, 860, 400])

    def resizeEvent(self, event):
        """窗口缩放时尝试消除空白"""
        super().resizeEvent(event)
        # 禁用自动布局调整，保持固定的splitter比例
        # self.auto_adjust_layout()

    def auto_adjust_layout(self):
        """
        动态调整左右面板宽度，使中间 Viewer 的比例尽可能贴合图片。
        """
        if self._is_scanning: return # 正在扫描时禁止布局自动调整，防止界面跳动
        try:
            if not hasattr(self, 'viewer') or self.viewer.pixmap_item.pixmap().isNull():
                return
        except (RuntimeError, AttributeError):
            return
            
        pix = self.viewer.pixmap_item.pixmap()
        img_ratio = pix.width() / pix.height()
        
        total_w = self.splitter.width()
        viewer_h = self.viewer.height()
        if viewer_h <= 0: return

        ideal_viewer_w = int(viewer_h * img_ratio)
        
        # 剩余给两个侧边栏的宽度
        available_side_w = total_w - ideal_viewer_w - self.splitter.handleWidth() * 2
        
        # 设置合理的侧边栏总宽度下限，确保功能可用
        if available_side_w < 260: 
            available_side_w = 260
            ideal_viewer_w = total_w - available_side_w - self.splitter.handleWidth() * 2
            
        # 尝试避开“尴尬宽度”：如果 side_w 刚好在 150-250 之间（容易产生大空白），
        # 我们可以稍微压缩一下 viewer (只要不太离谱)，以便侧边栏能干净地显示一列或两列。
        # 暂时先不做强制干预，看缩略图组件内优化后的效果。
            
        current_sizes = self.splitter.sizes()
        total_current_side = current_sizes[0] + current_sizes[2]
        if total_current_side > 0:
            left_ratio = current_sizes[0] / total_current_side
        else:
            left_ratio = 0.4
            
        left_w = int(available_side_w * left_ratio)
        right_w = available_side_w - left_w
        
        # 应用新比例，确保一次性到位
        # 加 1 像素冗余，确保覆盖可能存在的 Splitter 手柄接缝
        self.splitter.setSizes([left_w, ideal_viewer_w + 1, right_w])
        
        # 延迟一下强制 re-fit，确保 splitter 已经完成大小调整
        QTimer.singleShot(50, lambda: self.viewer.fit_to_window())

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择监控文件夹")
        if folder:
            self.current_folder = folder
            self.settings.setValue("last_folder", folder) # 保存设置
            self.file_controller.load_folder(folder)
            
            # 启动监控
            watch_recursive = self.settings.value("watch_recursive", False, type=bool)
            if self.watcher.start_monitoring(folder, recursive=watch_recursive):
                mode = "递归" if watch_recursive else "非递归"
                self.statusBar().showMessage(f"正在监控: {folder} ({mode})")
            else:
                self.statusBar().showMessage(f"监控失败: {folder}")

    def refresh_folder(self):
        """刷新当前文件夹 - 使用数据库查询而非重新扫描"""
        if self.current_folder:
            self.search_controller.perform_search()
            # 同时也刷新参数面板里的可用资源 (LoRA 等)
            self.param_panel._refresh_comfyui_assets()
            self.param_panel.refresh_lora_options()
            self.statusBar().showMessage("已刷新列表与可用资源", 2000)

    def _resolve_comfyui_models_root(self):
        base = self.settings.value("comfy_root", "", type=str).strip()
        if not base:
            return ""
        base_lower = os.path.basename(base).lower()
        if base_lower == "models":
            return base
        has_models_subdir = any(
            os.path.isdir(os.path.join(base, name))
            for name in ("checkpoints", "loras", "unet", "vae", "clip")
        )
        if has_models_subdir:
            return base
        models_dir = os.path.join(base, "models")
        if os.path.isdir(models_dir):
            return models_dir
        return base

    def _open_folder_in_system(self, path, label):
        if not path:
            QMessageBox.information(self, "路径未配置", f"请先在设置中配置{label}路径。")
            return
        target = os.path.normpath(path)
        if not os.path.isdir(target):
            QMessageBox.warning(self, "目录不存在", f"{label}目录不存在:\n{target}")
            return
        if QDesktopServices.openUrl(QUrl.fromLocalFile(target)):
            self.statusBar().showMessage(f"已打开{label}目录: {target}", 3000)
        else:
            QMessageBox.warning(self, "打开失败", f"无法打开目录:\n{target}")

    def open_lora_folder(self):
        models_root = self._resolve_comfyui_models_root()
        if not models_root:
            QMessageBox.information(self, "未配置 ComfyUI 目录", "请先在设置中配置 ComfyUI 目录。")
            return
        self._open_folder_in_system(os.path.join(models_root, "loras"), "LoRA")

    def open_output_folder(self):
        # 优先打开当前正在浏览/监控的图片目录，符合用户常用操作。
        if self.current_folder and os.path.isdir(self.current_folder):
            self._open_folder_in_system(self.current_folder, "图片输出")
            return

        comfy_root = self.settings.value("comfy_root", "", type=str).strip()
        if not comfy_root:
            QMessageBox.information(
                self,
                "未找到输出目录",
                "当前没有可用的图片目录。请先选择图片文件夹，或在设置中配置 ComfyUI 目录。",
            )
            return
        self._open_folder_in_system(os.path.join(comfy_root, "output"), "图片输出")

    def _load_historical_resolutions(self):
        """从数据库加载历史分辨率并更新到参数面板"""
        try:
            history_res = self.db_manager.get_unique_resolutions(self.current_folder)
            # 预设分辨率
            preset_res = [
                (512, 512), (768, 768), (1024, 1024),
                (512, 768), (768, 512),
                (1024, 768), (768, 1024),
            ]
            self.param_panel._populate_resolutions(preset_res, history_res)
            print(f"[UI] 已加载 {len(history_res)} 个历史分辨率")
        except Exception as e:
            print(f"[UI] 加载历史分辨率失败: {e}")

    def _load_historical_samplers(self):
        """从数据库加载历史采样器并更新到参数面板"""
        try:
            samplers = self.db_manager.get_unique_samplers(self.current_folder)
            self.param_panel._populate_samplers(samplers)
        except Exception as e:
            print(f"[UI] 加载历史采样器失败: {e}")
            self.param_panel._populate_samplers([])

    def _load_historical_schedulers(self):
        """从数据库加载历史调度器并更新到参数面板"""
        try:
            schedulers = self.db_manager.get_unique_schedulers(self.current_folder)
            self.param_panel._populate_schedulers(schedulers)
        except Exception as e:
            print(f"[UI] 加载历史调度器失败: {e}")
            self.param_panel._populate_schedulers([])

    def refresh_historical_params(self):
        """刷新历史分辨率、采样器和调度器列表"""
        if self.current_folder:
            self._load_historical_resolutions()
            self._load_historical_samplers()
            self._load_historical_schedulers()


    def on_remote_gen_requested(self, workflow, batch_count=1, randomize_seed=True):
        """处理远程生成请求 - 使用当前图片的workflow重新生成"""
        # 清空上一轮日志缓存
        self.last_gen_logs = ""
        self.last_log_count = 0
        
        # 随机模式每次提交自动随机；固定模式按工作区指定seed提交
        seed_mode_text = "随机种子" if randomize_seed else "固定种子"
        print(f"[Main] 远程生成: 使用当前图片的workflow（{seed_mode_text}） x{batch_count}")
        self.comfy_client.queue_current_prompt(workflow, batch_count, randomize_seed)
        self.statusBar().showMessage(f"已发送 {batch_count} 个生成请求到ComfyUI", 3000)
    def on_image_selected(self, path):
        """记录选中的图片路径，并启动同步定时器"""
        if not path: return
        
        self._pending_selection_path = path # 始终记录最后一次选中的路径
        
        # [Performance] 图片选择同步策略：
        # 1. 如果还在扫描中，使用较长的延迟减少 UI 负担
        # 2. 如果是正常浏览，使用极短延迟（50ms）或立即响应
        
        delay = 150 if self._is_scanning else 30
        
        curr_time = time.time()
        # 如果距离上次加载超过 300ms 且不处于扫描中，立即响应一次以保证手感
        if not self._is_scanning and (curr_time - self._last_selection_time > 0.3):
             self._sync_image_selection()
        elif not self._selection_timer.isActive():
             # Throttle Logic: Only start timer if not already running.
             # This ensures we process updates at regular intervals (defined by delay)
             # instead of delaying indefinitely while scrolling fast.
             self._selection_timer.start(delay)

    def _sync_image_selection(self):
        """执行实际的图片加载和参数解析"""
        path = self._pending_selection_path
        if not path or not os.path.exists(path):
            return
            
        # 记录本次加载时间
        self._last_selection_time = time.time()
        
        t0 = time.time()
        # 1. 核心图片显示
        self.viewer.load_image(path)
        
        # 2. 只有在单图模式下才重置缩放（对比模式由其自己管理）
        if self.view_stack.currentIndex() == 0:
            self._on_zoom_changed()
        
        # 3. 解析并显示参数 (优化：如果是扫描阶段，参数更新可以更慢)
        from src.core.metadata import MetadataParser
        meta = MetadataParser.parse_image(path)
        self.param_panel.update_info(meta)
        
        # print(f"[UI] 图片同步切换耗时: {(time.time() - t0) * 1000:.1f} ms -> {os.path.basename(path)}")
        
    def keyPressEvent(self, event):
        """处理全局快捷键"""
        if event.key() == Qt.Key.Key_Delete:
            self.file_controller.delete_current_image()
        elif event.key() == Qt.Key.Key_Left:
            self.navigate_image(-1)
        elif event.key() == Qt.Key.Key_Right:
            self.navigate_image(1)
        # 上下键通常由列表自己处理，但如果焦点在 Viewer，我们可以拦截
        # 简单起见，这里优先让 focused widget 处理，除非特定需求
        else:
            super().keyPressEvent(event)

    def delete_current_image(self):
        # 兼容旧代码调用，转发给 controller
        self.file_controller.delete_current_image()

    def navigate_image(self, delta):
        """切换图片: -1 上一张, 1 下一张"""
        count = self.thumbnail_list.count()
        if count == 0:
            return
            
        current_idx = self.thumbnail_list.currentIndex()
        current = current_idx.row() if current_idx.isValid() else -1
        
        if current < 0:
            current = 0
            
        # 计算新索引 (循环切换? 暂时不循环，到顶/底停止)
        new_index = current + delta
        if 0 <= new_index < count:
            self.thumbnail_list.setCurrentRow(new_index)
            path = self.thumbnail_list.image_model.get_path(new_index)
            self.on_image_selected(path)
        else:
            self.statusBar().showMessage("已经是第一张/最后一张了")

    def open_settings(self):
        dlg = SettingsDialog(self)
        old_addr = self.settings.value("comfy_address", "127.0.0.1:8188")
        old_root = self.settings.value("comfy_root", "")
        old_watch_recursive = self.settings.value("watch_recursive", False, type=bool)
        old_web_bind = str(self.settings.value("web_bind", "127.0.0.1")).strip()
        old_web_auth_code = str(self.settings.value("web_auth_code", "")).strip()
        if dlg.exec():
            # 重新应用主题以响应设置变化
            new_addr = self.settings.value("comfy_address", "127.0.0.1:8188")
            if new_addr != old_addr:
                self.comfy_client.server_address = new_addr
                self.comfy_client.connect_server()
            new_root = self.settings.value("comfy_root", "")
            if new_root != old_root and hasattr(self, "param_panel"):
                self.param_panel._refresh_comfyui_assets()
                self.param_panel.refresh_lora_options()
                if new_root:
                    self.statusBar().showMessage(f"ComfyUI 目录已更新: {new_root}", 3000)
            self.apply_theme()
            
            new_watch_recursive = self.settings.value("watch_recursive", False, type=bool)
            if new_watch_recursive != old_watch_recursive and self.current_folder:
                self.watcher.stop_monitoring()
                if self.watcher.start_monitoring(self.current_folder, recursive=new_watch_recursive):
                    mode = "递归" if new_watch_recursive else "非递归"
                    self.statusBar().showMessage(f"监控模式已更新: {mode}", 3000)

            new_web_bind = str(self.settings.value("web_bind", "127.0.0.1")).strip()
            new_web_auth_code = str(self.settings.value("web_auth_code", "")).strip()
            if (new_web_bind != old_web_bind or new_web_auth_code != old_web_auth_code) and self._is_web_running():
                self.statusBar().showMessage("Web 访问设置已变更，正在重启 Web 服务...", 3000)
                self.web_service.stop_server()
                self.web_service.start_server()

    def _poll_logs(self):
        """定时轮询param_panel的日志列表并更新UI"""
        from src.ui.widgets.param_panel import ParameterPanel
        
        current_log_count = len(ParameterPanel.generation_logs)
        if current_log_count > self.last_log_count:
            # 有新日志
            new_logs = ParameterPanel.generation_logs[self.last_log_count:]
            for log in new_logs:
                # 不需要再加时间戳,_log已经加过了
                if not hasattr(self, 'last_gen_logs'):
                    self.last_gen_logs = ""
                self.last_gen_logs += log + "\n"
            
            self.last_log_count = current_log_count
            
            # 如果日志窗口打开,实时更新
            if hasattr(self, 'log_dialog') and self.log_dialog.isVisible():
                self.log_text_edit.setPlainText(self.last_gen_logs)
                sb = self.log_text_edit.verticalScrollBar()
                sb.setValue(sb.maximum())
    
    def _append_log(self, msg: str):
        """追加日志到缓存"""
        # print(f"[MainWindow._append_log] 收到日志: {msg[:60]}...")
        
        if msg == "__CLEAR__":
            self.last_gen_logs = ""
            return
            
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.last_gen_logs += f"[{timestamp}] {msg}\n"
        
        # 如果日志窗口是打开的，实时更新内容
        if hasattr(self, 'log_dialog') and self.log_dialog.isVisible():
            self.log_text_edit.setPlainText(self.last_gen_logs)
            # 滚动到底部
            sb = self.log_text_edit.verticalScrollBar()
            sb.setValue(sb.maximum())
        else:
            if hasattr(self, 'log_dialog'):
                pass
            else:
                pass

    def _show_log_dialog(self):
        """显示生成日志弹窗 (非模态)"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QHBoxLayout
        
        # 如果已经创建且可见，刷新内容并激活
        if hasattr(self, 'log_dialog') and self.log_dialog.isVisible():
            # 刷新日志内容
            self.log_text_edit.setPlainText(self.last_gen_logs if self.last_gen_logs else "暂无日志...")
            # 滚动到底部
            sb = self.log_text_edit.verticalScrollBar()
            sb.setValue(sb.maximum())
            # 激活窗口
            self.log_dialog.raise_()
            self.log_dialog.activateWindow()
            return
            
        self.log_dialog = QDialog(self)
        self.log_dialog.setWindowTitle("最近一次生成日志")
        self.log_dialog.resize(600, 400)
        # 设置为非模态，允许点击主窗口
        self.log_dialog.setWindowModality(Qt.WindowModality.NonModal)
        
        layout = QVBoxLayout(self.log_dialog)
        
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setPlainText(self.last_gen_logs if self.last_gen_logs else "暂无日志...")
        self.log_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)
        
        layout.addWidget(self.log_text_edit)
        
        # 按钮区
        btn_layout = QHBoxLayout()
        
        btn_copy = QPushButton("📋 复制全部")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.last_gen_logs))
        btn_layout.addWidget(btn_copy)
        
        btn_layout.addStretch()
        
        btn_close = QPushButton("关闭")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.log_dialog.close)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
        
        self.log_dialog.show()

    def show_image_gallery(self):
        """显示全屏图片库弹窗"""
        dlg = ImageGalleryDialog(self.thumbnail_list.image_model, self)
        dlg.image_selected.connect(self._on_gallery_image_selected)
        dlg.compare_selected.connect(self._on_gallery_compare_selected)
        dlg.exec()

    def _on_gallery_image_selected(self, path):
        """处理画廊选中的图片：定位并加载"""
        # 在主列表中找到索引并选中
        for i in range(self.thumbnail_list.image_model.rowCount()):
            if self.thumbnail_list.image_model.get_path(i) == path:
                self.thumbnail_list.setCurrentRow(i)
                break
        self.on_image_selected(path)

    def _on_gallery_compare_selected(self, paths):
        self.open_compare_popup(paths=paths, title="图库手动对比")

    def _compare_session_to_dict(self, session: CompareSession) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "name": session.name,
            "mode": session.mode,
            "expected_count": int(session.expected_count),
            "completed_count": int(session.completed_count),
            "variants": session.variants,
            "prompt_to_variant": session.prompt_to_variant,
            "items": session.items,
            "saved_at": int(time.time()),
        }

    def _compare_session_from_dict(self, data: Dict[str, Any]) -> CompareSession | None:
        try:
            session_id = str(data.get("session_id") or "")
            if not session_id:
                return None
            session = CompareSession(
                session_id=session_id,
                name=str(data.get("name") or "对比会话"),
                mode=str(data.get("mode") or "generate"),
                expected_count=int(data.get("expected_count") or 0),
                completed_count=int(data.get("completed_count") or 0),
            )
            session.variants = dict(data.get("variants") or {})
            session.prompt_to_variant = dict(data.get("prompt_to_variant") or {})
            items = dict(data.get("items") or {})
            # 兜底修复 item 结构
            normalized_items: Dict[str, Dict[str, Any]] = {}
            for variant_id, item in items.items():
                if not isinstance(item, dict):
                    continue
                normalized_items[str(variant_id)] = {
                    "variant_id": str(item.get("variant_id") or variant_id),
                    "status": str(item.get("status") or "queued"),
                    "path": item.get("path"),
                    "label": str(item.get("label") or variant_id),
                    "meta": item.get("meta") if isinstance(item.get("meta"), dict) else {},
                }
            session.items = normalized_items
            if session.expected_count <= 0:
                session.expected_count = len(session.items)
            if session.completed_count < 0:
                session.completed_count = 0
            if session.completed_count > session.expected_count:
                session.completed_count = session.expected_count
            return session
        except Exception:
            return None

    def _save_last_compare_session(self):
        if not self.last_compare_session:
            self.settings.remove(self.COMPARE_LAST_SESSION_KEY)
            return
        try:
            payload = self._compare_session_to_dict(self.last_compare_session)
            self.settings.setValue(self.COMPARE_LAST_SESSION_KEY, json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            print(f"[Compare] 保存最近会话失败: {e}")

    def _load_last_compare_session(self):
        raw = self.settings.value(self.COMPARE_LAST_SESSION_KEY, "", type=str)
        if not raw:
            return
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return
            session = self._compare_session_from_dict(data)
            if not session:
                return
            self.last_compare_session = session
            self.compare_sessions[session.session_id] = session
        except Exception as e:
            print(f"[Compare] 加载最近会话失败: {e}")

    def _ensure_compare_dialog(self) -> ComparePopupDialog:
        if not self.compare_dialog:
            self.compare_dialog = ComparePopupDialog(self)
        return self.compare_dialog

    def _get_latest_gallery_image_path(self) -> str:
        model = getattr(self.thumbnail_list, "image_model", None)
        if model is None:
            return ""
        latest_path = ""
        latest_mtime = -1.0
        try:
            count = int(model.rowCount())
        except Exception:
            return ""

        for idx in range(count):
            try:
                path = model.get_path(idx)
            except Exception:
                continue
            if not path or not os.path.exists(path):
                continue
            try:
                mtime = float(os.path.getmtime(path))
            except OSError:
                continue
            if mtime >= latest_mtime:
                latest_mtime = mtime
                latest_path = path
        return latest_path

    def _get_latest_gallery_image_ratio(self) -> float | None:
        latest_path = self._get_latest_gallery_image_path()
        if not latest_path:
            return None
        image = QImage(latest_path)
        if image.isNull() or image.height() <= 0:
            return None
        return float(image.width()) / float(image.height())

    def _apply_compare_default_ratio(self, dlg: ComparePopupDialog | None = None) -> None:
        target = dlg if dlg is not None else self.compare_dialog
        if target is None:
            return
        ratio = self._get_latest_gallery_image_ratio()
        target.set_preferred_aspect_ratio(ratio)

    def _session_items_as_list(self, session: CompareSession) -> List[Dict[str, Any]]:
        return [session.items[k] for k in session.items.keys()]

    def _refresh_compare_dialog_for_session(self, session: CompareSession) -> None:
        dlg = self._ensure_compare_dialog()
        self._apply_compare_default_ratio(dlg)
        dlg.set_session(
            {
                "name": session.name,
                "expected_count": session.expected_count,
                "completed_count": session.completed_count,
                "mode": session.mode,
            }
        )
        dlg.set_items(self._session_items_as_list(session))

    def _remember_manual_compare_session(self, paths: List[str], title: str) -> None:
        session_id = f"manual_{int(time.time() * 1000)}"
        session = CompareSession(
            session_id=session_id,
            name=title,
            mode="manual",
            expected_count=len(paths),
            completed_count=len(paths),
        )
        for idx, path in enumerate(paths):
            variant_id = f"manual_{idx}"
            item = {
                "variant_id": variant_id,
                "status": "done",
                "path": path,
                "label": os.path.basename(path) if path else f"图{idx + 1}",
                "meta": {"manual": True},
            }
            session.items[variant_id] = item
            session.variants[variant_id] = {"label": item["label"]}
        self.compare_sessions[session_id] = session
        self.last_compare_session = session
        self._save_last_compare_session()

    def open_compare_popup(self, checked: bool = False, paths: List[str] | None = None, title: str | None = None):
        if paths:
            valid_paths = [p for p in paths if p and os.path.exists(p)]
            if len(valid_paths) < 2:
                QMessageBox.information(self, "提示", "可对比图片少于 2 张。")
                return
            dlg = self._ensure_compare_dialog()
            self._apply_compare_default_ratio(dlg)
            session_title = title or "手动对比"
            dlg.open_with_paths(valid_paths, title=session_title)
            self._remember_manual_compare_session(valid_paths, session_title)
            return

        if self.last_compare_session:
            session = self.last_compare_session
            self._refresh_compare_dialog_for_session(session)
            dlg = self._ensure_compare_dialog()
            self._apply_compare_default_ratio(dlg)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return

        indexes = self.thumbnail_list.selectionModel().selectedIndexes() if self.thumbnail_list.selectionModel() else []
        selected_paths = []
        for idx in indexes:
            if idx.isValid():
                path = self.thumbnail_list.image_model.get_path(idx.row())
                if path:
                    selected_paths.append(path)

        if len(selected_paths) >= 2:
            self.open_compare_popup(paths=selected_paths, title="当前列表手动对比")
            return
        QMessageBox.information(self, "提示", "暂无可恢复会话。请先做一次 LoRA 对比生成或在图库中多选图片。")

    def on_compare_generate_requested(self, payload: Dict[str, Any]):
        action = str(payload.get("action") or "")
        if action == "open_last":
            self.open_compare_popup()
            return
        if action != "start":
            return

        workflows = payload.get("workflows") or []
        contexts = payload.get("contexts") or []
        variants = payload.get("variants") or []
        session_id = str(payload.get("session_id") or "")
        session_name = str(payload.get("session_name") or "LoRA对比")
        expected_count = int(payload.get("expected_count") or len(workflows))
        if not session_id or not workflows:
            QMessageBox.warning(self, "提交失败", "对比任务数据不完整。")
            return

        session = CompareSession(
            session_id=session_id,
            name=session_name,
            mode="generate",
            expected_count=expected_count,
            completed_count=0,
        )

        for variant in variants:
            variant_id = str(variant.get("variant_id") or "")
            if not variant_id:
                continue
            label = str(variant.get("label") or variant_id)
            session.variants[variant_id] = variant
            session.items[variant_id] = {
                "variant_id": variant_id,
                "status": "queued",
                "path": None,
                "label": label,
                "meta": {
                    "seed": variant.get("seed"),
                    "seed_mode": variant.get("seed_mode"),
                    "lora_name": variant.get("lora_name"),
                    "lora_weight": variant.get("lora_weight"),
                    "is_baseline": bool(variant.get("is_baseline", False)),
                },
            }

        self.compare_sessions[session_id] = session
        self.last_compare_session = session
        self._save_last_compare_session()
        self._refresh_compare_dialog_for_session(session)
        self.open_compare_popup()

        self.comfy_client.submit_workflow_batch(workflows, contexts)
        self.statusBar().showMessage(f"已提交 LoRA 对比任务: {expected_count} 个", 5000)

    def _on_prompt_submitted_with_context(self, prompt_id: str, context: Dict[str, Any]):
        session_id = str(context.get("session_id") or "")
        variant_id = str(context.get("variant_id") or "")
        session = self.compare_sessions.get(session_id)
        if not session or not variant_id:
            return

        session.prompt_to_variant[prompt_id] = variant_id
        item = session.items.get(variant_id)
        if not item:
            return
        if item.get("status") == "queued":
            item["status"] = "submitted"
        self._save_last_compare_session()

        if self.compare_dialog:
            self.compare_dialog.upsert_item(
                variant_id=variant_id,
                status=item.get("status", "submitted"),
                path=item.get("path"),
                label=item.get("label"),
                meta=item.get("meta"),
            )
            self.compare_dialog.set_session(
                {
                    "name": session.name,
                    "expected_count": session.expected_count,
                    "completed_count": session.completed_count,
                    "mode": session.mode,
                }
            )

    def _resolve_comfy_image_path(self, image_info: Dict[str, Any]) -> str:
        filename = str(image_info.get("filename") or "")
        if not filename:
            return ""
        subfolder = str(image_info.get("subfolder") or "")
        img_type = str(image_info.get("type") or "output")
        comfy_root = str(self.settings.value("comfy_root", "", type=str) or "").strip()

        candidates = []
        if comfy_root:
            candidates.append(os.path.normpath(os.path.join(comfy_root, img_type, subfolder, filename)))
            candidates.append(os.path.normpath(os.path.join(comfy_root, "output", subfolder, filename)))
            if os.path.basename(comfy_root).lower() == "models":
                root_parent = os.path.dirname(comfy_root)
                candidates.append(os.path.normpath(os.path.join(root_parent, "output", subfolder, filename)))
                candidates.append(os.path.normpath(os.path.join(root_parent, img_type, subfolder, filename)))
        if self.current_folder:
            candidates.append(os.path.normpath(os.path.join(self.current_folder, subfolder, filename)))
            candidates.append(os.path.normpath(os.path.join(self.current_folder, filename)))

        for path in candidates:
            if path and os.path.exists(path):
                return path
        return candidates[0] if candidates else ""

    def _set_compare_item_done(
        self,
        session: CompareSession,
        variant_id: str,
        path: str,
        unresolved: bool = False
    ) -> None:
        item = session.items.get(variant_id)
        if not item:
            return

        if item.get("status") != "done":
            session.completed_count += 1
        item["status"] = "done"
        if path and os.path.exists(path):
            item["path"] = path
        if unresolved:
            item["label"] = f"{item.get('label', variant_id)} (结果未定位)"
        self._save_last_compare_session()

        if self.compare_dialog:
            self.compare_dialog.upsert_item(
                variant_id=variant_id,
                status=item["status"],
                path=item.get("path"),
                label=item.get("label"),
                meta=item.get("meta"),
            )
            self.compare_dialog.set_session(
                {
                    "name": session.name,
                    "expected_count": session.expected_count,
                    "completed_count": session.completed_count,
                    "mode": session.mode,
                }
            )

    def _resolve_compare_image_with_retry(
        self,
        session_id: str,
        variant_id: str,
        image_info: Dict[str, Any],
        retry: int = 0
    ) -> None:
        session = self.compare_sessions.get(session_id)
        if not session:
            return
        path = self._resolve_comfy_image_path(image_info)
        if path and os.path.exists(path):
            self._set_compare_item_done(session, variant_id, path, unresolved=False)
            return
        if retry < 3:
            QTimer.singleShot(
                500 * (retry + 1),
                lambda: self._resolve_compare_image_with_retry(session_id, variant_id, image_info, retry + 1),
            )
            return
        self._set_compare_item_done(session, variant_id, path, unresolved=True)

    def _on_prompt_executed_images(self, prompt_id: str, images: List[Dict[str, Any]], context: Dict[str, Any]):
        session_id = str(context.get("session_id") or "")
        variant_id = str(context.get("variant_id") or "")
        session = self.compare_sessions.get(session_id)
        if not session:
            return
        if not variant_id:
            variant_id = session.prompt_to_variant.get(prompt_id, "")
        if not variant_id:
            return
        if not images:
            return
        image_info = images[0]
        self._resolve_compare_image_with_retry(session_id, variant_id, image_info, retry=0)

    def apply_theme(self):
        """应用界面主题 (Windows 11 Fluent Design 风格)"""
        theme = self.settings.value("theme", "dark")
        
        # 定义 Fluent 变量
        if theme == "dark":
            colors = {
                "bg_main": "#1c1c1c",        # Mica 深色背景模拟
                "bg_sidebar": "#202020",
                "bg_card": "#2b2b2b",
                "bg_hover": "#323232",
                "bg_pressed": "#2d2d2d",
                "text_main": "#ffffff",
                "text_secondary": "#a1a1a1",
                "accent": "#60cdff",          # Win11 默认蓝色高亮
                "border": "#3c3c3c",
                "separator": "#333333",
                # VSCode-like top bar tokens
                "topbar_bg": "#2d2d30",
                "topbar_text": "#cccccc",
                "topbar_text_active": "#ffffff",
                "topbar_hover": "#37373d",
                "topbar_pressed": "#3e3e42",
                "topbar_checked": "#094771",
                "topbar_border": "#3c3c3c",
                "topbar_accent": "#007acc",
            }
        else:
            colors = {
                "bg_main": "#f3f3f3",        # Mica 浅色背景模拟
                "bg_sidebar": "#ebebeb",
                "bg_card": "#ffffff",
                "bg_hover": "#f9f9f9",
                "bg_pressed": "#f0f0f0",
                "text_main": "#000000",
                "text_secondary": "#5f5f5f",
                "accent": "#005a9e",
                "border": "#d2d2d2",
                "separator": "#e5e5e5",
                # VSCode-like top bar tokens (light)
                "topbar_bg": "#f3f3f3",
                "topbar_text": "#4b4b4b",
                "topbar_text_active": "#1f1f1f",
                "topbar_hover": "#e7e7e7",
                "topbar_pressed": "#dddddd",
                "topbar_checked": "#d6ebff",
                "topbar_border": "#d0d0d0",
                "topbar_accent": "#0066b8",
            }

        qss = f"""
            /* 全局基础设置 */
            QMainWindow, QWidget {{
                background-color: {colors['bg_main']};
                color: {colors['text_main']};
                font-family: "Segoe UI Variable Display", "Segoe UI", "PingFang SC", "Microsoft YaHei UI";
                font-size: 10pt;
            }}

            /* 分隔符 */
            QSplitter::handle {{
                background-color: transparent;
            }}
            QSplitter::handle:horizontal {{
                width: 1px;
                background-color: {colors['separator']};
            }}
            QSplitter::handle:vertical {{
                height: 1px;
                background-color: {colors['separator']};
            }}

            /* 顶栏工具区 (VSCode-like) */
            QToolBar#TopToolbar {{
                background-color: {colors['topbar_bg']};
                border: none;
                border-bottom: 1px solid {colors['topbar_border']};
                spacing: 2px;
                padding: 3px 8px;
                margin: 0;
            }}
            QToolBar#TopToolbar::separator {{
                width: 1px;
                margin: 5px 6px;
                background-color: {colors['topbar_border']};
            }}
            QToolBar#TopToolbar QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px 10px;
                min-height: 24px;
                color: {colors['topbar_text']};
                font-weight: 500;
            }}
            QToolBar#TopToolbar QToolButton:hover {{
                background-color: {colors['topbar_hover']};
                border-color: {colors['topbar_border']};
                color: {colors['topbar_text_active']};
            }}
            QToolBar#TopToolbar QToolButton:pressed {{
                background-color: {colors['topbar_pressed']};
            }}
            QToolBar#TopToolbar QToolButton:checked {{
                background-color: {colors['topbar_checked']};
                border-color: {colors['topbar_accent']};
                color: {colors['topbar_text_active']};
            }}
            QToolBar#TopToolbar QToolButton::menu-indicator {{
                subcontrol-origin: padding;
                subcontrol-position: right center;
                left: -4px;
            }}
            QToolBar#TopToolbar QToolButton#TopBarMenuButton {{
                padding-right: 18px;
            }}
            QToolBar#TopToolbar QComboBox {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['topbar_border']};
                border-radius: 4px;
                padding: 2px 24px 2px 8px;
                min-height: 24px;
                color: {colors['topbar_text_active']};
            }}
            QToolBar#TopToolbar QComboBox:hover {{
                border-color: {colors['topbar_accent']};
                background-color: {colors['topbar_hover']};
            }}
            QToolBar#TopToolbar QComboBox:focus {{
                border-color: {colors['topbar_accent']};
            }}
            QToolBar#TopToolbar QComboBox::drop-down {{
                border: none;
                width: 18px;
            }}
            QMenu {{
                background-color: {colors['topbar_bg']};
                border: 1px solid {colors['topbar_border']};
                padding: 4px 0;
            }}
            QMenu::item {{
                color: {colors['topbar_text']};
                padding: 6px 22px 6px 12px;
                margin: 0 4px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {colors['topbar_hover']};
                color: {colors['topbar_text_active']};
            }}
            QMenu::separator {{
                height: 1px;
                background: {colors['topbar_border']};
                margin: 4px 10px;
            }}

            /* 输入框 */
            QLineEdit {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['border']};
                border-bottom: 2px solid {colors['separator']}; /* 底部边框强调 */
                padding: 8px 12px;
                border-radius: 6px;
                color: {colors['text_main']};
            }}
            QLineEdit:focus {{
                border-bottom: 2px solid {colors['accent']};
                background-color: {colors['bg_hover']};
            }}
            QListView {{
                outline: none;
            }}
            QListView::item {{
                border: none;
                padding: 2px;
                border-radius: 6px;
            }}
            QListView::item:selected {{
                background-color: {colors['bg_card']};
                color: {colors['accent']};
            }}
            QListView::item:hover {{
                background-color: {colors['bg_hover']};
            }}

            /* 下拉框 */
            QComboBox {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['border']};
                border-radius: 6px;
                padding: 4px 10px;
                min-height: 24px;
            }}
            QComboBox:hover {{
                background-color: {colors['bg_hover']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}

            /* 状态栏 */
            QStatusBar {{
                background-color: {colors['bg_main']};
                color: {colors['text_secondary']};
                border-top: 1px solid {colors['separator']};
                padding: 2px 10px;
            }}

            /* 滚动条 - Win11 现代风格 */
            QScrollBar:vertical {{
                background: transparent;
                width: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {colors['border']};
                min-height: 30px;
                border-radius: 6px;
                margin: 2px 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {colors['text_secondary']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}

            /* 选项卡 */
            QTabWidget::pane {{
                border: 1px solid {colors['separator']};
                border-radius: 8px;
                background-color: {colors['bg_card']};
            }}
            QTabBar::tab {{
                background-color: transparent;
                padding: 8px 16px;
                margin: 2px;
                border-radius: 4px;
            }}
            QTabBar::tab:hover {{
                background-color: {colors['bg_hover']};
            }}
            QTabBar::tab:selected {{
                color: {colors['accent']};
                font-weight: bold;
                border-bottom: 2px solid {colors['accent']};
            }}

            /* 分组框 - 卡片化样式 */
            QGroupBox {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
                margin-top: 24px;
                padding: 16px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: {colors['text_secondary']};
            }}

            /* 参数面板特定样式 */
            QFrame#InfoCard {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
            }}
            QFrame#CardSeparator {{
                background-color: {colors['separator']};
                max-height: 1px;
            }}
            QLabel#LoraTag {{
                background-color: {colors['bg_hover']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                color: {colors['text_secondary']};
            }}
            QLabel#LoraTag:hover {{
                color: {colors['accent']};
                border-color: {colors['accent']};
            }}
            QLabel#FilterHint {{
                color: {colors['text_secondary']};
                font-size: 11px;
                padding: 2px 4px;
            }}
            QFrame#TextCard {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['border']};
                border-radius: 6px;
            }}
            
            /* 幽灵按钮 (透明背景，悬浮显色) */
            QPushButton#GhostButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: {colors['text_secondary']};
                font-size: 14px;
            }}
            QPushButton#GhostButton:hover {{
                background-color: {colors['bg_hover']};
                color: {colors['accent']};
            }}

            /* 按钮 */
            QPushButton {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 4px 12px;
                color: {colors['text_main']};
            }}
            QPushButton:hover {{
                background-color: {colors['bg_hover']};
                border: 1px solid {colors['accent']};
            }}
            QPushButton:pressed {{
                background-color: {colors['bg_pressed']};
            }}

            /* 下拉框修复 */
            QComboBox {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 4px 8px;
                color: {colors['text_main']};
            }}
            QComboBox:hover {{
                border-color: {colors['accent']};
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['accent']}; /* 使用主题色边框增加区分度 */
                selection-background-color: {colors['accent']};
                selection-color: white;
                outline: none;
                padding: 2px;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 28px; /* 增加项高度，更易点选 */
                padding-left: 8px;
            }}
        """
        self.setStyleSheet(qss)
        
        # 更新组件背景色
        bg_viewer = colors['bg_main']
        self.viewer.set_background_color(bg_viewer)
        self.comparison_view.viewer_left.set_background_color(bg_viewer)
        self.comparison_view.viewer_right.set_background_color(bg_viewer)

    def _zoom_label_for_mode(self, mode: str) -> str:
        for label, value in getattr(self, "_zoom_options", []):
            if value == mode:
                return label
        return "适应窗口"

    def _sort_label_for_mode(self, mode: str) -> str:
        for label, value in getattr(self, "_sort_options", []):
            if value == mode:
                return label
        return "时间倒序 (最新在前)"

    def _set_zoom_mode(self, mode: str, apply: bool = True):
        if mode not in {v for _, v in getattr(self, "_zoom_options", [])}:
            mode = "fit"
        self.current_zoom_mode = mode
        self.settings.setValue("zoom_mode", mode)
        if hasattr(self, "zoom_actions"):
            act = self.zoom_actions.get(mode)
            if act:
                act.setChecked(True)
        if hasattr(self, "zoom_menu_btn"):
            self.zoom_menu_btn.setText(f"缩放: {self._zoom_label_for_mode(mode)}")
        if apply:
            self._on_zoom_changed()

    def _set_sort_mode(self, sort_by: str, trigger_search: bool = True):
        if sort_by not in {v for _, v in getattr(self, "_sort_options", [])}:
            sort_by = "time_desc"
        self.current_sort_by = sort_by
        self.settings.setValue("sort_by", sort_by)
        if hasattr(self, "sort_actions"):
            act = self.sort_actions.get(sort_by)
            if act:
                act.setChecked(True)
        if hasattr(self, "sort_menu_btn"):
            self.sort_menu_btn.setText(f"排序: {self._sort_label_for_mode(sort_by)}")
        if trigger_search:
            self.search_controller.perform_search()

    def _on_zoom_changed(self, index=None):
        """处理缩放变化（兼容旧下拉和新菜单）"""
        data = getattr(self, "current_zoom_mode", "fit")
        if hasattr(self, "zoom_combo") and self.zoom_combo is not None and index is not None:
            legacy_data = self.zoom_combo.itemData(index)
            if legacy_data:
                data = legacy_data

        if data == "fit":
            self.viewer.fit_to_window()
        elif data == "fill":
            self.viewer.toggle_fill_mode()
        else:
            try:
                scale_val = float(data)
                self.viewer.fit_to_original()
                if scale_val != 1.0:
                    self.viewer.scale(scale_val, scale_val)
            except ValueError:
                pass

    def _on_sort_changed(self, index=None):
        """排序方式变更（兼容旧下拉和新菜单）"""
        sort_by = getattr(self, "current_sort_by", "time_desc")
        if hasattr(self, "sort_combo") and self.sort_combo is not None and index is not None:
            legacy_sort = self.sort_combo.itemData(index)
            if legacy_sort:
                sort_by = legacy_sort
        self._set_sort_mode(sort_by, trigger_search=True)

    # --- Web 服务控制 ---
    def _is_web_running(self) -> bool:
        return bool(self.web_service and self.web_service.process and
                    self.web_service.process.state() != QProcess.ProcessState.NotRunning)

    def toggle_web_service(self):
        """启动/停止 Web 服务"""
        if self._is_web_running():
            self.statusBar().showMessage("正在停止 Web 服务...")
            self.web_service.stop_server()
        else:
            self.statusBar().showMessage("正在启动 Web 服务...")
            try:
                self.web_service.start_server()
            except Exception as e:
                self.statusBar().showMessage(f"Web 服务启动失败: {e}", 5000)

    def _on_web_service_ready(self, url: str):
        self._web_last_url = url
        if hasattr(self, 'action_web'):
            self.action_web.setText("停止 Web")
        if hasattr(self, "tool_menu_btn"):
            self.tool_menu_btn.setText("服务*")
        if getattr(self.web_service, "remote_auth_enabled", False):
            code = getattr(self.web_service, "remote_access_code", "")
            self.statusBar().showMessage(f"Web 服务已启动: {url}  验证码: {code}", 12000)
        else:
            self.statusBar().showMessage(f"Web 服务已启动: {url}", 5000)

        if self.settings.value("web_auto_open_browser", True, type=bool):
            # 默认打开本机地址
            local_url = f"http://127.0.0.1:{self.web_service.port}"
            webbrowser.open(local_url)

    def _on_web_service_stopped(self):
        if hasattr(self, 'action_web'):
            self.action_web.setText("启动 Web")
        if hasattr(self, "tool_menu_btn"):
            self.tool_menu_btn.setText("服务")
        self.statusBar().showMessage("Web 服务已停止", 5000)

    def _on_web_service_log(self, msg: str):
        # 控制台输出，避免 UI 过于频繁刷屏
        print(msg)

    def on_selection_changed(self, selected, deselected):
        """当选择项改变时（用于对比模式自动触发）"""
        if hasattr(self, 'action_compare') and self.action_compare.isChecked():
            indexes = self.thumbnail_list.selectionModel().selectedIndexes()
            if len(indexes) == 2:
                p1 = self.thumbnail_list.image_model.get_path(indexes[0].row())
                p2 = self.thumbnail_list.image_model.get_path(indexes[1].row())
                self.comparison_view.load_images(p1, p2)
                if self.view_stack.currentIndex() != 1:
                    self.view_stack.setCurrentIndex(1)
                self.statusBar().showMessage(f"正在比对: {os.path.basename(p1)} 与 {os.path.basename(p2)}")

    def toggle_comparison_mode(self, checked):
        """进入/退出对比模式"""
        from PyQt6.QtWidgets import QAbstractItemView
        if checked:
            # 开启多选权限
            self.thumbnail_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.statusBar().showMessage("⚖ 对比模式已开启：请按住 Ctrl/Shift 选中 2 张图片，然后再次点击此按钮或双击。")
            
            # 获取当前选中的图片 (如果有)
            indexes = self.thumbnail_list.selectionModel().selectedIndexes()
            if len(indexes) >= 2:
                p1 = self.thumbnail_list.image_model.get_path(indexes[0].row())
                p2 = self.thumbnail_list.image_model.get_path(indexes[1].row())
                self.comparison_view.load_images(p1, p2)
                self.view_stack.setCurrentIndex(1)
                self.statusBar().showMessage(f"正在对比: {os.path.basename(p1)} vs {os.path.basename(p2)}")
            else:
                # 如果没选够，依然停留在单图视图，但允许开始多选
                self.view_stack.setCurrentIndex(0)
        else:
            # 恢复单选模式，彻底杜绝意外连选
            self.thumbnail_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.thumbnail_list.clearSelection() # 清理一下
            self.view_stack.setCurrentIndex(0)
            self.statusBar().showMessage("对比模式已关闭，恢复单选浏览。")

    def _show_queue_dialog(self):
        """显示队列管理对话框"""
        from src.ui.widgets.queue_dialog import QueueDialog
        
        if not hasattr(self, 'queue_dialog') or self.queue_dialog is None:
            self.queue_dialog = QueueDialog(self.comfy_client, self)
        
        self.queue_dialog.show()
        self.queue_dialog.raise_()
        self.queue_dialog.activateWindow()

    def _on_comfy_progress(self, current, total):
        """处理 ComfyUI 进度更新"""
        if hasattr(self, 'progress_bar'):
            self._has_realtime_progress = True
            # 确保处于确定进度状态
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setMaximum(total)
            
            # 确保子控件也是可见的
            self.progress_container.setVisible(True)
            self.interrupt_btn.raise_() # 确保每次重绘后都在最上层
            
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            self.progress_bar.setFormat(f"生成中... {current}/{total} (%p%)")

    def _on_prompt_submitted(self, prompt_id):
        """处理任务提交成功"""
        self.statusBar().showMessage(f"任务已提交: {prompt_id[:8]}...", 5000)
        # 如果队列窗口打开，刷新它
        if hasattr(self, 'queue_dialog') and self.queue_dialog and self.queue_dialog.isVisible():
            self.queue_dialog.refresh_queue()
        # 同时触发主界面的队列查询以更新计数
        self.comfy_client.get_queue()

    def _update_queue_button(self, data):
        """更新状态栏队列按钮的任务计数"""
        running = data.get('queue_running', [])
        pending = data.get('queue_pending', [])
        total = len(running) + len(pending)
        
        if total > 0:
            self.queue_btn.setText(f"📋 队列 ({total})")
            # 强化视觉反馈 (发现有任务时变色)
            self.queue_btn.setStyleSheet("""
                QPushButton {
                    background-color: palette(highlight);
                    color: white;
                    border: 1px solid palette(highlight);
                    font-weight: bold;
                }
            """)
        else:
            self.queue_btn.setText("📋 队列")
            self.queue_btn.setStyleSheet("") # 恢复默认样式

        if total > 0:
            if not self.queue_sync_timer.isActive():
                self.queue_sync_timer.start()
        else:
            if self.queue_sync_timer.isActive():
                self.queue_sync_timer.stop()
            self._has_realtime_progress = False
            if hasattr(self, 'progress_bar'):
                self.progress_container.setVisible(False)

        if len(running) > 0 and hasattr(self, 'progress_bar') and not self._has_realtime_progress:
            self.progress_container.setVisible(True)
            self.progress_bar.setMaximum(0)
            self.progress_bar.setFormat("正在恢复跟踪... 队列执行中")
            self.interrupt_btn.raise_()

    def _on_comfy_node_start(self, node_id, node_type):
        """处理节点开始执行"""
        if hasattr(self, 'progress_bar'):
            self._has_realtime_progress = True
            self.progress_container.setVisible(True)
            
            # 常用节点名称翻译
            node_map = {
                "CheckpointLoaderSimple": "加载模型",
                "LoraLoader": "加载 LoRA",
                "CLIPTextEncode": "解析提示词",
                "KSampler": "正在采样",
                "VAEDecode": "VAE 解码",
                "SaveImage": "保存图片",
                "EmptyLatentImage": "初始化画布",
                "ControlNetApply": "应用 ControlNet",
                "UpscaleModelLoader": "加载放大模型"
            }
            
            display_name = node_map.get(node_type, node_type)
            
            # 如果是非采样节点，使用忙碌动画（Indeterminate）
            if "sampler" not in node_type.lower() and node_type != "KSampler":
                self.progress_bar.setMaximum(0) # 开启忙碌动画
                self.progress_bar.setFormat(f"任务: {display_name}...")
            else:
                self.progress_bar.setFormat(f"正在准备采样...")
            
            self.interrupt_btn.raise_()
                
        self.statusBar().showMessage(f"正在执行: {node_type} ({node_id})")

    def _on_comfy_done(self, result=None):
        """处理执行完成"""
        self._has_realtime_progress = False
        if hasattr(self, 'progress_bar'):
            self.progress_container.setVisible(False) # 隐藏整个容器
        self.statusBar().showMessage("生成任务已完成", 5000)

    def closeEvent(self, event):
        """窗口关闭时保存状态"""
        print("[Window] closeEvent 被调用，正在保存窗口状态...")

        if hasattr(self, "log_poll_timer") and self.log_poll_timer.isActive():
            self.log_poll_timer.stop()

        if hasattr(self, "queue_dialog") and self.queue_dialog:
            self.queue_dialog.close()

        if hasattr(self, "watcher"):
            self.watcher.stop_monitoring()

        if hasattr(self, "search_controller") and hasattr(self.search_controller, "search_loader"):
            if self.search_controller.search_loader.isRunning():
                self.search_controller.search_loader.stop()
                self.search_controller.search_loader.wait()

        if hasattr(self, "file_controller") and self.file_controller.loader_thread:
            if self.file_controller.loader_thread.isRunning():
                self.file_controller.loader_thread.stop()
                self.file_controller.loader_thread.wait()

        if hasattr(self, "param_panel") and self.param_panel.current_ai_worker:
            if self.param_panel.current_ai_worker.isRunning():
                self.param_panel.current_ai_worker.is_cancelled = True
                self.param_panel.current_ai_worker.wait(3000)
                if self.param_panel.current_ai_worker.isRunning():
                    self.param_panel.current_ai_worker.terminate()
                    self.param_panel.current_ai_worker.wait()
        
        if hasattr(self, "param_panel") and self.param_panel.current_img_worker:
            if self.param_panel.current_img_worker.isRunning():
                self.param_panel.current_img_worker.is_cancelled = True
                self.param_panel.current_img_worker.wait(3000)
                if self.param_panel.current_img_worker.isRunning():
                    self.param_panel.current_img_worker.terminate()
                    self.param_panel.current_img_worker.wait()

        if hasattr(self, "comfy_client"):
            if self.comfy_client.reconnect_timer.isActive():
                self.comfy_client.reconnect_timer.stop()
            self.comfy_client.ws.close()
        if hasattr(self, "queue_sync_timer") and self.queue_sync_timer.isActive():
            self.queue_sync_timer.stop()

        if hasattr(self, "web_service"):
            self.web_service.stop_server()

        # 保存窗口几何形状（位置和大小）
        self.settings.setValue("window/geometry", self.saveGeometry())
        print(f"[Window] 已保存窗口几何形状")
        
        # 保存分割器状态（各面板的宽度比例）
        self.settings.setValue("window/main_splitter", self.splitter.saveState())
        self.settings.setValue("window/left_splitter", self.left_splitter.saveState())
        print(f"[Window] 已保存分割器状态")
        
        # 保存当前文件夹
        if self.current_folder:
            self.settings.setValue("last_folder", self.current_folder)
            print(f"[Window] 已保存当前文件夹: {self.current_folder}")

        # 保存最近一次对比会话（跨重启恢复）
        self._save_last_compare_session()
        
        # 强制同步到磁盘
        self.settings.sync()
        print(f"[Window] 设置已同步到磁盘")
        
        super().closeEvent(event)
