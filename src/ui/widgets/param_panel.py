from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTextEdit, QScrollArea,
                             QFrame, QGridLayout, QHBoxLayout, QPushButton, QApplication, 
                             QSplitter, QGroupBox, QSpinBox, QDoubleSpinBox, QSlider, 
                             QComboBox, QLineEdit, QCheckBox, QDialog, QMenu, QToolButton,
                             QAbstractSpinBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSettings, QThread, QEvent
from PyQt6.QtGui import QFont, QAction
from typing import List, Dict
import random
import copy
import json
from src.assets.default_workflows import DEFAULT_T2I_WORKFLOW
from src.core.ai_prompt_optimizer import AIPromptOptimizer

class AIWorker(QThread):
    finished = pyqtSignal(bool, str)  # (success, result)
    stream_update = pyqtSignal(str)   # (chunk)
    
    def __init__(self, user_input, existing_prompt, is_negative):
        super().__init__()
        self.user_input = user_input
        self.existing_prompt = existing_prompt
        self.is_negative = is_negative
        self.is_cancelled = False
    
    def run(self):
        try:
            if self.is_cancelled: return
            optimizer = AIPromptOptimizer()
            
            def on_stream_callback(chunk):
                if not self.is_cancelled:
                    self.stream_update.emit(chunk)
            
            success, result = optimizer.optimize_prompt(
                self.user_input, 
                self.existing_prompt,
                is_negative=self.is_negative,
                stream_callback=on_stream_callback
            )
            if not self.is_cancelled:
                self.finished.emit(success, result)
        except Exception as e:
            if not self.is_cancelled:
                self.finished.emit(False, f"处理异常: {str(e)}")

class AIHistoryManager:
    """管理AI提示词修改历史 (Session-based)"""
    def __init__(self):
        # Format: { 'positive': [session1, session2], 'negative': [...] }
        # Session: {'base': str, 'chain': [v1, v2, ...], 'timestamp': time}
        self.sessions = {'positive': [], 'negative': []}
        
    def add_record(self, prompt_type: str, original: str, new_text: str):
        sessions = self.sessions[prompt_type]
        import time
        
        # 尝试查找匹配的现有 Session (即 original 是某个 Session 的最新版本)
        # 优先匹配最近的 Session
        for session in reversed(sessions):
            last_version = session['chain'][-1] if session['chain'] else session['base']
            if last_version == original:
                session['chain'].append(new_text)
                return

        # 如果没有匹配，创建新 Session
        sessions.append({
            'base': original,
            'chain': [new_text],
            'timestamp': time.time()
        })
    
    def get_sessions(self, prompt_type: str) -> List[Dict]:
        return self.sessions[prompt_type]

class SmartTextEdit(QTextEdit):
    """支持回车提交，Shift+回车换行的文本框"""
    submitted = pyqtSignal()
    
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Shift + Enter: 正常换行
                super().keyPressEvent(event)
            else:
                # 仅 Enter: 触发提交
                self.submitted.emit()
            return
        super().keyPressEvent(event)

