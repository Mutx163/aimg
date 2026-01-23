from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QSplitter, QFileDialog, QToolBar, QMessageBox, 
                             QStatusBar, QLineEdit, QLabel, QTabWidget, QStackedWidget, 
                             QFrame, QComboBox, QPushButton)
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

class SearchThumbnailLoader(QThread):
    """专门为搜索结果异步加载缩略图的微型线程 - V4.1 缓存优化版"""
    thumbnail_ready = pyqtSignal(int, str, QImage)

    def __init__(self, paths, thumb_cache=None):
        super().__init__()
        self.paths = paths
        self.thumb_cache = thumb_cache or ThumbnailCache()
        self._is_running = True

    def run(self):
        for i, path in enumerate(self.paths):
            if not self._is_running: break
            if not os.path.exists(path): continue
            
            try:
                # 优先从缓存读取
                thumb = self.thumb_cache.get_thumbnail(path)
                if not thumb:
                    img = QImage(path)
                    if not img.isNull():
                        thumb = img.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, 
                                          Qt.TransformationMode.FastTransformation)
                        self.thumb_cache.save_thumbnail(path, thumb)
                
                if thumb:
                    self.thumbnail_ready.emit(i, path, thumb)
            except Exception as e:
                print(f"[SearchLoader] Thumb error for {path}: {e}")

    def stop(self):
        self._is_running = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Image Viewer Pro")
        self.resize(1200, 800)
        
        # 状态数据
        self.current_folder = None
        self.current_model = "ALL"
        self.current_lora = "ALL"
        
        # 初始化数据库与缓存
        self.db_manager = DatabaseManager()
        self.thumb_cache = ThumbnailCache()
        
        # 核心组件初始化
        self.watcher = FileWatcher()
        self.watcher.get_signal().connect(self.on_new_image_detected)
        
        self.settings = QSettings("Antigravity", "AIImageViewer")
        self.current_sort_by = self.settings.value("sort_by", "time_desc")
        
        # 搜索防抖定时器
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)
        
        self.setup_ui()
        self.apply_theme()
        
        # 初始化 ComfyUI 客户端
        self.comfy_client = ComfyClient(self.settings.value("comfy_address", "127.0.0.1:8188"))
        self.comfy_client.status_changed.connect(lambda msg: self.statusBar().showMessage(f"[Comfy] {msg}", 3000))
        self.comfy_client.progress_updated.connect(self._on_comfy_progress)
        self.comfy_client.connect_server()
        
        # 绑定参数面板的远程生成请求
        self.param_panel.remote_gen_requested.connect(self.on_remote_gen_requested)
        self.comfy_client.execution_start.connect(self._on_comfy_node_start)
        self.comfy_client.execution_done.connect(lambda: self.statusBar().showMessage("ComfyUI 生成任务已完成", 5000))
        
        # 自动加载上次的文件夹
        last_folder = self.settings.value("last_folder")
        if last_folder and os.path.exists(last_folder):
            self.current_folder = last_folder
            self.load_folder(last_folder)
            
            # 启动监控
            if self.watcher.start_monitoring(last_folder):
                self.statusBar().showMessage(f"正在监控(上次位置): {last_folder}")

    def load_folder(self, folder):
        """扫描文件夹并加载现有图片 (异步)"""
        self.thumbnail_list.clear_list()
        self.viewer.clear_view()
        self.param_panel.clear_info()
        self.statusBar().showMessage(f"正在加载: {folder}...")
        
        if hasattr(self, 'loader_thread') and self.loader_thread.isRunning():
            self.loader_thread.stop()
            self.loader_thread.wait()
            
        from src.core.loader import ImageLoaderThread
        self.loader_thread = ImageLoaderThread(folder, self.db_manager, self.thumb_cache)
        self.loader_thread.image_thumb_ready.connect(self._on_loader_image_ready)
        self.loader_thread.image_found.connect(self._on_loader_image_found)
        self.loader_thread.finished_loading.connect(self._on_loader_finished)
        self.loader_thread.start()

    def setup_ui(self):
        # 1. 工具栏 - Windows 原生风格
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: palette(window);
                border: none;
                border-bottom: 1px solid palette(mid);
                spacing: 6px;
                padding: 6px;
            }
            QToolButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 6px 12px;
                margin: 2px;
                color: palette(window-text);
            }
            QToolButton:hover {
                background-color: palette(midlight);
                border: 1px solid palette(mid);
            }
            QToolButton:pressed {
                background-color: palette(mid);
            }
            QToolButton:checked {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
        """)
        self.addToolBar(toolbar)
        
        action_open = QAction("📂 打开文件夹", self)
        action_open.triggered.connect(self.select_folder)
        toolbar.addAction(action_open)
        
        action_refresh = QAction("🔄 刷新", self)
        action_refresh.triggered.connect(self.refresh_folder)
        toolbar.addAction(action_refresh)
        
        toolbar.addSeparator()
        
        action_fit = QAction("⛶ 适应窗口", self)
        action_fit.triggered.connect(lambda: self.viewer.fit_to_window())
        toolbar.addAction(action_fit)
        
        action_fill = QAction("🖼 铺满窗口", self)
        action_fill.triggered.connect(lambda: self.viewer.toggle_fill_mode())
        action_fill.setToolTip("图片铺满区域，不留黑边（可能会裁剪图片）")
        toolbar.addAction(action_fill)
        
        action_original = QAction("1:1 原始大小", self)
        action_original.triggered.connect(lambda: self.viewer.fit_to_original())
        toolbar.addAction(action_original)
        
        toolbar.addSeparator()
        
        self.action_compare = QAction("⚖ 对比模式", self)
        self.action_compare.setCheckable(True)
        self.action_compare.triggered.connect(self.toggle_comparison_mode)
        toolbar.addAction(self.action_compare)
        
        toolbar.addSeparator()
        
        # 排序选择 - 优化样式
        sort_label = QLabel(" 排序: ")
        sort_label.setStyleSheet("color: palette(window-text); font-weight: bold;")
        toolbar.addWidget(sort_label)
        
        self.sort_combo = QComboBox()
        self.sort_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 150px;
                background-color: palette(base);
            }
            QComboBox:hover {
                border: 1px solid palette(highlight);
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid palette(text);
                margin-right: 6px;
            }
        """)
        self.sort_combo.addItem("⚡ 时间倒序 (最新在前)", "time_desc")
        self.sort_combo.addItem("🔼 时间正序 (最旧在前)", "time_asc")
        self.sort_combo.addItem("🅰 名称 A-Z", "name_asc")
        self.sort_combo.addItem("🆉 名称 Z-A", "name_desc")
        
        # 设置当前选中项
        index = self.sort_combo.findData(self.current_sort_by)
        if index >= 0: self.sort_combo.setCurrentIndex(index)
        
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        toolbar.addWidget(self.sort_combo)
        
        toolbar.addSeparator()
        
        action_settings = QAction("⚙ 设置", self)
        action_settings.triggered.connect(self.open_settings)
        toolbar.addAction(action_settings)

        # 2. 中间主要区域 (QSplitter)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)
        
        # 左侧列表面板 (增加搜索框)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(2, 2, 2, 2)
        
        # 搜索栏 + 重置按钮
        search_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("🔍 搜索提示词/模型/文件名...")
        self.search_bar.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_bar)
        
        btn_reset = QPushButton("🔄")
        btn_reset.setFixedWidth(35)
        btn_reset.setToolTip("重置所有筛选")
        btn_reset.clicked.connect(self._reset_all_filters)
        search_layout.addWidget(btn_reset)
        
        left_layout.addLayout(search_layout)
        
        # 增加一条细分割线，区分全局搜索与筛选器
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #333; margin: 2px 0;")
        left_layout.addWidget(line)
        
        # 使用 QSplitter 整合“筛选区”和“图库列表”
        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 1. 模型筛选器
        self.model_explorer = ModelExplorer()
        self.model_explorer.filter_requested.connect(self.on_filter_requested)
        self.left_splitter.addWidget(self.model_explorer)
        
        # 2. 缩略图图库
        self.thumbnail_list = ThumbnailList()
        self.thumbnail_list.image_selected.connect(self.on_image_selected)
        self.thumbnail_list.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.left_splitter.addWidget(self.thumbnail_list)
        
        # 初始权重：筛选占 30%，列表占 70%
        self.left_splitter.setStretchFactor(0, 3)
        self.left_splitter.setStretchFactor(1, 7)
        
        left_layout.addWidget(self.left_splitter)
        
        self.splitter.addWidget(left_widget)
        
        # 中间：主展示区 (使用 Stack 进行单图/对比切换)
        self.view_stack = QStackedWidget()
        self.view_stack.setContentsMargins(0, 0, 0, 0) # 消除 Stack 内部边距
        
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
        self.param_panel.setMinimumWidth(100)
        self.param_panel.setMaximumWidth(600)
        self.splitter.addWidget(self.param_panel)
        
        # 设置 Splitter 初始比例
        self.splitter.setStretchFactor(0, 0) # 侧边栏不主动伸缩
        self.splitter.setStretchFactor(1, 1) # 中间区域主动伸缩
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([250, 900, 250])

    def resizeEvent(self, event):
        """窗口缩放时尝试消除空白"""
        super().resizeEvent(event)
        self.auto_adjust_layout()

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
            self.load_folder(folder)
            
            # 启动监控
            if self.watcher.start_monitoring(folder):
                self.statusBar().showMessage(f"正在监控: {folder}")
            else:
                self.statusBar().showMessage(f"监控失败: {folder}")

    def refresh_folder(self):
        """刷新当前文件夹 - 使用数据库查询而非重新扫描"""
        if self.current_folder:
            # 不重新扫描，而是重新执行当前的搜索/过滤
            self.perform_search(model=self.current_model, lora=self.current_lora)
            self.statusBar().showMessage("已刷新列表", 2000)

    def load_folder(self, folder):
        """扫描文件夹并加载现有图片 (异步)"""
        self.thumbnail_list.clear_list()
        self.viewer.clear_view() # 使用安全清空方法
        self.param_panel.clear_info()
        self.statusBar().showMessage(f"正在加载: {folder}...")
        
        # 停止旧的加载线程（如果有）
        if hasattr(self, 'loader_thread') and self.loader_thread.isRunning():
            self.loader_thread.stop()
            self.loader_thread.wait()
            
        from src.core.loader import ImageLoaderThread
        self.loader_thread = ImageLoaderThread(folder, self.db_manager)
        # 连接新的带缩略图的信号
        self.loader_thread.image_thumb_ready.connect(self._on_loader_image_ready)
        # 保留旧的 fallback
        self.loader_thread.image_found.connect(self._on_loader_image_found)
        self.loader_thread.finished_loading.connect(self._on_loader_finished)
        self.loader_thread.start()

    def _on_loader_image_ready(self, path, thumb):
        # 检查是否是第一张图片（即最新的一张）
        is_first = self.thumbnail_list.count() == 0
        
        # 线程回调：添加带缩略图的图片
        self.thumbnail_list.add_image(path, thumbnail=thumb)
        
        # 如果是第一张，自动选中并显示
        if is_first:
            self.thumbnail_list.setCurrentRow(0)
            self.on_image_selected(path)
            
        # 增量刷新模型筛选器：每加载 30 张图片刷新一次，让用户尽早看到 LoRA 列表
        count = self.thumbnail_list.count()
        if count > 0 and count % 30 == 0:
            self.refresh_model_explorer()

    def _on_loader_image_found(self, path):
        # 线程回调：添加单张图片 (无缩略图)
        self.thumbnail_list.add_image(path)
        
    def _on_loader_finished(self):
        self.statusBar().showMessage("文件夹加载完成")
        # 刷新模型浏览器数据
        self.refresh_model_explorer()
        # 尝试自动选中已有的第一张（如果列表不为空）
        if self.thumbnail_list.count() > 0:
             # 为了避免干扰用户操作，只有在当前没有任何选中项时才自动选中第一张
             # 这里先不强制自动选中，以免覆盖用户意图
             pass

    def refresh_model_explorer(self):
        """从数据库读取最新的模型和 LoRA 统计信息"""
        if not self.current_folder: return
        models = self.db_manager.get_unique_models(self.current_folder)
        loras = self.db_manager.get_unique_loras(self.current_folder)
        self.model_explorer.update_models(models, loras)

    def on_new_image_detected(self, path):
        """Watcher 信号回调：新图片生成"""
        print(f"[新图片] 检测到: {path}")
        self.statusBar().showMessage(f"新图片 detected: {os.path.basename(path)}")
        
        # 延迟加载，等待文件写入完成
        QTimer.singleShot(500, lambda: self._load_new_image_with_retry(path, retries=3))
    
    def _load_new_image_with_retry(self, path, retries=3):
        """延迟重试加载新图片，处理文件未完全写入的情况"""
        try:
            from PyQt6.QtGui import QImage
            img = QImage(path)
            print(f"[新图片] QImage 加载: isNull={img.isNull()}, size={img.size()}")
            
            if not img.isNull():
                thumb = img.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, 
                                  Qt.TransformationMode.FastTransformation)
                print(f"[新图片] 缩略图生成成功: {thumb.size()}")
                self.thumbnail_list.add_image(path, index=0, thumbnail=thumb)
                self.thumbnail_list.setCurrentRow(0) # 明确选中第一张图片，确保高亮同步
                print(f"[新图片] 已添加到列表（带缩略图）并选中")
                
                # 自动查看最新的
                self.on_image_selected(path)
            else:
                # 图片加载失败，可能文件还在写入中
                if retries > 0:
                    print(f"[新图片] 加载失败，{retries} 次重试剩余，等待 800ms...")
                    QTimer.singleShot(800, lambda: self._load_new_image_with_retry(path, retries - 1))
                else:
                    print(f"[新图片] 多次重试后仍失败，使用占位符")
                    self.thumbnail_list.add_image(path, index=0)
                    self.thumbnail_list.setCurrentRow(0)
                    self.on_image_selected(path)
        except Exception as e:
            print(f"[新图片] 缩略图生成失败: {e}")
            if retries > 0:
                QTimer.singleShot(800, lambda: self._load_new_image_with_retry(path, retries - 1))
            else:
                import traceback
                traceback.print_exc()
                self.thumbnail_list.add_image(path, index=0)
                self.thumbnail_list.setCurrentRow(0)
                self.on_image_selected(path)

    def _on_comfy_progress(self, value, max_val):
        """处理 ComfyUI 进度"""
        progress = int((value / max_val) * 100) if max_val > 0 else 0
        # 如果正在采样，显示具体百分号
        current_msg = self.statusBar().currentMessage()
        if "正在生成" in current_msg or "采样" in current_msg:
             self.statusBar().showMessage(f"ComfyUI 正在采样... {progress}%")

    def _on_comfy_node_start(self, node_id, node_type):
        """当 ComfyUI 开始执行某个节点时"""
        self.statusBar().showMessage(f"ComfyUI 正在执行: {node_type} (节点 {node_id})")
        print(f"[Comfy] 正在执行节点: {node_id} ({node_type})")

    def on_remote_gen_requested(self, workflow):
        """发送远程生成请求"""
        self.statusBar().showMessage("正在提交生成请求到 ComfyUI...", 3000)
        prompt_id = self.comfy_client.send_prompt(workflow)
        if prompt_id:
            self.statusBar().showMessage(f"请求已提交 (ID: {prompt_id[:8]}...)", 5000)
        else:
            QMessageBox.warning(self, "生成失败", "无法提交任务到 ComfyUI，请检查地址和连接状态。")

    def on_image_selected(self, path):
        """用户点击缩略图或自动跳转"""
        import time
        t0 = time.time()
        
        self.viewer.load_image(path)
        # 图片改变后，自动调整布局以消除空白
        self.auto_adjust_layout()
        
        # 解析并显示参数
        meta = MetadataParser.parse_image(path)
        self.param_panel.update_info(meta)
        
        t1 = time.time()
        print(f"[UI] 图片加载与解析耗时: {(t1 - t0) * 1000:.2f} ms ({os.path.basename(path)})")
        
    def keyPressEvent(self, event):
        """处理全局快捷键"""
        if event.key() == Qt.Key.Key_Delete:
            self.delete_current_image()
        elif event.key() == Qt.Key.Key_Left:
            self.navigate_image(-1)
        elif event.key() == Qt.Key.Key_Right:
            self.navigate_image(1)
        # 上下键通常由列表自己处理，但如果焦点在 Viewer，我们可以拦截
        # 简单起见，这里优先让 focused widget 处理，除非特定需求
        else:
            super().keyPressEvent(event)

    def delete_current_image(self):
        idx = self.thumbnail_list.currentIndex()
        if not idx.isValid():
            return
            
        row = idx.row()
        path = self.thumbnail_list.image_model.get_path(row)
        
        # 确认对话框
        confirm = self.settings.value("confirm_delete", True, type=bool)
        if confirm:
            ret = QMessageBox.question(self, "确认删除", f"确定要将图片移至回收站吗？\n{os.path.basename(path)}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
        
        try:
            send2trash(path)
            # 从模型中移除
            self.thumbnail_list.image_model.beginRemoveRows(idx.parent(), row, row)
            self.thumbnail_list.image_model.image_data.pop(row)
            self.thumbnail_list.image_model.endRemoveRows()
            
            self.statusBar().showMessage(f"已删除: {os.path.basename(path)}")
            
            # 自动选中下一张 (如果有)
            if self.thumbnail_list.count() > 0:
                next_row = min(row, self.thumbnail_list.count() - 1)
                self.thumbnail_list.setCurrentRow(next_row)
                
                # 重新加载新选中的图片
                next_path = self.thumbnail_list.image_model.get_path(next_row)
                self.on_image_selected(next_path)
            else:
                self.viewer.scene.clear()
                self.param_panel.clear_info()
                
        except Exception as e:
            QMessageBox.critical(self, "删除失败", str(e))

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
        if dlg.exec():
            # 重新应用主题以响应设置变化
            new_addr = self.settings.value("comfy_address", "127.0.0.1:8188")
            if new_addr != old_addr:
                self.comfy_client.server_address = new_addr
                self.comfy_client.connect_server()
            self.apply_theme()

    def closeEvent(self, event):
        self.watcher.stop_monitoring()
        super().closeEvent(event)

    def apply_theme(self):
        """应用界面主题 (从配置读取)"""
        theme = self.settings.value("theme", "dark")
        
        if theme == "dark":
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background-color: #0f0f0f;
                    color: #d1d1d1;
                    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei";
                    font-size: 9pt;
                }
                QSplitter::handle:vertical { background-color: #2a2a2a; height: 1px; }
                QSplitter::handle:horizontal { width: 2px; background-color: #222; }
                QToolBar {
                    background-color: #1a1a1a;
                    border-bottom: 1px solid #2a2a2a;
                    spacing: 8px;
                    padding: 4px;
                }
                QToolButton {
                    padding: 6px 12px;
                    border: 1px solid transparent;
                    border-radius: 4px;
                    color: #bbb;
                }
                QToolButton:hover {
                    background-color: #2a2a2a;
                    border: 1px solid #3a3a3a;
                    color: #fff;
                }
                QLineEdit {
                    background-color: #1a1a1a;
                    border: 1px solid #333;
                    padding: 8px 12px;
                    border-radius: 6px;
                    color: #fff;
                }
                QListWidget { background-color: #0f0f0f; border: none; }
                QListWidget::item { padding: 4px 8px; border-radius: 4px; }
                QListWidget::item:selected {
                    background-color: #252525;
                    border: 1px solid #0078d4;
                    color: #fff;
                }
                QListWidget::item:hover { background-color: #1a1a1a; }
                QStatusBar {
                    background-color: #121212;
                    color: #666;
                    border-top: 1px solid #222;
                }
                QTabWidget::pane { border-top: 1px solid #222; background-color: #0f0f0f; }
                QTabBar::tab {
                    background-color: #1a1a1a;
                    color: #888;
                    padding: 8px 20px;
                }
                QTabBar::tab:selected {
                    background-color: #222;
                    color: #fff;
                    border-bottom: 2px solid #0078d4;
                }
                QGroupBox { 
                    border: 1px solid #2a2a2a; 
                    border-radius: 6px;
                    margin-top: 15px;
                    padding-top: 15px; 
                    color: #888; 
                }
                QTextEdit { background-color: #161616; border: 1px solid #2a2a2a; color: #aaa; }
                QScrollBar:vertical { background: #0f0f0f; width: 10px; }
                QScrollBar::handle:vertical { background: #333; border-radius: 5px; }
            """)
            self.viewer.set_background_color("#0f0f0f")
            self.comparison_view.viewer_left.set_background_color("#0f0f0f")
            self.comparison_view.viewer_right.set_background_color("#0f0f0f")
        else:
            # 经典浅色主题
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background-color: #fcfcfc;
                    color: #333;
                    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei";
                    font-size: 9pt;
                }
                QSplitter::handle:vertical { background-color: #ddd; height: 1px; }
                QSplitter::handle:horizontal { width: 2px; background-color: #eee; }
                QToolBar {
                    background-color: #f0f0f0;
                    border-bottom: 1px solid #ddd;
                    spacing: 8px;
                    padding: 4px;
                }
                QToolButton {
                    padding: 6px 12px;
                    border: 1px solid transparent;
                    border-radius: 4px;
                    color: #555;
                }
                QToolButton:hover {
                    background-color: #e5e5e5;
                    border: 1px solid #ccc;
                    color: #000;
                }
                QLineEdit {
                    background-color: #fff;
                    border: 1px solid #ccc;
                    padding: 8px 12px;
                    border-radius: 6px;
                    color: #000;
                }
                QListWidget { background-color: #fff; border: 1px solid #eee; }
                QListWidget::item { padding: 4px 8px; border-radius: 4px; }
                QListWidget::item:selected {
                    background-color: #e1f0ff;
                    border: 1px solid #0078d4;
                    color: #000;
                }
                QListWidget::item:hover { background-color: #f0f0f0; }
                QStatusBar {
                    background-color: #f0f0f0;
                    color: #888;
                    border-top: 1px solid #ddd;
                }
                QTabWidget::pane { border-top: 1px solid #ddd; background-color: #fff; }
                QTabBar::tab {
                    background-color: #e5e5e5;
                    color: #666;
                    padding: 8px 20px;
                    border: 1px solid #ddd;
                    border-bottom: none;
                }
                QTabBar::tab:selected {
                    background-color: #fff;
                    color: #000;
                    border-bottom: 2px solid #0078d4;
                }
                QGroupBox { 
                    border: 1px solid #ddd; 
                    border-radius: 6px;
                    margin-top: 15px;
                    padding-top: 15px;
                    color: #666; 
                    font-weight: bold; 
                }
                QTextEdit { background-color: #fff; border: 1px solid #ddd; color: #333; }
                QScrollBar:vertical { background: #f5f5f5; width: 10px; }
                QScrollBar::handle:vertical { background: #ccc; border-radius: 5px; }
                QScrollBar::handle:vertical:hover { background: #bbb; }
            """)
            self.viewer.set_background_color("#fcfcfc")
            self.comparison_view.viewer_left.set_background_color("#fcfcfc")
            self.comparison_view.viewer_right.set_background_color("#fcfcfc")

    def on_search_changed(self):
        """搜索文字改变，开启防抖计时"""
        self.search_timer.start(500) # 500ms 后执行搜索

    def perform_search(self, model=None, lora=None):
        """执行数据库搜索 (增加优化，防止 UI 阻塞)"""
        keyword = self.search_bar.text().strip()
        if not self.current_folder: return
        
        # 优化：不再强行 wait() 线程，而是直接 disconnect 并 stop
        if hasattr(self, 'loader_thread') and self.loader_thread.isRunning():
            try:
                self.loader_thread.image_thumb_ready.disconnect()
                self.loader_thread.image_found.disconnect()
                self.loader_thread.finished_loading.disconnect()
            except: pass
            self.loader_thread.stop()
            # 不调用 .wait()，直接开启新流程
            
        m_val = None if model == "ALL" else model
        l_val = None if lora == "ALL" else lora
        
        results = self.db_manager.search_images(
            keyword=keyword, 
            folder_path=self.current_folder,
            model=m_val,
            lora=l_val,
            order_by=self.current_sort_by
        )
        
        # 性能优化：在填充大数据量列表前禁用更新
        self.thumbnail_list.setUpdatesEnabled(False)
        self.thumbnail_list.clear_list()
        
        for path in results:
            self.thumbnail_list.add_image(path)
            
        self.thumbnail_list.setUpdatesEnabled(True)
        self.statusBar().showMessage(f"通过筛选找到 {len(results)} 张图片")
        
        # 启动异步缩略图补全
        if results:
            if hasattr(self, 'search_loader') and self.search_loader.isRunning():
                self.search_loader.stop()
                self.search_loader.wait()
            
            self.search_loader = SearchThumbnailLoader(results, self.thumb_cache)
            self.search_loader.thumbnail_ready.connect(self._on_search_thumb_ready)
            self.search_loader.start()

    def _on_search_thumb_ready(self, index, path, thumb):
        """异步补全搜索结果的图标 (Model 版)"""
        self.thumbnail_list.image_model.update_thumbnail(path, thumb)

    def _on_sort_changed(self, index):
        """排序方式变更"""
        if index < 0: return
        sort_by = self.sort_combo.itemData(index)
        if sort_by:
            self.current_sort_by = sort_by
            self.settings.setValue("sort_by", sort_by)
            self.perform_search(model=self.current_model, lora=self.current_lora)

    def _reset_all_filters(self):
        """重置所有筛选条件"""
        self.search_bar.clear()
        self.model_explorer._clear_selection()
        self.statusBar().showMessage("已重置所有筛选", 2000)

    def on_filter_requested(self, filter_type, name):
        """处理来自模型浏览器的过滤请求 (双向联动)"""
        if filter_type == "Model":
            self.current_model = name
            if name == "ALL":
                self.current_lora = "ALL" # 模型都重置了，LoRA 通常也重置
            self.perform_search(model=self.current_model, lora=self.current_lora)
        elif filter_type == "Lora":
            self.current_lora = name
            self.perform_search(model=self.current_model, lora=self.current_lora)

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

