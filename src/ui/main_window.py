
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QSplitter, QFileDialog, QToolBar, QMessageBox, 
                             QStatusBar, QLineEdit, QLabel, QTabWidget, QStackedWidget, 
                             QFrame, QComboBox, QPushButton, QAbstractSpinBox, QTextEdit, QApplication,
                             QProgressBar, QSizePolicy)
from PyQt6.QtCore import Qt, QSize, QSettings, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QImage
import time
import os
from send2trash import send2trash

from src.core.watcher import FileWatcher
from src.core.loader import ImageLoaderThread
from src.core.database import DatabaseManager
from src.ui.widgets.image_viewer import ImageViewer
from src.ui.widgets.thumbnail_list import ThumbnailList
from src.ui.widgets.param_panel import ParameterPanel
from src.ui.widgets.model_explorer import ModelExplorer
from src.ui.widgets.comparison_view import ComparisonView
from src.core.metadata import MetadataParser
from src.core.comfy_client import ComfyClient
from src.ui.settings_dialog import SettingsDialog
from src.core.cache import ThumbnailCache
from src.ui.controllers.file_controller import FileController

from src.ui.controllers.search_controller import SearchController

class MainWindow(QMainWindow):
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
        
        # 初始化数据库与缓存
        self.db_manager = DatabaseManager()
        self.thumb_cache = ThumbnailCache()
        
        # 核心组件初始化
        self.watcher = FileWatcher()
        self.current_sort_by = self.settings.value("sort_by", "time_desc")
        
        # 控制器初始化
        self.search_controller = SearchController(self)
        self.file_controller = FileController(self)
        
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
        
        # 绑定参数面板的远程生成请求
        self.param_panel.remote_gen_requested.connect(self.on_remote_gen_requested)
        self.comfy_client.execution_start.connect(self._on_comfy_node_start)
        self.comfy_client.execution_done.connect(self._on_comfy_done)
        
        # 日志系统:使用定时器轮询param_panel的日志列表
        self.log_poll_timer = QTimer(self)
        self.log_poll_timer.timeout.connect(self._poll_logs)
        self.log_poll_timer.start(500)  # 每500ms检查一次新日志
        self.last_log_count = 0  # 记录上次已处理的日志数量

        
        # 自动加载上次的文件夹
        last_folder = self.settings.value("last_folder")
        if last_folder and os.path.exists(last_folder):
            self.current_folder = last_folder
            self.file_controller.load_folder(last_folder)
            
            # 从数据库加载历史分辨率并更新到param_panel
            self._load_historical_resolutions()
            
            # 从数据库加载历史采样器并更新到param_panel
            self._load_historical_samplers()
            
            # 启动监控
            if self.watcher.start_monitoring(last_folder):
                self.statusBar().showMessage(f"正在监控(上次位置): {last_folder}")



    def setup_ui(self):
        # 1. 工具栏 - Windows 原生风格
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        # 移除硬编码样式，改由 apply_theme 统一控制
        self.addToolBar(toolbar)
        
        action_open = QAction("打开文件夹", self)
        action_open.triggered.connect(self.select_folder)
        toolbar.addAction(action_open)
        
        action_refresh = QAction("刷新", self)
        action_refresh.triggered.connect(self.refresh_folder)
        toolbar.addAction(action_refresh)
        
        toolbar.addSeparator()
        
        # 缩放控制 - 下拉列表样式
        zoom_label = QLabel(" 缩放: ")
        zoom_label.setStyleSheet("color: palette(window-text); font-weight: bold;")
        toolbar.addWidget(zoom_label)
        
        self.zoom_combo = QComboBox()
        self.zoom_combo.setMinimumWidth(100)
        # 添加选项 (显示文本, 用户数据)
        self.zoom_combo.addItem("适应窗口", "fit")
        self.zoom_combo.addItem("铺满窗口", "fill")
        self.zoom_combo.addItem("100% 原始大小", "1.0")
        self.zoom_combo.addItem("50%", "0.5")
        self.zoom_combo.addItem("200%", "2.0")
        self.zoom_combo.addItem("400%", "4.0")
        
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        toolbar.addWidget(self.zoom_combo)
        
        toolbar.addSeparator()
        
        self.action_compare = QAction("对比模式", self)
        self.action_compare.setCheckable(True)
        self.action_compare.triggered.connect(self.toggle_comparison_mode)
        toolbar.addAction(self.action_compare)
        
        toolbar.addSeparator()
        
        # 排序选择 - 优化样式
        sort_label = QLabel(" 排序: ")
        sort_label.setStyleSheet("color: palette(window-text); font-weight: bold;")
        toolbar.addWidget(sort_label)
        
        self.sort_combo = QComboBox()
        # 移除硬编码样式
        self.sort_combo.addItem("时间倒序 (最新在前)", "time_desc")
        self.sort_combo.addItem("时间正序 (最旧在前)", "time_asc")
        self.sort_combo.addItem("名称 A-Z", "name_asc")
        self.sort_combo.addItem("名称 Z-A", "name_desc")
        
        # 设置当前选中项
        index = self.sort_combo.findData(self.current_sort_by)
        if index >= 0: self.sort_combo.setCurrentIndex(index)
        
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        toolbar.addWidget(self.sort_combo)
        
        toolbar.addSeparator()
        action_settings = QAction("设置", self)
        action_settings.triggered.connect(self.open_settings)
        toolbar.addAction(action_settings)
        
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
        left_widget.setFixedWidth(330)  # 严格限制左侧面板宽度 (约容纳两列大图)
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
        
        # 右侧：参数面板
        self.param_panel = ParameterPanel()
        self.param_panel.setMinimumWidth(380)
        self.param_panel.setMaximumWidth(600)
        self.splitter.addWidget(self.param_panel)
        
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
            if self.watcher.start_monitoring(folder):
                self.statusBar().showMessage(f"正在监控: {folder}")
            else:
                self.statusBar().showMessage(f"监控失败: {folder}")

    def refresh_folder(self):
        """刷新当前文件夹 - 使用数据库查询而非重新扫描"""
        if self.current_folder:
            self.search_controller.perform_search()
            self.statusBar().showMessage("已刷新列表", 2000)

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
            # print(f"[UI] 开始加载历史采样器...")
            samplers = self.db_manager.get_unique_samplers(self.current_folder)
            # print(f"[UI] 从数据库获取到 {len(samplers)} 个采样器: {samplers}")
            self.param_panel._populate_samplers(samplers)
            # print(f"[UI] 已加载 {len(samplers)} 个历史采样器")
        except Exception as e:
            import traceback
            print(f"[UI] 加载历史采样器失败: {e}")
            print(f"[UI] 错误堆栈: {traceback.format_exc()}")
            # 即使失败也填充默认采样器
            self.param_panel._populate_samplers([])

    def refresh_historical_params(self):
        """刷新历史分辨率和采样器列表"""
        if self.current_folder:
            self._load_historical_resolutions()
            self._load_historical_samplers()


    def on_remote_gen_requested(self, workflow, batch_count=1):
        """处理远程生成请求 - 使用当前图片的workflow重新生成"""
        # 清空上一轮日志缓存
        self.last_gen_logs = ""
        self.last_log_count = 0
        
        # 使用当前图片的workflow，但会自动修改随机种子
        print(f"[Main] 远程生成: 使用当前图片的workflow（随机种子） x{batch_count}")
        self.comfy_client.queue_current_prompt(workflow, batch_count)
        self.statusBar().showMessage(f"已发送 {batch_count} 个生成请求到ComfyUI", 3000)
    def _on_prompt_submitted(self, prompt_id):
        """当任务成功提交到 ComfyUI 后触发"""
        self.statusBar().showMessage(f"请求已提交 (ID: {prompt_id[:8]}...)", 5000)

    def on_image_selected(self, path):
        """用户点击缩略图或自动跳转"""
        import time
        t0 = time.time()
        
        self.viewer.load_image(path)
        # 切换图片时，重置手动缩放状态，应用当前的缩放选项
        self._on_zoom_changed(self.zoom_combo.currentIndex())
        
        # 解析并显示参数
        meta = MetadataParser.parse_image(path)
        self.param_panel.update_info(meta)
        
        t1 = time.time()
        # print(f"[UI] 图片加载与解析耗时: {(t1 - t0) * 1000:.2f} ms ({os.path.basename(path)})")
        
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
                "separator": "#333333"
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
                "separator": "#e5e5e5"
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

            /* 工具栏 */
            QToolBar {{
                background-color: {colors['bg_main']};
                border-bottom: 1px solid {colors['separator']};
                spacing: 4px;
                padding: 4px 8px;
            }}
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 6px 10px;
                color: {colors['text_secondary']};
            }}
            QToolButton:hover {{
                background-color: {colors['bg_hover']};
                color: {colors['text_main']};
            }}
            QToolButton:pressed {{
                background-color: {colors['bg_pressed']};
            }}
            QToolButton:checked {{
                background-color: {colors['bg_card']};
                border: 1px solid {colors['border']};
                color: {colors['accent']};
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
                border: 1px solid {colors['border']};
                selection-background-color: {colors['accent']};
                selection-color: white;
                outline: none;
            }}
        """
        self.setStyleSheet(qss)
        
        # 更新组件背景色
        bg_viewer = colors['bg_main']
        self.viewer.set_background_color(bg_viewer)
        self.comparison_view.viewer_left.set_background_color(bg_viewer)
        self.comparison_view.viewer_right.set_background_color(bg_viewer)

    def _on_zoom_changed(self, index):
        """处理缩放下拉框变化"""
        data = self.zoom_combo.itemData(index)
        if not data: return
        
        if data == "fit":
            self.viewer.fit_to_window()
        elif data == "fill":
            self.viewer.toggle_fill_mode()
        else:
            try:
                scale_val = float(data)
                self.viewer.fit_to_original() # 先重置
                if scale_val != 1.0:
                    self.viewer.scale(scale_val, scale_val)
            except ValueError:
                pass

    def _on_sort_changed(self, index):
        """排序方式变更"""
        if index < 0: return
        sort_by = self.sort_combo.itemData(index)
        if sort_by:
            self.current_sort_by = sort_by
            self.settings.setValue("sort_by", sort_by)
            self.search_controller.perform_search()

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

    def _on_comfy_node_start(self, node_id, node_type):
        """处理节点开始执行"""
        if hasattr(self, 'progress_bar'):
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
        
        # 强制同步到磁盘
        self.settings.sync()
        print(f"[Window] 设置已同步到磁盘")
        
        super().closeEvent(event)