class AIPromptDialog(QDialog):
    """自定义 AI 提示词输入对话框，支持预设标签"""
    def __init__(self, title, label_text, preset_tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self.resize(550, 400)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # 顶部提示
        layout.addWidget(QLabel(label_text))
        
        # 预设标签区域 (FlowLayout 模拟效果)
        tags_container = QWidget()
        tags_layout = QHBoxLayout(tags_container) # 简单布局，后续可用 FlowLayout
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(8)
        
        # 使用 QFrame + 自动换行或简单的按钮组
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(100)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tag_scroll = scroll
        
        tag_widget = QWidget()
        self.tag_layout = QHBoxLayout(tag_widget) # 暂时横向
        self.tag_layout.setContentsMargins(2, 2, 2, 2)
        self.tag_layout.addStretch() # 让按钮靠左
        
        for tag in preset_tags:
            btn = QPushButton(tag)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #f3f4f6;
                    border: 1px solid #e5e7eb;
                    color: #374151;
                    border-radius: 14px;
                    padding: 4px 12px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #ede9fe;
                    color: #5b21b6;
                    border-color: #c4b5fd;
                }
                QPushButton:pressed {
                    background-color: #ddd6fe;
                    border-color: #a78bfa;
                }
            """)
            btn.clicked.connect(lambda checked, t=tag: self._on_tag_clicked(t))
            self.tag_layout.insertWidget(self.tag_layout.count() - 1, btn)
            
        scroll.setWidget(tag_widget)
        scroll.viewport().installEventFilter(self)
        layout.addWidget(scroll)
        
        # 输入框
        self.input_edit = SmartTextEdit()
        self.input_edit.setPlaceholderText("在此输入或点击上方标签...\n(提示: Enter 确定优化, Shift+Enter 换行)")
        self.input_edit.setStyleSheet("background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px; padding: 8px;")
        self.input_edit.submitted.connect(self._try_accept)
        layout.addWidget(self.input_edit)

        info_row = QHBoxLayout()
        self.counter_label = QLabel("字数: 0")
        self.counter_label.setStyleSheet("color: palette(mid); font-size: 10px;")
        info_row.addStretch()
        info_row.addWidget(self.counter_label)
        layout.addLayout(info_row)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_ok = QPushButton("确定优化")
        self.btn_ok.setMinimumSize(100, 32)
        self.btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #8b5cf6; }
            QPushButton:pressed { background-color: #6d28d9; }
            QPushButton:disabled { background-color: #555; color: #aaa; }
        """)
        self.btn_ok.clicked.connect(self._try_accept)
        
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setMinimumSize(80, 32)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: palette(alternate-base);
                color: palette(text);
                border-radius: 6px;
                border: 1px solid palette(mid);
            }
            QPushButton:hover { background-color: palette(midlight); }
            QPushButton:pressed { background-color: palette(mid); color: white; }
        """)
        self.btn_clear.clicked.connect(self._clear_input)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setMinimumSize(80, 32)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: palette(base);
                color: palette(text);
                border-radius: 6px;
                border: 1px solid palette(mid);
            }
            QPushButton:hover { background-color: palette(midlight); }
            QPushButton:pressed { background-color: palette(mid); color: white; }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

        self.input_edit.textChanged.connect(self._update_state)
        self._update_state()
        self.input_edit.setFocus()

    def _on_tag_clicked(self, tag):
        current_text = self.input_edit.toPlainText().strip()
        if current_text:
            self.input_edit.setPlainText(f"{current_text}，{tag}")
        else:
            self.input_edit.setPlainText(tag)
        self.input_edit.setFocus()

    def _update_state(self):
        text = self.input_edit.toPlainText().strip()
        self.counter_label.setText(f"字数: {len(text)}")
        self.btn_ok.setEnabled(bool(text))

    def _try_accept(self):
        text = self.input_edit.toPlainText().strip()
        if text:
            self.accept()

    def _clear_input(self):
        self.input_edit.clear()

    def eventFilter(self, source, event):
        if source is self.tag_scroll.viewport() and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta()
            dx = delta.x()
            dy = delta.y()
            bar = self.tag_scroll.horizontalScrollBar()
            if dx != 0:
                bar.setValue(bar.value() - dx)
            elif dy != 0:
                bar.setValue(bar.value() - dy)
            return True
        return super().eventFilter(source, event)

    def get_text(self):
        return self.input_edit.toPlainText().strip()

class ParameterPanel(QScrollArea):
    # 信号定义
    remote_gen_requested = pyqtSignal(dict, int) # 请求远程生成 (带workflow, 批次数量)
    
    # 日志系统:使用简单的列表,不用信号
    generation_logs = []  # 类变量,存储所有生成日志
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("ComfyUIImageManager", "Settings")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # 内部状态
        self.current_meta = {}
        self.current_loras = {} # 存储当前选中的LoRA {name: weight}
        self._ai_is_processing = False # AI处理并发锁
        self.history_manager = AIHistoryManager()
        self.current_ai_worker = None
        
        # Create a central widget for the scroll area
        self._central_widget = QWidget()
        self.setWidget(self._central_widget)
        
        self.layout = QVBoxLayout(self._central_widget) # Layout should be on the central widget
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(8)
        
        # ========== 1. 顶部核心信息卡片 ==========
        self.info_card = QFrame()
        # 移除硬编码 palette 样式，依赖全局 QSS
        self.info_card.setObjectName("InfoCard") # 方便 QSS 定制
        info_card_layout = QVBoxLayout(self.info_card)
        info_card_layout.setContentsMargins(12, 12, 12, 12)
        info_card_layout.setSpacing(10)
        
        # 第一行：大标题和复制按钮
        title_row = QHBoxLayout()
        self.model_label = QLabel("🎨 未选择模型")
        self.model_label.setFont(QFont("", 13, QFont.Weight.Bold))
        self.model_label.setStyleSheet("color: palette(highlight);")
        title_row.addWidget(self.model_label)
        title_row.addStretch()
        
        btn_copy_all = QPushButton("📋 复制全部")
        btn_copy_all.setCursor(Qt.CursorShape.PointingHandCursor)
        # 移除固定宽度，改用最小宽度 + 自适应
        btn_copy_all.setMinimumWidth(80) 
        btn_copy_all.clicked.connect(self._copy_all_params)
        title_row.addWidget(btn_copy_all)
        
        # 添加“调用到工作区”按钮 (替代之前的生成按钮)
        self.btn_apply_workspace = QPushButton("📥 调用进生成区")
        self.btn_apply_workspace.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_workspace.setMinimumWidth(110)
        self.btn_apply_workspace.setObjectName("ApplyWorkspaceButton")
        self.btn_apply_workspace.setStyleSheet("""
            QPushButton#ApplyWorkspaceButton {
                background-color: palette(button);
                border: 1px solid palette(highlight);
                color: palette(text);
                font-weight: bold;
                padding: 4px 8px;
            }
            QPushButton#ApplyWorkspaceButton:hover { background-color: palette(highlight); color: white; }
        """)
        self.btn_apply_workspace.clicked.connect(self.apply_to_workspace)
        title_row.addWidget(self.btn_apply_workspace)
        # 强制垂直居中对齐，修复按钮高低不平的问题
        title_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        title_row.setContentsMargins(0, 0, 0, 0)
        info_card_layout.addLayout(title_row)
        
        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("CardSeparator")
        info_card_layout.addWidget(line)
        
        # 参数网格展示区 (不再使用沉重的 GroupBox)
        self.stats_grid = QGridLayout()
        self.stats_grid.setVerticalSpacing(6)
        self.stats_grid.setHorizontalSpacing(20)
        
        # 预定义标签样式
        self._label_style = "color: palette(mid); font-weight: bold; font-size: 10px;"
        # 统一数值区域样式：增加背景框效果
        self._value_style = "background-color: palette(alternate-base); border-radius: 4px; padding: 2px 8px; color: palette(text); font-size: 11px;"
        self._fixed_label_width = 65 # 统一标签宽度，确保对齐
        
        def add_stat(row, col, label_text, attr_name, colspan=1):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(self._label_style)
            lbl.setFixedWidth(self._fixed_label_width) # 强制固定宽度
            val = QLabel("-")
            val.setStyleSheet(self._value_style)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            setattr(self, attr_name, val)
            self.stats_grid.addWidget(lbl, row, col)
            self.stats_grid.addWidget(val, row, col + 1, 1, colspan)

        # 第一行：SEED 独占
        add_stat(0, 0, "SEED", "seed_label", colspan=3)
        
        # 第二行：分辨率 + 采样器
        add_stat(1, 0, "分辨率", "resolution_label")
        add_stat(1, 2, "采样器", "sampler_label")
        
        # 第三行：Steps + CFG
        add_stat(2, 0, "STEPS", "steps_label")
        add_stat(2, 2, "CFG", "cfg_label")

        # 第四行：LoRAs (改为和SEED一样的独占行显示)
        lbl_lora = QLabel("LORAS")
        lbl_lora.setStyleSheet(self._label_style)
        lbl_lora.setFixedWidth(self._fixed_label_width) # 强制对齐
        self.info_lora_val = QLabel("-")
        self.info_lora_val.setStyleSheet(self._value_style)
        self.info_lora_val.setWordWrap(True)
        self.stats_grid.addWidget(lbl_lora, 3, 0)
        self.stats_grid.addWidget(self.info_lora_val, 3, 1, 1, 3)
        
        info_card_layout.addLayout(self.stats_grid)

        # --- 新增：原始提示词滚动查看区 (样式向SEED看齐) ---
        def add_scroll_info(label_text, attr_name, height):
            lay = QHBoxLayout()
            lay.setSpacing(20) # 提升至 20，与 stats_grid 的 HorizontalSpacing 保持一致
            lbl = QLabel(label_text)
            lbl.setStyleSheet(self._label_style)
            lbl.setFixedWidth(self._fixed_label_width) # 强力对齐
            lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
            
            edit = QTextEdit()
            edit.setReadOnly(True)
            edit.setMaximumHeight(height)
            # 统一提示词区域样式：与上方数值项的“灰色框框”保持一致
            edit.setStyleSheet("background-color: palette(alternate-base); border-radius: 4px; padding: 5px; font-size: 11px; color: palette(text); border: none;")
            setattr(self, attr_name, edit)
            
            lay.addWidget(lbl)
            lay.addWidget(edit)
            info_card_layout.addLayout(lay)

        info_card_layout.addSpacing(5)
        add_scroll_info("提示词", "info_prompt_val", 80)
        add_scroll_info("反向词", "info_neg_val", 60)
        
        # 安装事件过滤器，实现“点击任意区域复制”
        self.info_prompt_val.viewport().installEventFilter(self)
        self.info_neg_val.viewport().installEventFilter(self)
        self.info_prompt_val.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.info_neg_val.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        # 更多细节网格 (预创建坑位，避免跳动)
        self.details_layout = QGridLayout()
        self.details_layout.setVerticalSpacing(4)
        self.details_layout.setHorizontalSpacing(20)
        
        self.detail_widgets = {} # {key: (label_widget, value_widget)}
        detail_keys = [("文件大小", "file_size"), ("格式", "format"), 
                       ("Scheduler", "scheduler"), ("Denoise", "denoise"), 
                       ("Model hash", "model_hash")]
        
        for i, (label_text, key) in enumerate(detail_keys):
            row = i // 2
            col = (i % 2) * 2
            lbl = QLabel(f"{label_text}:")
            lbl.setStyleSheet(self._label_style)
            lbl.setFixedWidth(self._fixed_label_width)
            val = QLabel("-")
            val.setStyleSheet(self._value_style)
            self.details_layout.addWidget(lbl, row, col)
            self.details_layout.addWidget(val, row, col + 1)
            self.detail_widgets[key] = val
            
        info_card_layout.addLayout(self.details_layout)
        
        # 锁定卡片最小高度，防止切换时的视觉剧烈振荡
        self.info_card.setMinimumHeight(320)
        self.layout.addWidget(self.info_card)
        
        # ========== 2. 底部专用生成设置区域 (可编辑工作区) ==========
        self._setup_generation_settings(self.layout)

    def _populate_resolutions(self, preset_res, history_res):
        """填充分辨率下拉框（预设+历史，去重）"""
        # 暂时阻塞信号，防止清除/添加过程触发自动保存导致配置丢失
        self.resolution_combo.blockSignals(True)
        try:
            # 记录当前选中内容，以便刷新后恢复
            current_res = self.resolution_combo.currentData()
            
            # 合并并去重
            all_res = set(preset_res + history_res)
            # 排序：先按宽度，再按高度
            sorted_res = sorted(list(all_res), key=lambda x: (x[0], x[1]))
            
            self.resolution_combo.clear()
            for w, h in sorted_res:
                # 判断横竖图
                if w == h:
                    label = f"{w} × {h} (方图)"
                elif w < h:
                    label = f"{w} × {h} (竖图)"
                else:
                    label = f"{w} × {h} (横图)"
            
                self.resolution_combo.addItem(label, (w, h))
            
            saved_res = None
            if self.settings.contains("gen_width") and self.settings.contains("gen_height"):
                saved_w = self.settings.value("gen_width", 0, type=int)
                saved_h = self.settings.value("gen_height", 0, type=int)
                if saved_w and saved_h:
                    saved_res = (saved_w, saved_h)

            # 优先从设置恢复，再回退到当前选择
            target_res = saved_res or current_res
            
            if not target_res:
                target_res = (512, 768)
            
            found = False
            for i in range(self.resolution_combo.count()):
                res_data = self.resolution_combo.itemData(i)
                if res_data == target_res:
                    self.resolution_combo.setCurrentIndex(i)
                    found = True
                    break
            
            # 如果既没恢复成功也没默认成功，且列表不为空，选第一个
            if not found and self.resolution_combo.count() > 0:
                self.resolution_combo.setCurrentIndex(0)
        finally:
            self.resolution_combo.blockSignals(False)

    def _populate_samplers(self, samplers: List[str]):
        """填充采样器下拉框"""
        # print(f"[UI] _populate_samplers被调用，采样器列表: {samplers}")
        
        # 暂时阻塞信号，防止清除过程触发自动保存(存为空值)导致配置丢失
        self.sampler_combo.blockSignals(True)
        try:
            # 记录当前选中
            current_sampler = self.sampler_combo.currentText()
            self.sampler_combo.clear()
            
            if samplers:
                for sampler in samplers:
                    self.sampler_combo.addItem(sampler)
                    # print(f"[UI] 添加采样器: {sampler}")
            else:
                # 如果没有历史记录，添加一些常用采样器
                default_samplers = ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde"]
                # print(f"[UI] 没有历史采样器，使用默认列表: {default_samplers}")
                for sampler in default_samplers:
                    self.sampler_combo.addItem(sampler)
            
            # 优先恢复之前的选择
            target_sampler = current_sampler
            if not target_sampler:
                target_sampler = self.settings.value("gen_sampler", "", type=str)

            if target_sampler:
                index = self.sampler_combo.findText(target_sampler)
                if index >= 0:
                    self.sampler_combo.setCurrentIndex(index)
                    return

            # 默认选择第一个
            if self.sampler_combo.count() > 0:
                self.sampler_combo.setCurrentIndex(0)
                # print(f"[UI] 采样器下拉框已填充，共 {self.sampler_combo.count()} 项")
            else:
                # print(f"[UI] 警告：采样器下拉框为空！")
                pass
        finally:
            self.sampler_combo.blockSignals(False)

    def _setup_generation_settings(self, parent_layout):
        """设置生成参数编辑面板（专用工作区）"""
        gen_settings_outer = QFrame()
        gen_settings_outer.setObjectName("GenWorkspace")
        gen_settings_outer.setStyleSheet("""
            QFrame#GenWorkspace {
                background-color: palette(window);
                border: 1px solid palette(highlight);
                border-radius: 8px;
                margin-top: 5px;
            }
        """)
        outer_layout = QVBoxLayout(gen_settings_outer)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)
        
        header_lbl = QLabel("🛠️ 生成工作区 (在此修改并生成)")
        header_lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: palette(highlight);")
        outer_layout.addWidget(header_lbl)

        # --- 1. 可编辑文本区 ---
        def create_edit_block(title, placeholder, height):
            # 标题和AI按钮放在同一行
            title_row = QHBoxLayout()
            title_row.setSpacing(8)
            title_row.addWidget(QLabel(title, styleSheet=self._label_style))
            title_row.addStretch()
            return title_row, height

        # 正向提示词
        prompt_title_row, prompt_height = create_edit_block("✨ 正向提示词", "输入新的提示词进行创作...", 70)

        # AI处理状态标签
        self.ai_status_label = QLabel("")
        self.ai_status_label.setStyleSheet("color: #8b5cf6; font-size: 10px;")
        self.ai_status_label.setFixedWidth(80)
        prompt_title_row.addWidget(self.ai_status_label)

        # 历史记录按钮
        self.btn_history = QToolButton()
        self.btn_history.setText("📜")
        self.btn_history.setToolTip("查看AI修改历史")
        self.btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history.setStyleSheet("QToolButton { border: none; background: transparent; font-size: 14px; } QToolButton:hover { background: palette(midlight); border-radius: 4px; }")
        self.btn_history.clicked.connect(lambda: self._show_history_menu('positive'))
        prompt_title_row.addWidget(self.btn_history)

        # AI优化按钮(放在标题行)
        self.btn_ai_optimize = QPushButton("✨ AI优化")
        self.btn_ai_optimize.setToolTip("使用AI优化提示词")
        self.btn_ai_optimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_optimize.setFixedSize(80, 24)
        self.btn_ai_optimize.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border-radius: 3px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #8b5cf6; }
            QPushButton:pressed { background-color: #6d28d9; }
            QPushButton:disabled { background-color: #555; color: #aaa; }
        """)
        self.btn_ai_optimize.clicked.connect(self._on_ai_optimize_click)
        prompt_title_row.addWidget(self.btn_ai_optimize)

        outer_layout.addLayout(prompt_title_row)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("输入新的提示词进行创作...")
        self.prompt_edit.setMaximumHeight(prompt_height)
        self.prompt_edit.setStyleSheet("background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px; padding: 4px;")
        outer_layout.addWidget(self.prompt_edit)

        # 反向提示词
        neg_title_row, neg_height = create_edit_block("🚫 反向提示词", "输入过滤词...", 60)

        # AI优化反向提示词按钮
        self.btn_neg_ai_optimize = QPushButton("✨ AI优化")
        self.btn_neg_ai_optimize.setToolTip("使���AI优化反向提示词")
        self.btn_neg_ai_optimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_neg_ai_optimize.setFixedSize(80, 24)
        self.btn_neg_ai_optimize.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border-radius: 3px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #8b5cf6; }
            QPushButton:pressed { background-color: #6d28d9; }
            QPushButton:disabled { background-color: #555; color: #aaa; }
        """)
        self.btn_neg_ai_optimize.clicked.connect(self._on_neg_ai_optimize_click)

        # 反向历史记录按钮
        self.btn_neg_history = QToolButton()
        self.btn_neg_history.setText("📜")
        self.btn_neg_history.setToolTip("查看反向提示词修改历史")
        self.btn_neg_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_neg_history.setStyleSheet("QToolButton { border: none; background: transparent; font-size: 14px; } QToolButton:hover { background: palette(midlight); border-radius: 4px; }")
        self.btn_neg_history.clicked.connect(lambda: self._show_history_menu('negative'))

        # AI处理状态标签(反向提示词)
        self.neg_ai_status_label = QLabel("")
        self.neg_ai_status_label.setStyleSheet("color: #8b5cf6; font-size: 10px;")
        self.neg_ai_status_label.setFixedWidth(80)
        
        # Reorder: Status -> History -> AI Button (Right aligned)
        neg_title_row.addWidget(self.neg_ai_status_label)
        neg_title_row.addWidget(self.btn_neg_history)
        neg_title_row.addWidget(self.btn_neg_ai_optimize)

        outer_layout.addLayout(neg_title_row)

        self.neg_prompt_edit = QTextEdit()
        self.neg_prompt_edit.setPlaceholderText("输入过滤词...")
        self.neg_prompt_edit.setMaximumHeight(neg_height)
        self.neg_prompt_edit.setStyleSheet("background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px; padding: 4px;")
        outer_layout.addWidget(self.neg_prompt_edit)
        

        # --- 2. 其他参数设置 ---
        self.gen_settings_container = QWidget()
        gen_layout = QVBoxLayout(self.gen_settings_container)
        gen_layout.setContentsMargins(0, 0, 0, 0)
        gen_layout.setSpacing(6)

        # 将整个外层容器添加到父布局
        parent_layout.addWidget(gen_settings_outer)

        # ===== Seed行 =====
        seed_row = QHBoxLayout()
        seed_row.setSpacing(6)

        lbl_seed = QLabel("Seed:")
        lbl_seed.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        seed_row.addWidget(lbl_seed)

        self.seed_input = QLineEdit()
        self.seed_input.setText("-1")
        self.seed_input.setPlaceholderText("输入种子数值")
        self.seed_input.setMinimumWidth(120)
        self.seed_input.setStyleSheet("padding: 3px; border-radius: 3px; font-size: 11px;")
        seed_row.addWidget(self.seed_input)

        # 改用复选框替代按钮
        from PyQt6.QtWidgets import QCheckBox
        self.seed_random_checkbox = QCheckBox("随机")
        self.seed_random_checkbox.setToolTip("勾选后每次生成使用随机种子")
        # Load saved random state
        saved_random = self.settings.value("seed_random", True, type=bool)
        self.seed_random_checkbox.setChecked(saved_random)
        self.seed_random_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seed_random_checkbox.toggled.connect(self._on_seed_random_toggled)
        seed_row.addWidget(self.seed_random_checkbox)
        seed_row.addStretch()

        gen_layout.addLayout(seed_row)

        # 初始化时禁用输入框（因为默认随机）
        self.seed_input.setEnabled(False)

        # 保存上一张图片的seed，用于取消随机时恢复
        self.last_image_seed = None

        # ===== 分辨率行 =====
        res_row = QHBoxLayout()
        res_row.setSpacing(6)

        lbl_res = QLabel("分辨率:")
        lbl_res.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        res_row.addWidget(lbl_res)

        self.resolution_combo = QComboBox()
        self.resolution_combo.setMinimumWidth(160)
        self.resolution_combo.setStyleSheet("padding: 3px; font-size: 11px;")

        # 系统预设分辨率
        preset_resolutions = [
            (512, 512),
            (768, 768),
            (1024, 1024),
            (512, 768),
            (768, 512),
            (1024, 768),
            (768, 1024),
        ]

        # 从数据库获取历史分辨率（延迟加载，稍后由主窗口调用）
        # 这里先添加预设
        self._populate_resolutions(preset_resolutions, [])

        res_row.addWidget(self.resolution_combo)
        res_row.addStretch()

        gen_layout.addLayout(res_row)

        # ===== Steps和CFG合并到一行 =====
        steps_cfg_row = QHBoxLayout()
        steps_cfg_row.setSpacing(6)

        lbl_steps = QLabel("Steps:")
        lbl_steps.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        steps_cfg_row.addWidget(lbl_steps)

        self.steps_value = QSpinBox()
        self.steps_value.setRange(1, 150)
        self.steps_value.setValue(20)
        self.steps_value.setMinimumWidth(70)
        self.steps_value.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.steps_value.setStyleSheet("""
            QSpinBox {
                padding: 4px;
                font-size: 11px;
                border: 1px solid palette(mid);
                border-radius: 3px;
                background-color: palette(base);
            }
            QSpinBox:focus { border: 2px solid palette(highlight); }
        """)
        steps_cfg_row.addWidget(self.steps_value)

        steps_cfg_row.addSpacing(15)

        lbl_cfg = QLabel("CFG:")
        lbl_cfg.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 40px;")
        steps_cfg_row.addWidget(lbl_cfg)

        self.cfg_value = QDoubleSpinBox()
        self.cfg_value.setRange(1.0, 30.0)
        self.cfg_value.setSingleStep(0.5)
        self.cfg_value.setValue(7.5)
        self.cfg_value.setDecimals(1)
        self.cfg_value.setMinimumWidth(70)
        self.cfg_value.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.cfg_value.setStyleSheet("""
            QDoubleSpinBox {
                padding: 4px;
                font-size: 11px;
                border: 1px solid palette(mid);
                border-radius: 3px;
                background-color: palette(base);
            }
            QDoubleSpinBox:focus { border: 2px solid palette(highlight); }
        """)
        steps_cfg_row.addWidget(self.cfg_value)
        steps_cfg_row.addStretch()

        gen_layout.addLayout(steps_cfg_row)
        
        # ===== 采样器行 =====
        sampler_row = QHBoxLayout()
        sampler_row.setSpacing(6)

        lbl_sampler = QLabel("采样器:")
        lbl_sampler.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        sampler_row.addWidget(lbl_sampler)

        self.sampler_combo = QComboBox()
        self.sampler_combo.setMinimumWidth(160)
        self.sampler_combo.setStyleSheet("padding: 3px; font-size: 11px;")
        sampler_row.addWidget(self.sampler_combo)
        sampler_row.addStretch()

        gen_layout.addLayout(sampler_row)

        # ===== LoRA管理区域 =====
        lora_header_row = QHBoxLayout()
        lora_header_row.setSpacing(6)

        lbl_loras = QLabel("LoRAs:")
        lbl_loras.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px; font-weight: bold;")
        lora_header_row.addWidget(lbl_loras)

        # 添加LoRA按钮放在标题行
        add_lora_btn = QPushButton("+ 添加")
        add_lora_btn.setFixedSize(60, 22)
        add_lora_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 6px;
                background-color: palette(button);
                border: 1px solid palette(mid);
                border-radius: 3px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: palette(light); }
        """)
        add_lora_btn.clicked.connect(self._on_add_lora_click)
        lora_header_row.addWidget(add_lora_btn)
        lora_header_row.addStretch()

        gen_layout.addLayout(lora_header_row)

        # LoRA列表容器（滚动区域）
        self.lora_scroll = QScrollArea()
        self.lora_scroll.setWidgetResizable(True)
        self.lora_scroll.setMaximumHeight(100)
        self.lora_scroll.setStyleSheet("QScrollArea { border: 1px solid palette(mid); border-radius: 3px; background-color: palette(base); }")

        self.lora_container = QWidget()
        self.lora_layout = QVBoxLayout(self.lora_container)
        self.lora_layout.setContentsMargins(3, 3, 3, 3)
        self.lora_layout.setSpacing(3)
        self.lora_layout.addStretch()

        self.lora_scroll.setWidget(self.lora_container)
        gen_layout.addWidget(self.lora_scroll)

        # 存储LoRA数据: {name: weight}
        self.current_loras = {}

        outer_layout.addWidget(self.gen_settings_container)

        # --- 3. 底部生成按钮 (从上方移动到这里) ---
        # 远程生成按钮行
        gen_btn_layout = QHBoxLayout()

        # 始终使用标准模板,不再提供切换选项
        gen_btn_layout.addStretch()

        # [NEW] 批量生成计数器 (优化版 - 简洁风格)
        self.batch_count_spin = QSpinBox()
        self.batch_count_spin.setRange(1, 100)
        self.batch_count_spin.setValue(1)
        self.batch_count_spin.setFixedWidth(60) # 稍微收窄，因为去掉了按钮
        self.batch_count_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.batch_count_spin.setToolTip("批量生成数量 (输入数字)")
        # 隐藏上下按钮，只显示数字框
        self.batch_count_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.batch_count_spin.setStyleSheet("""
            QSpinBox {
                padding: 5px;
                border: 1px solid palette(mid);
                border-radius: 4px;
                background-color: palette(base);
                color: palette(text);
                font-weight: bold;
            }
            QSpinBox:hover {
                border-color: palette(highlight);
            }
            QSpinBox:focus {
                border: 1px solid palette(highlight);
            }
        """)
        
        # 添加 "批量:" 标签，明确含义
        lbl_batch = QLabel("批量:")
        lbl_batch.setStyleSheet("color: palette(text); font-weight: bold;")
        gen_btn_layout.addWidget(lbl_batch)
        gen_btn_layout.addWidget(self.batch_count_spin)
        
        # 添加 "张" 单位标签
        lbl_unit = QLabel("张")
        lbl_unit.setStyleSheet("color: palette(mid);")
        gen_btn_layout.addWidget(lbl_unit)
        
        # Spacer
        gen_btn_layout.addSpacing(15)

        self.btn_remote_gen = QPushButton("生成")
        self.btn_remote_gen.setMinimumHeight(32)
        self.btn_remote_gen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remote_gen.setStyleSheet("""
            QPushButton {
                background-color: #ff4d00;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                border: 1px solid #cc3d00;
                font-size: 13px;
                padding-left: 20px;
                padding-right: 20px;
            }
            QPushButton:hover { background-color: #ff6a00; }
            QPushButton:pressed { background-color: #e64600; }
            QPushButton:disabled { background-color: #555; color: #aaa; border: none; }
        """)
        self.btn_remote_gen.clicked.connect(self._on_remote_gen_click)
        gen_btn_layout.addWidget(self.btn_remote_gen)
        
        gen_layout.addLayout(gen_btn_layout)

        # 将整个外层容器添加到父布局
        parent_layout.addWidget(gen_settings_outer)
        
        # 初始化持久化逻辑
        self._init_workspace_persistence()
    
    
    def _add_lora_item(self, name: str = "", weight: float = 1.0):
        """添加一个LoRA项到列表（下拉框模式）"""
        # 限制最多5个LoRA
        if len(self.current_loras) >= 5:
            print("[UI] 已达到LoRA数量上限（5个）")
            return
        
        # 获取所有可用的LoRA
        main_window = self.window()
        all_loras = []
        if hasattr(main_window, 'db_manager'):
            all_loras_raw = main_window.db_manager.get_unique_loras()
            for item in all_loras_raw:
                if isinstance(item, tuple):
                    all_loras.append(item[0] if item else "")
                else:
                    all_loras.append(str(item))
        
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(4, 2, 4, 2)
        item_layout.setSpacing(8)
        
        # LoRA下拉选择框
        lora_combo = QComboBox()
        lora_combo.setMinimumWidth(200)
        lora_combo.addItem("选择LoRA...")  # 默认提示项
        for lora in all_loras:
            if lora:
                lora_combo.addItem(lora)
        
        if name:
            index = lora_combo.findText(name)
            if index < 0:
                lora_combo.addItem(name)
                index = lora_combo.findText(name)
            if index >= 0:
                lora_combo.setCurrentIndex(index)
        
        # 当选择改变时更新数据
        lora_combo.currentTextChanged.connect(
            lambda text: self._on_lora_selection_changed(item_widget, text, lora_combo)
        )
        
        item_layout.addWidget(lora_combo)
        
        # 权重标签
        weight_label = QLabel("权重:")
        weight_label.setStyleSheet("color: palette(mid); font-size: 10px;")
        item_layout.addWidget(weight_label)
        
        # 权重输入
        weight_spin = QDoubleSpinBox()
        weight_spin.setRange(-2.0, 2.0)
        weight_spin.setSingleStep(0.01)  # 步长改为0.01
        weight_spin.setValue(round(weight, 2))
        weight_spin.setDecimals(2)  # 显示2位小数
        weight_spin.setMinimumWidth(70)  # 稍微加宽以容纳两位小数
        weight_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        weight_spin.setStyleSheet("""
            QDoubleSpinBox {
                padding: 2px;
                font-size: 11px;
                border: 1px solid palette(mid);
                border-radius: 2px;
            }
        """)
        # 保存引用到combo box的userData
        lora_combo.setProperty("weight_spin", weight_spin)
        weight_spin.valueChanged.connect(
            lambda v: self._update_lora_weight_from_combo(lora_combo, round(v, 2))
        )
        item_layout.addWidget(weight_spin)
        
        # 删除按钮
        del_btn = QPushButton("✕")
        del_btn.setMaximumWidth(25)
        del_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: palette(mid);
                font-weight: bold;
            }
            QPushButton:hover {
                color: red;
            }
        """)
        del_btn.clicked.connect(lambda: self._remove_lora_item_widget(item_widget, lora_combo))
        item_layout.addWidget(del_btn)
        
        # 插入到stretch之前
        count = self.lora_layout.count()
        self.lora_layout.insertWidget(count - 1, item_widget)
        
        # 如果指定了名称，添加到数据并设置属性
        if name and name != "选择LoRA...":
            self.current_loras[name] = weight
            lora_combo.setProperty("selected_lora", name)  # 设置属性，防止重复检测
            # print(f"[UI] 添加LoRA: {name} (权重: {weight})")
    
    def _on_lora_selection_changed(self, widget, text, combo):
        """当LoRA选择改变时"""
        if text == "选择LoRA..." or not text:
            # 从数据中移除（如果之前有选择）
            old_data = combo.property("selected_lora")
            if old_data and old_data in self.current_loras:
                del self.current_loras[old_data]
            combo.setProperty("selected_lora", None)
            self._save_loras()
            return
        
        # 检查是否重复
        if text in self.current_loras:
            # 恢复之前的选择或重置
            old_data = combo.property("selected_lora")
            if old_data:
                index = combo.findText(old_data)
                if index >= 0:
                    combo.setCurrentIndex(index)
            else:
                combo.setCurrentIndex(0)
            # print(f"[UI] LoRA '{text}' 已被使用")
            return
        
        # 更新数据
        old_name = combo.property("selected_lora")
        if old_name and old_name in self.current_loras:
            del self.current_loras[old_name]
        
        weight_spin = combo.property("weight_spin")
        weight = weight_spin.value() if weight_spin else 1.0
        self.current_loras[text] = weight
        combo.setProperty("selected_lora", text)
        self._save_loras()
        # print(f"[UI] 选择LoRA: {text} (权重: {weight})")
    
    # [Removed redundant _log method that was overwritten]

    def _update_lora_weight_from_combo(self, combo, weight):
        """从ComboBox更新LoRA权重"""
        lora_name = combo.property("selected_lora")
        if lora_name and lora_name in self.current_loras:
            self.current_loras[lora_name] = weight
            self._save_loras()
            # print(f"[UI] 更新LoRA权重: {lora_name} -> {weight}")
    
    def _remove_lora_item_widget(self, widget, combo):
        """删除LoRA项（ComboBox模式）"""
        lora_name = combo.property("selected_lora")
        if lora_name and lora_name in self.current_loras:
            del self.current_loras[lora_name]
            # print(f"[UI] 删除LoRA: {lora_name}")
        
        self.lora_layout.removeWidget(widget)
        widget.deleteLater()
        self._save_loras()
    
    def _remove_lora_item(self, name: str, widget: QWidget):
        """删除一个LoRA项（兼容旧方法）"""
        if name in self.current_loras:
            del self.current_loras[name]
        
        self.lora_layout.removeWidget(widget)
        widget.deleteLater()
        self._save_loras()
        # print(f"[UI] 删除LoRA: {name}")
    
    def _update_lora_weight(self, name: str, weight: float):
        """更新LoRA权重"""
        if name in self.current_loras:
            self.current_loras[name] = weight
            self._save_loras()
            # print(f"[UI] 更新LoRA权重: {name} -> {weight}")
    
    def _clear_lora_list(self, persist=True):
        """清空LoRA列表"""
        # 删除所有LoRA项（保留stretch）
        while self.lora_layout.count() > 1:
            item = self.lora_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.current_loras.clear()
        if persist:
            self._save_loras()
        # print(f"[UI] 清空LoRA列表")
    
    def _log(self, msg: str):
        """记录日志到列表和控制台"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {msg}"
        # print(log_entry) # 减少控制台输出
        ParameterPanel.generation_logs.append(log_entry)
    
    
    def _on_ai_optimize_click(self):
        """处理正向提示词AI优化按钮点击"""
        self._run_prompt_ai_optimization(is_negative=False)

    def _on_neg_ai_optimize_click(self):
        """处理反向提示词AI优化按钮点击"""
        self._run_prompt_ai_optimization(is_negative=True)

    def _show_history_menu(self, prompt_type):
        menu = QMenu(self)
        sessions = self.history_manager.get_sessions(prompt_type)
        
        if not sessions:
            action = QAction("暂无历史记录", self)
            action.setEnabled(False)
            menu.addAction(action)
        else:
            # Reverse order (newest first)
            for i, session in enumerate(reversed(sessions)):
                base = session['base']
                chain = session['chain']
                
                # Title for the session
                base_preview = (base[:20] + '...') if len(base) > 20 else (base or "空提示词")
                
                # Submenu for this session
                session_menu = menu.addMenu(f"系列 {len(sessions)-i}: {base_preview}")
                
                # Add Original
                action_orig = QAction(f"原始: {base_preview}", self)
                action_orig.triggered.connect(lambda checked, t=base: self._restore_history(prompt_type, t))
                session_menu.addAction(action_orig)
                
                # Add Versions
                for j, ver in enumerate(chain):
                    ver_preview = (ver[:30] + '...') if len(ver) > 30 else ver
                    action = QAction(f"V{j+1}: {ver_preview}", self)
                    action.triggered.connect(lambda checked, t=ver: self._restore_history(prompt_type, t))
                    session_menu.addAction(action)

        # Show menu at button position
        btn = self.btn_history if prompt_type == 'positive' else self.btn_neg_history
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _restore_history(self, prompt_type, text):
        target_edit = self.prompt_edit if prompt_type == 'positive' else self.neg_prompt_edit
        target_edit.setPlainText(text)

    def _on_ai_stream_update(self, chunk, is_negative):
        """处理AI流式输出更新"""
        if not self._ai_is_processing: return
        
        target_edit = self.neg_prompt_edit if is_negative else self.prompt_edit
        
        # 第一次收到数据时清空输入框
        if not hasattr(self, '_ai_stream_started') or not self._ai_stream_started:
            target_edit.clear()
            self._ai_stream_started = True
            
        target_edit.insertPlainText(chunk)
        # 滚动到底部
        cursor = target_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        target_edit.setTextCursor(cursor)

    def _on_ai_finished(self, success, result, is_negative, original_prompt):
        target_btn = self.btn_neg_ai_optimize if is_negative else self.btn_ai_optimize
        status_label = self.neg_ai_status_label if is_negative else self.ai_status_label
        target_edit = self.neg_prompt_edit if is_negative else self.prompt_edit
        
        # Check if cancelled (should be handled by cancellation flag but good to double check)
        if not self._ai_is_processing: return

        self._ai_is_processing = False
        target_btn.setText("✨ AI优化")
        target_btn.setEnabled(True)
        self.current_ai_worker = None
        self._ai_original_prompt = None
        
        if success:
            status_label.setText("✅ 优化成功")
            QTimer.singleShot(3000, lambda: status_label.setText(""))
            target_edit.setPlainText(result)
            
            # Record History
            p_type = 'negative' if is_negative else 'positive'
            self.history_manager.add_record(p_type, original_prompt, result)
        else:
            status_label.setText("❌ 失败")
            # 如果流式输出已经修改了内容，需要恢复原始内容
            if hasattr(self, '_ai_stream_started') and self._ai_stream_started:
                target_edit.setPlainText(original_prompt)
                
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "AI优化失败", result)

    def _run_prompt_ai_optimization(self, is_negative=False):
        """执行API优化通用流程"""
        from PyQt6.QtWidgets import QMessageBox
        from PyQt6.QtCore import QSettings
        
        target_edit = self.neg_prompt_edit if is_negative else self.prompt_edit
        target_btn = self.btn_neg_ai_optimize if is_negative else self.btn_ai_optimize
        status_label = self.neg_ai_status_label if is_negative else self.ai_status_label
        
        # 1. Cancel Logic
        if self._ai_is_processing:
            if self.current_ai_worker:
                self.current_ai_worker.is_cancelled = True
                self.current_ai_worker = None
            
            # Reset UI
            self._ai_is_processing = False
            target_btn.setText("✨ AI优化")
            status_label.setText("🚫 已取消")
            QTimer.singleShot(2000, lambda: status_label.setText(""))
            target_btn.setEnabled(True)
            self.btn_ai_optimize.setEnabled(True)
            self.btn_neg_ai_optimize.setEnabled(True)
            if hasattr(self, '_ai_original_prompt') and self._ai_original_prompt is not None:
                target_edit.setPlainText(self._ai_original_prompt)
            self._ai_stream_started = False
            self._ai_original_prompt = None
            return

        # 0. 检查API Key是否配置
        settings = QSettings("ComfyUIImageManager", "Settings")
        api_key = settings.value("glm_api_key", "")
        api_url = settings.value("ai_base_url", "")
        
        # 判断是否是本地或局域网地址
        is_local = any(x in api_url for x in ["localhost", "127.0.0.1", "192.168.", "10."])
        
        if not api_key and not is_local:
            reply = QMessageBox.question(
                self,
                "未配置API Key",
                "当前配置的不是本地模型，使用AI功能建议配置 API Key。\n\n"
                "如果您使用的是本地免密模型(如Ollama)，请点击'继续'。\n"
                "否则，是否现在前往设置配置 Key?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Ignore
            )
            if reply == QMessageBox.StandardButton.Yes:
                status_label.setText("请在设置中配置GLM API Key")
                QTimer.singleShot(3000, lambda: status_label.setText(""))
                return
        
        # 1. 弹出自定义对话框,询问用户需求
        existing_prompt = target_edit.toPlainText().strip()
        label_prefix = "反向" if is_negative else ""
        
        # 预设标签
        if is_negative:
            preset_tags = ["一键优化", "去除马赛克", "去除水印/文字", "提升清晰度", "修正肢体崩坏", "过滤低质量"]
        else:
            preset_tags = ["一键优化", "换背景", "丰富画面细节", "改为夜景风格", "电影级光影", "质感提升", "增加环境描述"]

        if existing_prompt:
            dialog_title = f"优化{label_prefix}提示词"
            dialog_label = f"请描述您的修改需求（点击标签可快速填入）："
        else:
            dialog_title = f"AI生成{label_prefix}提示词"
            dialog_label = f"请描述您想要的{label_prefix}图片内容（点击标签可快速填入）："
            
        dialog = AIPromptDialog(dialog_title, dialog_label, preset_tags, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        user_input = dialog.get_text()
        if not user_input.strip():
            return
        
        # 2. 锁定并显示处理状态
        self._ai_is_processing = True
        target_btn.setText("⏹️ 取消")
        status_label.setText("⏳ AI正在处理...")
        self._ai_original_prompt = existing_prompt
        
        # 3. 启动后台线程
        self.current_ai_worker = AIWorker(user_input, existing_prompt, is_negative)
        self.current_ai_worker.finished.connect(lambda s, r: self._on_ai_finished(s, r, is_negative, existing_prompt))
        
        # 连接流式更新信号
        self._ai_stream_started = False
        self.current_ai_worker.stream_update.connect(lambda chunk: self._on_ai_stream_update(chunk, is_negative))
        
        self.current_ai_worker.start()
    
    def _on_add_lora_click(self):

        """添加新的LoRA行"""
        # 直接添加空的LoRA项（用户从下拉框选择）
        self._add_lora_item("", 1.0)

    def _create_compact_header(self, title, copy_func):
        """创建紧凑的标题行 (替代笨重的 GroupBox)"""
        header = QHBoxLayout()
        header.setContentsMargins(4, 6, 4, 2)
        header.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-weight: bold; color: palette(text); font-size: 12px;")
        header.addWidget(lbl_title)
        
        header.addStretch()
        
        # 改用英文 "Copy"，防止乱码
        btn_copy = QPushButton("Copy") 
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fix_text_button(btn_copy) # 应用通用修复
        if copy_func:
            btn_copy.clicked.connect(copy_func)
        header.addWidget(btn_copy)
        return header

    def _fix_text_button(self, btn):
        """统一调整文字按钮尺寸，防止截断"""
        btn.setMinimumWidth(60) 
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                color: palette(mid);
                font-size: 11px;
                padding: 2px 8px;
                text-align: center;
            }
            QPushButton:hover { 
                background-color: palette(midlight);
                color: palette(highlight); 
            }
        """)

    def _copy_prompt(self):
        text = self.prompt_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._temp_notify("✅ 提示词已复制")
            # 查找复制按钮并临时改变文字
            self._flash_button_feedback(self.prompt_container, "✓")

    def _copy_neg_prompt(self):
        text = self.neg_prompt_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._temp_notify("✅ 反向提示词已复制")
            self._flash_button_feedback(self.neg_container, "✓")

    def _copy_all_params(self):
        """复制所有参数为文本格式"""
        all_text = f"Model: {self.model_label.text()}\n"
        all_text += f"{self.seed_label.text()}\n"
        all_text += f"Prompt: {self.prompt_edit.toPlainText()}\n"
        all_text += f"Negative: {self.neg_prompt_edit.toPlainText()}"
        QApplication.clipboard().setText(all_text)
        self._temp_notify("✅ 所有参数已复制")
        # print(f"[UI] 所有参数已复制")
        # 闪烁顶部卡片的复制按钮
        for btn in self.info_card.findChildren(QPushButton):
            if "复制" in btn.text():
                original = btn.text()
                btn.setText("✓ 已复制")
                btn.setStyleSheet("background-color: #4CAF50; color: white;")
                QTimer.singleShot(1000, lambda: [btn.setText(original), btn.setStyleSheet("")])
                break

    def _flash_button_feedback(self, group_box, symbol):
        """为分组内的复制按钮提供闪烁反馈"""
        for btn in group_box.findChildren(QPushButton):
            original = btn.text()
            btn.setText(symbol)
            btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
            QTimer.singleShot(800, lambda b=btn, t=original: [b.setText(t), b.setStyleSheet("")])

    def _toggle_gen_settings(self):
        """切换生成设置显示/隐藏"""
        is_visible = self.gen_settings_container.isVisible()
        self.gen_settings_container.setVisible(not is_visible)
        # 更新按钮文字和箭头
        self.btn_toggle_settings.setText("▼ 生成设置" if not is_visible else "▶ 生成设置")
    
    def _on_seed_random_toggled(self, checked):
        """随机种子复选框状态改变"""
        self.settings.setValue("seed_random", checked)
        self.seed_input.setEnabled(not checked)
        if checked:
            # 勾选随机也保持显示当前图片的seed，只是禁用编辑
            if self.last_image_seed:
                self.seed_input.setText(str(self.last_image_seed))
        else:
            # 取消随机 -> 恢复上一张图片的seed
            if self.last_image_seed:
                self.seed_input.setText(str(self.last_image_seed))
            else:
                self.seed_input.clear()
    
    def _set_resolution(self, width, height):
        """设置分辨率预设"""
        self.width_input.setValue(width)
        self.height_input.setValue(height)

    def _temp_notify(self, msg):
        main_win = self.window()
        if hasattr(main_win, 'statusBar'):
            main_win.statusBar().showMessage(msg, 2000)

    def update_info(self, meta_data):
        """更新UI - V4.0新版"""
        self.current_meta = meta_data # 保存当前元数据
        if not meta_data:
            self.clear_info()
            self.btn_apply_workspace.setEnabled(False)
            self.btn_remote_gen.setEnabled(False)
            return
            
        # 只有 ComfyUI 导出的图片才支持调用和生成
        has_workflow = 'workflow' in meta_data
        self.btn_apply_workspace.setEnabled(has_workflow)
        self.btn_remote_gen.setEnabled(has_workflow)
        self.btn_remote_gen.setToolTip("通过远程 ComfyUI 重新生成" if has_workflow else "非 ComfyUI 图片，暂不支持远程生成")
        
        # 启用复制按钮
        for btn in self.info_card.findChildren(QPushButton):
            if "复制" in btn.text():
                btn.setEnabled(True)

        params = meta_data.get('params', {})
        tech_info = meta_data.get('tech_info', {})
        loras = meta_data.get('loras', [])
        
        # 更新核心信息卡片
        # 模型名称可能在不同的字段中，需要多重查找
        model_name = (params.get('Model') or 
                     params.get('model') or 
                     params.get('model_name') or
                     meta_data.get('model') or
                     '未知模型')
        self.model_label.setText(f"🎨 {model_name}")
        
        seed = params.get('Seed', params.get('seed', '-'))
        self.seed_label.setText(f"{seed}")
        
        resolution = tech_info.get('resolution', '-')
        self.resolution_label.setText(f"{resolution}")
        
        steps = params.get('Steps', params.get('steps', '-'))
        self.steps_label.setText(f"{steps}")
        
        cfg = params.get('CFG scale', params.get('cfg', '-'))
        self.cfg_label.setText(f"{cfg}")
        
        sampler = params.get('Sampler', params.get('sampler_name', '-'))
        self.sampler_label.setText(f"{sampler}")
        
        # 更新LoRA展示 (简约文本)
        lora_texts = []
        for l in loras:
            if isinstance(l, dict):
                # 修复浮点数精度 bug: 0.850000001 -> 0.85
                name = l.get('name','')
                weight = l.get('weight', 1.0)
                try:
                    weight_rounded = round(float(weight), 2)
                    lora_texts.append(f"{name} ({weight_rounded})")
                except:
                    lora_texts.append(f"{name} ({weight})")
            else:
                lora_texts.append(str(l))
        self.info_lora_val.setText(", ".join(lora_texts) if lora_texts else "无")
        
        # 更新提示词展示 (只读滚动区)
        prompt_text = meta_data.get('prompt', '')
        neg_text = meta_data.get('negative_prompt', '')
        self.info_prompt_val.setPlainText(prompt_text)
        self.info_neg_val.setPlainText(neg_text)
        
        # --- 注意：解开关联，update_info 不再自动改动编辑区 ---
        # 只有调用 apply_to_workspace 时才会同步到编辑区

        # 更新详细信息 (只更新文字，不重建布局)
        def update_detail(key, value):
            if key in self.detail_widgets:
                self.detail_widgets[key].setText(str(value) if value else "-")

        update_detail("scheduler", params.get('Scheduler'))
        update_detail("denoise", params.get('Denoise'))
        update_detail("model_hash", params.get('Model hash'))
        
        if tech_info:
            update_detail("file_size", tech_info.get('file_size'))
            update_detail("format", tech_info.get('format'))
        else:
            for k in ["file_size", "format"]: update_detail(k, None)
        
        # 采样器（需要先from数据库加载列表，暂时只设置文本）
        # TODO: 从数据库加载采样器列表

    def apply_to_workspace(self):
        """将当前图片参数显式调用到生成工作区"""
        if not hasattr(self, 'current_meta') or not self.current_meta:
            self._temp_notify("⚠️ 未选中有效图片")
            return
            
        meta_data = self.current_meta
        params = meta_data.get('params', {})
        tech_info = meta_data.get('tech_info', {})
        loras = meta_data.get('loras', [])
        
        # 1. 提示词
        self.prompt_edit.setPlainText(meta_data.get('prompt', ''))
        self.neg_prompt_edit.setPlainText(meta_data.get('negative_prompt', ''))
        
        # 2. Seed
        seed = params.get('Seed', params.get('seed', '-'))
        if seed != '-':
            self.last_image_seed = seed
            self.seed_input.setText(str(seed))
            # 保持用户当前的随机设置，不自动改变
            # self.seed_random_checkbox.setChecked(False)
        
        # 3. 分辨率
        resolution = tech_info.get('resolution', '-')
        if resolution != '-' and 'x' in str(resolution):
            try:
                w, h = str(resolution).split('x')
                width, height = int(w.strip()), int(h.strip())
                for i in range(self.resolution_combo.count()):
                    res_data = self.resolution_combo.itemData(i)
                    if res_data and res_data[0] == width and res_data[1] == height:
                        self.resolution_combo.setCurrentIndex(i)
                        break
            except: pass
            
        # 4. Steps & CFG
        try:
            steps = params.get('Steps', params.get('steps'))
            if steps: self.steps_value.setValue(int(steps))
            cfg = params.get('CFG scale', params.get('cfg'))
            if cfg: self.cfg_value.setValue(float(cfg))
        except: pass

        # 5. Sampler
        try:
            sampler = params.get('Sampler', params.get('sampler_name'))
            if sampler:
                idx = self.sampler_combo.findText(sampler)
                if idx >= 0: self.sampler_combo.setCurrentIndex(idx)
        except: pass

        # 6. LoRAs
        # 清空当前LoRA
        self._clear_lora_list(persist=False)
        def _parse_lora_string(value: str):
            text = value.strip()
            name = text
            weight = 1.0
            if "(" in text and text.endswith(")"):
                idx = text.rfind("(")
                name = text[:idx].strip()
                weight_text = text[idx + 1:-1].strip()
                try:
                    weight = float(weight_text)
                except:
                    weight = 1.0
                if not name:
                    name = text
            return name, weight
        # 添加新LoRA
        for lora in loras:
            if isinstance(lora, dict):
                name = lora.get('name', '')
                weight = lora.get('weight', 1.0)
                if name:
                    self._add_lora_item(name, weight)
            elif isinstance(lora, str):
                name, weight = _parse_lora_string(lora)
                if name:
                    self._add_lora_item(name, weight)
        self._save_loras()

    def _save_loras(self):
        """保存当前LoRA配置到Settings"""
        try:
            # self.current_loras 是 {name: weight} 字典
            # 转换为 list of dicts 以便扩展
            lora_list = []
            for name, weight in self.current_loras.items():
                lora_list.append({"name": name, "weight": weight})
            
            json_str = json.dumps(lora_list)
            self.settings.setValue("gen_loras", json_str)
        except Exception as e:
            print(f"Error saving LoRAs: {e}")

    def _load_loras(self):
        """从Settings加载LoRA配置"""
        try:
            json_str = self.settings.value("gen_loras", "[]", type=str)
            if not json_str: return
            
            lora_list = json.loads(json_str)
            if not isinstance(lora_list, list): return
            
            self._clear_lora_list(persist=False)
            for lora in lora_list:
                if isinstance(lora, dict):
                    name = lora.get("name", "")
                    weight = lora.get("weight", 1.0)
                    if name:
                        self._add_lora_item(name, weight)
        except Exception as e:
            print(f"Error loading LoRAs: {e}")

    def _init_workspace_persistence(self):
        """初始化工作区持久化：连接信号并加载初始值"""
        
        # 1. Prompt & Negative Prompt
        self.prompt_edit.textChanged.connect(
            lambda: self.settings.setValue("gen_prompt", self.prompt_edit.toPlainText())
        )
        saved_prompt = self.settings.value("gen_prompt", "", type=str)
        if saved_prompt: self.prompt_edit.setPlainText(saved_prompt)

        self.neg_prompt_edit.textChanged.connect(
            lambda: self.settings.setValue("gen_negative", self.neg_prompt_edit.toPlainText())
        )
        saved_neg = self.settings.value("gen_negative", "", type=str)
        if saved_neg: self.neg_prompt_edit.setPlainText(saved_neg)

        # 2. Seed (Input) - Random checkbox is already handled
        self.seed_input.textChanged.connect(
            lambda t: self.settings.setValue("gen_seed", t)
        )
        saved_seed = self.settings.value("gen_seed", "-1", type=str)
        if saved_seed: self.seed_input.setText(saved_seed)

        # 3. Steps
        self.steps_value.valueChanged.connect(
            lambda v: self.settings.setValue("gen_steps", v)
        )
        saved_steps = self.settings.value("gen_steps", 0, type=int)
        if saved_steps > 0: self.steps_value.setValue(saved_steps)

        # 4. CFG
        self.cfg_value.valueChanged.connect(
            lambda v: self.settings.setValue("gen_cfg", v)
        )
        saved_cfg = self.settings.value("gen_cfg", 0.0, type=float)
        if saved_cfg > 0: self.cfg_value.setValue(saved_cfg)

        # 5. Batch Count
        self.batch_count_spin.valueChanged.connect(
            lambda v: self.settings.setValue("gen_batch_count", v)
        )
        saved_batch = self.settings.value("gen_batch_count", 0, type=int)
        if saved_batch > 0: self.batch_count_spin.setValue(saved_batch)

        # 6. Resolution (Combo) - Saving logic
        def _on_res_change(index):
            data = self.resolution_combo.currentData()
            if data:
                self.settings.setValue("gen_width", data[0])
                self.settings.setValue("gen_height", data[1])
        self.resolution_combo.currentIndexChanged.connect(_on_res_change)
        # Note: Loading is handled in _populate_resolutions

        # 7. Sampler (Combo) - Saving logic
        self.sampler_combo.currentTextChanged.connect(
            lambda t: self.settings.setValue("gen_sampler", t)
        )
        # Note: Loading is handled in _populate_samplers

        # 8. LoRAs
        self._load_loras()

    def _on_remote_gen_click(self):
        """处理远程生成点击"""
        btn = self.btn_remote_gen
        original_text = btn.text()
        btn.setEnabled(False)
        btn.setText("发送中...")
        def _restore_btn():
            btn.setEnabled(True)
            btn.setText(original_text)
        # 清空上一次的日志
        ParameterPanel.generation_logs.clear()
        self._log("========== 开始生成参数准备 ==========")
        
        # 始终使用标准模板workflow (不再参照图片)
        self._log("[Main] 使用<标准模版>工作流")
        raw_workflow = DEFAULT_T2I_WORKFLOW

        # 深拷贝以防污染原始数据
        try:
            workflow = copy.deepcopy(raw_workflow)
        except Exception as e:
            self._log(f"Workflow 深拷贝失败: {e}")
            _restore_btn()
            return
            
        params = self.current_meta.get('params', {}) if self.current_meta else {} 
        # 智能同步修改后的提示词到工作流 (V5.4 精准透明版)
        new_prompt = self.prompt_edit.toPlainText().strip()
        new_neg = self.neg_prompt_edit.toPlainText().strip()
        
        # 1. 注入提示词 (智能追踪版)
        def find_prompt_nodes_by_tracing(wf):
            """
            通过遍历图结构寻找提示词节点 (KSampler -> positive/negative -> CLIPTextEncode)
            返回: (pos_id, neg_id)
            """
            ks_nodes = []
            # 1. 找 所有 KSampler
            for nid, node in wf.items():
                ctype = node.get('class_type', '').lower()
                if 'ksampler' in ctype:
                    ks_nodes.append(node)
            
            if not ks_nodes: return None, None
            
            # 使用第一个 KSampler 进行追踪
            ks_node = ks_nodes[0]
            
            def trace_back(current_node_id, visited=None):
                if visited is None: visited = set()
                if current_node_id in visited: return None
                visited.add(current_node_id)
                
                curr_node = wf.get(str(current_node_id))
                if not curr_node: return None
                
                ctype = curr_node.get('class_type', '').lower()
                
                # 找到目标
                if 'cliptextencode' in ctype:
                    return str(current_node_id)
                
                # 🛑 阻断逻辑：遇到 ZeroOut/SetArea/Avg 等修改/衍生 Conditioning 的节点，停止回溯
                # 这些节点通常意味着当前的 conditioning 是从另一个 conditioning 衍生出来的（例如把正向转为负向）
                # 我们不希望追踪到原始的 source (即正向提示词节点)
                if 'zeroout' in ctype or 'setarea' in ctype or 'combine' in ctype or 'average' in ctype:
                    return None
                    
                # 穿透逻辑 (Conditioning 传递)
                # 检查 inputs 中是否有连接到其他节点的 conditioning/positive/negative
                inputs = curr_node.get('inputs', {})
                for k, v in inputs.items():
                    # 常见的穿透键名
                    if k in ['conditioning', 'positive', 'negative', 'clip', 'samples'] or True: # 激进策略：检查所有输入
                        if isinstance(v, list) and len(v) >= 1:
                            source_id = str(v[0])
                            # 递归寻找
                            res = trace_back(source_id, visited)
                            if res: return res
                return None

            # 从 KSampler 的 inputs 开始回溯
            pos_id = None
            neg_id = None
            
            inputs = ks_node.get('inputs', {})
            
            # 找 positive
            if 'positive' in inputs and isinstance(inputs['positive'], list):
                pos_id = trace_back(str(inputs['positive'][0]))
                
            # 找 negative
            if 'negative' in inputs and isinstance(inputs['negative'], list):
                neg_id = trace_back(str(inputs['negative'][0]))
                
            return pos_id, neg_id

        # 优先使用 Metadata ID
        pos_node_id = self.current_meta.get('prompt_node_id')
        neg_node_id = self.current_meta.get('negative_prompt_node_id')
        
        # 如果 ID 无效 或 相同（冲突），尝试智能追踪
        if not pos_node_id or not neg_node_id or pos_node_id == neg_node_id or \
           pos_node_id not in workflow or neg_node_id not in workflow:
            self._log("[Comfy] ⚠️ Prompt ID 无效或冲突(相同)，尝试智能图追踪...")
            found_pos, found_neg = find_prompt_nodes_by_tracing(workflow)
            
            if found_pos:
                pos_node_id = found_pos
                self._log(f"[Comfy] -> 追踪到正向提示词节点: {pos_node_id}")
                
            if found_neg:
                neg_node_id = found_neg
                self._log(f"[Comfy] -> 追踪到反向提示词节点: {neg_node_id}")

        self._log(f"\n[Comfy] --- 准备提交生成任务 ---")
        
        # 执行注入
        if pos_node_id and pos_node_id in workflow:
            workflow[pos_node_id]['inputs']['text'] = new_prompt
            self._log(f"[Comfy] -> 正向提示词注入节点: {pos_node_id} (CLIPTextEncode)")
        else:
            self._log(f"[Comfy] ⚠️ 注入失败: 未找到正向提示词节点")

        if neg_node_id and neg_node_id in workflow:
            workflow[neg_node_id]['inputs']['text'] = new_neg
            self._log(f"[Comfy] -> 反向提示词注入节点: {neg_node_id} (CLIPTextEncode)")
        else:
            self._log(f"[Comfy] ⚠️ 注入失败: 未找到反向提示词节点")
            if new_neg:
                self._temp_notify("⚠️ 反向提示词无法生效 (此工作流使用自动 ZeroOut 负面条件)")

        # 2. 读取用户自定义参数 (Seed/Res/Steps/CFG/Sampler)
        # Seed - 检查是否随机（-1或勾选checkbox）
        user_seed = None
        if not self.seed_random_checkbox.isChecked():
            # 不随机，读取输入框
            user_seed_text = self.seed_input.text().strip()
            if user_seed_text and user_seed_text != "-1":
                try:
                    user_seed = int(user_seed_text)
                except:
                    pass  # 无效输入，忽略
        
        # 从下拉框获取分辨率
        res_data = self.resolution_combo.currentData()
        user_width, user_height = res_data if res_data else (512, 768)
        
        user_steps = self.steps_value.value()
        user_cfg = self.cfg_value.value()
        user_sampler = self.sampler_combo.currentText()
        
        # 3. 注入用户自定义参数到workflow
        self._log(f"\n[Comfy] ========== 参数注入开始 ==========")
        self._log(f"[Comfy] 用户参数:")
        self._log(f"  → Seed: {user_seed if user_seed is not None else '随机'}")
        self._log(f"  → 分辨率: {user_width}x{user_height}")
        self._log(f"  → Steps: {user_steps}")
        self._log(f"  → CFG: {user_cfg}")
        self._log(f"  → Sampler: {user_sampler}")
        self._log(f"  → LoRAs: {list(self.current_loras.keys())}")
        
        # 遍历workflow节点注入参数
        self._log(f"\n[Comfy] 开始遍历workflow节点...")
        modified_nodes = []
        
        for node_id, node in workflow.items():
            class_type = node.get('class_type', '').lower()
            inputs = node.get('inputs', {})
            
            # print(f"[Comfy] 检查节点 {node_id}: {node.get('class_type')} ({class_type})")
            
            # KSampler节点：注入seed、steps、cfg、sampler
            if 'ksampler' in class_type:
                # Seed
                if 'seed' in inputs:
                    if user_seed is not None:
                        final_seed = int(user_seed)
                    else:
                        # “超随机种子”实现：使用 OS 级真随机源
                        # 锁定 18-20 位长度，使用 64 位无符号整数上限
                        # ComfyUI 最大支持范围约为 2^64-1 (18,446,744,073,709,551,615)
                        final_seed = random.SystemRandom().randint(10**17, 18446744073709551614)
                    
                    inputs['seed'] = final_seed
                    # 实时反馈：将生成的随机种子显示在界面上，不再隐藏
                    self.seed_input.setText(str(final_seed))
                    self._log(f"[Comfy] -> 注入超随机Seed: 节点 {node_id} -> {final_seed}")
                
                # Steps
                if 'steps' in inputs:
                    inputs['steps'] = user_steps
                    self._log(f"[Comfy] -> 注入Steps: 节点 {node_id} -> {user_steps}")
                
                # CFG
                if 'cfg' in inputs:
                    inputs['cfg'] = user_cfg
                    self._log(f"[Comfy] -> 注入CFG: 节点 {node_id} -> {user_cfg}")
                
                # Sampler
                if 'sampler_name' in inputs and user_sampler:
                    inputs['sampler_name'] = user_sampler
                    self._log(f"[Comfy] -> 注入Sampler: 节点 {node_id} -> {user_sampler}")
            
            # CheckpointLoader节点: 注入模型名称
            if 'checkpointloader' in class_type:
                if 'ckpt_name' in inputs:
                    # 从UI Model Label获取当前模型名称 (去除 "🎨 " 前缀)
                    current_model = self.model_label.text().replace("🎨 ", "").strip()
                    
                    if current_model and current_model != "未选择模型":
                         # 尝试从服务器列表中找到真正的全名
                         real_model_name = self._find_best_model_match(current_model)
                         
                         if real_model_name:
                             inputs['ckpt_name'] = real_model_name
                             self._log(f"[Comfy] -> 注入Model (精准匹配): {real_model_name}")
                         else:
                             # 回退到启发式补全
                             if '.' not in current_model:
                                 current_model += ".safetensors"
                                 self._log(f"[Comfy] ⚠️ 本地未找到匹配模型，尝试自动补全: {current_model}")
                             
                             inputs['ckpt_name'] = current_model
                             self._log(f"[Comfy] -> 注入Model: 节点 {node_id} -> {current_model}")
                    else:
                         self._log(f"[Comfy] ⚠️ 未注入模型: UI未选择有效模型")
            
            # UNETLoader节点: 注入UNET模型名称
            if 'unetloader' in class_type:
                if 'unet_name' in inputs:
                    current_model = self.model_label.text().replace("🎨 ", "").strip()
                    
                    if current_model and current_model != "未选择模型":
                         real_model_name = self._find_best_model_match(current_model)
                         
                         if real_model_name:
                             inputs['unet_name'] = real_model_name
                             self._log(f"[Comfy] -> 注入UNET Model (精准匹配): {real_model_name}")
                         else:
                             if '.' not in current_model:
                                 current_model += ".safetensors"
                                 self._log(f"[Comfy] ⚠️ 本地未找到匹配UNET模型，尝试自动补全: {current_model}")
                             
                             inputs['unet_name'] = current_model
                             self._log(f"[Comfy] -> 注入UNET Model: 节点 {node_id} -> {current_model}")
                    else:
                         self._log(f"[Comfy] ⚠️ 未注入UNET模型: UI未选择有效模型")

            # LoraLoader节点：不再在主循环中处理，改为后处理
            # LoraLoaderModelOnly节点: 也在后处理中统一处理
            pass
            
            # Latent节点：注入分辨率（支持多种类型）
            # EmptyLatentImage, EmptySD3LatentImage, EmptySDXLLatentImage等
            if 'latentimage' in class_type and 'empty' in class_type:
                # print(f"[Comfy] 找到Latent节点 {node_id}: {node.get('class_type')}")
                # print(f"[Comfy]   原始参数: width={inputs.get('width')}, height={inputs.get('height')}")
                
                if 'width' in inputs and 'height' in inputs:
                    old_width = inputs['width']
                    old_height = inputs['height']
                    inputs['width'] = user_width
                    inputs['height'] = user_height
                    modified_nodes.append(node_id)
                    # print(f"[Comfy] ✅ 注入分辨率: 节点 {node_id}")
                    # print(f"[Comfy]   {old_width}x{old_height} → {user_width}x{user_height}")
                else:
                    # print(f"[Comfy] ⚠️ 节点缺少width/height字段: {list(inputs.keys())}")
                    pass
        
        # --- 专门处理 LoRA 注入 (更健壮的逻辑) ---
        if self.current_loras:
            # 1. 找到所有 LoraLoader 和 LoraLoaderModelOnly 节点
            lora_nodes = []
            for nid, node in workflow.items():
                node_class = node.get('class_type', '').lower()
                if 'loraloader' in node_class:  # 匹配 LoraLoader 和 LoraLoaderModelOnly
                    # 尝试将ID转为整数以便正确排序 ('9' < '10')
                    try:
                        nid_int = int(nid)
                    except:
                        nid_int = 999999
                    lora_nodes.append((nid_int, nid, node))
            
            # 2. 按ID排序，确保顺序一致
            lora_nodes.sort(key=lambda x: x[0])
            
            # 3. 按顺序注入
            lora_list = list(self.current_loras.items())
            self._log(f"[Comfy] 找到 {len(lora_nodes)} 个 LoraLoader 节点，UI中有 {len(lora_list)} 个 LoRA")
            
            # ⚠️ 警告检测与自动注入
            if not lora_nodes:
                self._log(f"[Comfy] ⚠️ 工作流中只有 0 个 LoraLoader，尝试自动注入...")
                
                # 尝试自动注入 LoRA 节点
                # 策略:
                # 1. 找到 KSampler 的 model 输入源 (通常是 CheckpointLoader)
                # 2. 在该源节点和所有下游节点之间插入 LoraLoader
                
                def try_inject_lora_node(wf, lora_name, lora_weight):
                    # 1. 寻找核心路径: KSampler -> model input -> Source Node
                    ks_node = None
                    for nid, node in wf.items():
                        if 'ksampler' in node.get('class_type', '').lower():
                            ks_node = node
                            break
                    
                    if not ks_node: return False
                    
                    # 获取模型源连接 [node_id, slot_idx]
                    model_link = ks_node.get('inputs', {}).get('model')
                    if not isinstance(model_link, list): return False
                    
                    source_id = str(model_link[0])
                    source_node = wf.get(source_id)
                    if not source_node: return False
                    
                    s_ctype = source_node.get('class_type', '')
                    self._log(f"[Comfy] 自动注入: 找到模型源节点 {source_id} ({s_ctype})")
                    
                    # 🛑 安全检查: 仅支持标准的 CheckpointLoader 节点
                    # 如果源节点是 Reroute, Primitive, 或其他自定义节点，盲目连接 slot 1 (CLIP) 会导致 'Bad Request'
                    if 'checkpointloader' not in s_ctype.lower():
                        self._log(f"[Comfy] ⚠️ 自动注入中止: 源节点类型 '{s_ctype}' 不是标准的 CheckpointLoader，无法确定 CLIP 连接位置。")
                        self._temp_notify(f"⚠️ 无法自动注入 LoRA: 不支持的节点类型 {s_ctype}")
                        return False
                    
                    # 2. 创建新 LoraLoader 节点
                    # 寻找可用ID
                    new_id = str(max([int(k) for k in wf.keys() if k.isdigit()] + [1000]) + 1)
                    
                    new_node = {
                        "inputs": {
                            "model": [source_id, 0], # 假设 CheckpointLoader 输出 0 是 MODEL
                            "clip": [source_id, 1],  # 假设 CheckpointLoader 输出 1 是 CLIP
                            "lora_name": lora_name,
                            "strength_model": lora_weight,
                            "strength_clip": lora_weight
                        },
                        "class_type": "LoraLoader",
                        "_meta": {
                            "title": "Auto Injected LoRA"
                        }
                    }
                    wf[new_id] = new_node
                    
                    # 3. 重定向所有引用了 Source Node 的节点
                    # 我们需要重定向两种连接: MODEL 连接和 CLIP 连接
                    # MODEL 通常在 slot 0, CLIP 在 slot 1
                    
                    redirect_count_m = 0
                    redirect_count_c = 0
                    
                    # 记录 source_nodeModel output (slot 0) and Clip output (slot 1) 
                    # 严格只重定向连接到 0 或 1 的 link
                    
                    for nid, node in wf.items():
                        if nid == new_id: continue # 跳过自己
                        
                        inputs = node.get('inputs', {})
                        for key, val in inputs.items():
                            if isinstance(val, list) and len(val) >= 1 and str(val[0]) == source_id:
                                params_slot = val[1] if len(val) > 1 else 0
                                
                                # 策略: 如果连的是 slot 0 (Model)，重定向到 NewNode slot 0 (Model)
                                # 如果连的是 slot 1 (Clip)，重定向到 NewNode slot 1 (Clip)
                                # LoraLoader 输出: 0=Model, 1=Clip
                                
                                # 其他 slot (如 2=VAE) 不动
                                if params_slot == 0:
                                    inputs[key] = [new_id, 0]
                                    redirect_count_m += 1
                                elif params_slot == 1:
                                    inputs[key] = [new_id, 1]
                                    redirect_count_c += 1
                                    
                    self._log(f"[Comfy] 自动注入成功: ID {new_id}, 重定向 Model引用 {redirect_count_m}个, Clip引用 {redirect_count_c}个")
                    return True

                # 目前只支持注入第一个 LoRA (多 LoRA 链式注入太复杂)
                if lora_list:
                    first_lora_name, first_lora_weight = lora_list[0]
                    if try_inject_lora_node(workflow, first_lora_name, first_lora_weight):
                        self._temp_notify("✨ 已自动为您即时修补工作流以支持 LoRA")
                    else:
                        # print(f"[Comfy] ⚠️ 自动注入失败: 无法分析图结构")
                        self._temp_notify("⚠️ 无法注入 LoRA (结构不支持)")
            
            # 如果有节点 (或刚注入了节点)，常规注入参数
            # 重新扫描一遍节点 (因为可能刚注入了)
            
            # ...重新执行原来的注入循环逻辑...
            # 为简单起见，我们只能在这里复制一遍查找逻辑，或者指望上面的注入已经设置好了参数
            # 上面的 try_inject_lora_node 已经设置了 lora_name 和 weight。
            # 如果有多个 LoRA，剩余的会被忽略 (如果只有一个插槽)
            
            if not lora_nodes:
                 pass # 已处理 (要么注入成功，要么失败)
            else:
                for i, (nid_int, nid, node) in enumerate(lora_nodes):
                    inputs = node.get('inputs', {})
                    if i < len(lora_list):
                        lora_name, lora_weight = lora_list[i]
                        
                        # 注入LoRA名称
                        if 'lora_name' in inputs:
                            inputs['lora_name'] = lora_name
                            self._log(f"[Comfy] -> 注入LoRA名称: 节点 {nid} -> {lora_name}")
                        
                        # 注入LoRA权重 (LoraLoader有两个权重, LoraLoaderModelOnly只有一个)
                        for weight_key in ['strength_model', 'strength_clip']:
                            if weight_key in inputs:
                                inputs[weight_key] = lora_weight
                        self._log(f"[Comfy] -> 注入LoRA权重: 节点 {nid} ({node.get('class_type')}) -> {lora_weight}")
                    else:
                        # 关键修复: 多余的 LoRA 节点必须静音 (设为0)，否则会残留原图的 LoRA
                        self._log(f"[Comfy] 节点 {nid} (LoraLoader) 超出UI列表数量，执行静音 (Strength=0)")
                        for weight_key in ['strength_model', 'strength_clip']:
                            if weight_key in inputs:
                                inputs[weight_key] = 0.0          
        # print(f"\n[Comfy] ========== 参数注入完成 ==========")
        # print(f"[Comfy] 修改的节点: {modified_nodes}")
        # print(f"[Comfy] --- 任务数据准备就绪 ---\n")
        
        # 发送请求信号
        batch_count = self.batch_count_spin.value()
        self.remote_gen_requested.emit(workflow, batch_count)
        QTimer.singleShot(800, _restore_btn)

    def set_available_models(self, models: List[str]):
        """设置可用模型列表 (来自ComfyUI)"""
        self.available_models = models
        # print(f"[UI] 已接收可用模型列表: {len(models)} 个")

    def _find_best_model_match(self, ui_name: str) -> str:
        """在可用模型列表中寻找最佳匹配 (优先精准，后包含)"""
        if not hasattr(self, 'available_models') or not self.available_models:
            return None
            
        # 0. 预处理：移除潜在的 "🎨 " 前缀 (防守性编程)
        clean_name = ui_name.replace("🎨 ", "").strip()
        
        # 1. 精确匹配
        if clean_name in self.available_models:
            return clean_name
            
        # 2. 尝试加上 .safetensors 或 .ckpt 后匹配
        for ext in ['.safetensors', '.ckpt']:
            if clean_name + ext in self.available_models:
                return clean_name + ext
        
        # 3. 忽略路径匹配 (ui_name = "model.safetensors", available = "SDXL/model.safetensors")
        for m in self.available_models:
            if m.endswith(clean_name) or m.endswith(clean_name + ".safetensors"):
                return m
                
        # 4. 模糊包含匹配 (最宽松 - 慎用，但在不匹配时好过没有)
        # ui_name = "turbo_bf16" -> "z_image_turbo_bf16.safetensors"
        for m in self.available_models:
            if clean_name in m:
                return m
                
        return None

    def _clear_layout(self, layout):
        """递归清空布局"""
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self._clear_layout(child.layout())

    def clear_info(self):
        """清空信息"""
        self.model_label.setText("🎨 未选择模型")
        self.seed_label.setText("-")
        
        # 禁用操作按钮
        for btn in self.info_card.findChildren(QPushButton):
            if "复制" in btn.text():
                btn.setEnabled(False)
        self.resolution_label.setText("-")
        self.steps_label.setText("-")
        self.cfg_label.setText("-")
        self.sampler_label.setText("-")
        
        # 清除详情区文字（不再清除布局）
        for val_widget in self.detail_widgets.values():
            val_widget.setText("-")
        
        # 生成工作区现在是独立的，不随图片清空而清空
        # self.prompt_edit.clear()
        # self.neg_prompt_edit.clear()
    def eventFilter(self, source, event):
        """实现点击复制逻辑"""
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            if source is self.info_prompt_val.viewport():
                self._copy_to_clip(self.info_prompt_val.toPlainText(), "✨ 提示词已复制")
                return True
            elif source is self.info_neg_val.viewport():
                self._copy_to_clip(self.info_neg_val.toPlainText(), "🚫 反向词已复制")
                return True
        return super().eventFilter(source, event)

    def _copy_to_clip(self, text, msg):
        """通用复制并提示函数"""
        if text:
            QApplication.clipboard().setText(text)
            self._temp_notify(f"✅ {msg}")
