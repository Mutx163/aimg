from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTextEdit, QScrollArea,
                             QFrame, QGridLayout, QHBoxLayout, QPushButton, QApplication, 
                             QSplitter, QGroupBox, QSpinBox, QDoubleSpinBox, QSlider, 
                             QComboBox, QLineEdit, QCheckBox, QDialog, QToolButton,
                             QAbstractSpinBox, QSizePolicy, QListWidget, QListWidgetItem, QMessageBox,
                             QStackedWidget)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSettings, QThread, QEvent, QBuffer, QIODevice, QByteArray
from PyQt6.QtGui import QFont, QAction, QImage, QGuiApplication
from typing import List, Dict, Any, Tuple, Optional
import random
import copy
import json
import base64
import os
import re
import uuid
from datetime import datetime
from src.assets.default_workflows import DEFAULT_T2I_WORKFLOW


def parse_compare_weights_expression(text: str) -> List[float]:
    """解析 LoRA 对比权重表达式，支持列表和 start:end:step。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("请先输入 LoRA 权重，例如 0.7,0.75 或 0.7:0.9:0.05")

    tokens = [t.strip() for t in re.split(r"[,，;\n；]+", raw) if t.strip()]
    values: List[float] = []

    for token in tokens:
        if ":" not in token:
            try:
                val = float(token)
            except Exception as exc:
                raise ValueError(f"无法解析权重: {token}") from exc
            values.append(round(val, 6))
            continue

        parts = [p.strip() for p in token.split(":")]
        if len(parts) != 3:
            raise ValueError(f"区间写法错误: {token}，应为 start:end:step")
        try:
            start = float(parts[0])
            end = float(parts[1])
            step = float(parts[2])
        except Exception as exc:
            raise ValueError(f"区间值无法解析: {token}") from exc

        if abs(step) < 1e-12:
            raise ValueError(f"区间步长不能为 0: {token}")
        if (end - start) * step < 0:
            raise ValueError(f"区间方向与步长不一致: {token}")

        cur = start
        if step > 0:
            while cur <= end + 1e-9:
                values.append(round(cur, 6))
                cur += step
        else:
            while cur >= end - 1e-9:
                values.append(round(cur, 6))
                cur += step

    deduped: List[float] = []
    seen = set()
    for v in values:
        key = f"{v:.6f}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(v)

    if not deduped:
        raise ValueError("未解析到任何权重值")
    return deduped

class LoraSelectorWidget(QWidget):
    selection_changed = pyqtSignal(str) # Emits new path

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(2)
        
        self.label = QLineEdit() # Use ReadOnly LineEdit for display
        self.label.setReadOnly(True)
        self.label.setPlaceholderText("点击选择 LoRA...")
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.installEventFilter(self)
        self.label.setStyleSheet("""
            QLineEdit {
                border: 1px solid palette(mid);
                background-color: palette(base);
                border-radius: 3px;
                padding: 2px 4px;
                color: palette(text);
            }
            QLineEdit:hover {
                border-color: palette(highlight);
                background-color: palette(alternate-base);
            }
        """)
        
        layout.addWidget(self.label)
        
        self._current_path = ""
        self._all_loras_getter = None # Function to get all loras
        
    def set_data_source(self, getter_func):
        self._all_loras_getter = getter_func
        
    def set_current_lora(self, path):
        self._current_path = path
        self.label.setText(os.path.basename(path) if path else "")
        self.label.setToolTip(path)
        # self.setProperty("selected_lora", path) # REMOVED: Managed by controller (ParamPanel) to track changes
        
    def get_current_lora(self):
        return self._current_path
        
    def _open_dialog(self):
        if not self._all_loras_getter: return
        try:
            loras = self._all_loras_getter()
            # print(f"[DEBUG] LoraSelector opened with {len(loras)} loras")
            from src.ui.dialogs.lora_selection_dialog import LoraSelectionDialog
            dlg = LoraSelectionDialog(loras, self)
            
            # Pre-select if available
            # (Dialog logic to expand to current would be nice but optional)
            
            if dlg.exec():
                selected = dlg.selected_lora
                if selected:
                    selected_profile = getattr(dlg, "selected_lora_profile", {}) or {}
                    self.setProperty("selected_lora_profile", selected_profile)
                    self.set_current_lora(selected)
                    self.selection_changed.emit(selected)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开LoRA选择窗口失败: {str(e)}")
            import traceback
            traceback.print_exc()

    def eventFilter(self, source, event):
        if source is self.label and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self._open_dialog()
                return True
        return super().eventFilter(source, event)

class AIWorker(QThread):
    finished = pyqtSignal(bool, str)  # (success, result)
    stream_update = pyqtSignal(str)   # (chunk)
    
    def __init__(self, user_input, existing_prompt, is_negative, lora_guidance: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.user_input = user_input
        self.existing_prompt = existing_prompt
        self.is_negative = is_negative
        self.lora_guidance = dict(lora_guidance or {})
        self.is_cancelled = False
    
    def run(self):
        emitted = False
        try:
            if self.is_cancelled:
                self.finished.emit(False, "已取消")
                return
            from src.core.ai_prompt_optimizer import AIPromptOptimizer
            optimizer = AIPromptOptimizer()
            
            def on_stream_callback(chunk):
                if not self.is_cancelled:
                    self.stream_update.emit(chunk)
            
            success, result = optimizer.optimize_prompt(
                self.user_input, 
                self.existing_prompt,
                is_negative=self.is_negative,
                stream_callback=on_stream_callback,
                lora_guidance=self.lora_guidance,
            )
            if not self.is_cancelled:
                self.finished.emit(success, result)
                emitted = True
            else:
                self.finished.emit(False, "已取消")
                emitted = True
        except Exception as e:
            if not self.is_cancelled:
                self.finished.emit(False, f"处理异常: {str(e)}")
                emitted = True
        finally:
            if self.is_cancelled and not emitted:
                self.finished.emit(False, "已取消")

class ImagePromptWorker(QThread):
    finished = pyqtSignal(bool, str)
    stream_update = pyqtSignal(str)
    
    def __init__(self, image_b64: str, lora_guidance: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.image_b64 = image_b64
        self.lora_guidance = dict(lora_guidance or {})
        self.is_cancelled = False
    
    def run(self):
        try:
            if self.is_cancelled:
                return
            from src.core.ai_prompt_optimizer import AIPromptOptimizer
            optimizer = AIPromptOptimizer()
            
            def on_stream_callback(chunk):
                if not self.is_cancelled:
                    self.stream_update.emit(chunk)
            
            success, result = optimizer.generate_prompt_from_image(
                self.image_b64,
                stream_callback=on_stream_callback,
                lora_guidance=self.lora_guidance,
            )
            if not self.is_cancelled:
                self.finished.emit(success, result)
        except Exception as e:
            if not self.is_cancelled:
                self.finished.emit(False, f"处理异常: {str(e)}")

class AutoRefreshComboBox(QComboBox):
    """支持点击时自动触发刷新的下拉框"""
    about_to_show = pyqtSignal()
    
    def showPopup(self):
        self.about_to_show.emit()
        super().showPopup()

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
        
        quick_scene_row = QHBoxLayout()
        quick_scene_row.setSpacing(6)
        quick_scene_row.addWidget(QLabel("快捷场景:"))
        scene_tags = ["近景", "远景", "全身照", "半身照", "特写", "仰拍", "俯拍"]
        for tag in scene_tags:
            scene_btn = QPushButton(tag)
            scene_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            scene_btn.setStyleSheet(
                "QPushButton { padding: 2px 8px; border-radius: 10px; border: 1px solid palette(mid); background: palette(base); }"
                "QPushButton:hover { border-color: palette(highlight); color: palette(highlight); }"
            )
            scene_btn.clicked.connect(lambda checked, t=tag: self._on_tag_clicked(t))
            quick_scene_row.addWidget(scene_btn)
        quick_scene_row.addStretch()
        layout.addLayout(quick_scene_row)

        self.quick_cmd_edit = QLineEdit()
        self.quick_cmd_edit.setPlaceholderText("快捷修改指令（可选）：如“改成夜景、增加景深、改为电影光影”")
        self.quick_cmd_edit.setClearButtonEnabled(True)
        layout.addWidget(self.quick_cmd_edit)

        # 输入框
        self.input_edit = SmartTextEdit()
        self.input_edit.setPlaceholderText("输入你的核心修改需求...\n提示: Enter 确定优化, Shift+Enter 换行")
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
        self.quick_cmd_edit.textChanged.connect(self._update_state)
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
        quick = self.quick_cmd_edit.text().strip()
        self.counter_label.setText(f"字数: {len(text) + len(quick)}")
        self.btn_ok.setEnabled(bool(text or quick))

    def _try_accept(self):
        text = self.get_text()
        if text:
            self.accept()

    def _clear_input(self):
        self.input_edit.clear()
        self.quick_cmd_edit.clear()

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
        main_text = self.input_edit.toPlainText().strip()
        quick = self.quick_cmd_edit.text().strip()
        if main_text and quick:
            return f"{main_text}；补充要求：{quick}"
        return main_text or quick

class ParameterPanel(QWidget):
    # 信号定义
    remote_gen_requested = pyqtSignal(dict, int, bool) # 请求远程生成 (带workflow, 批次数量, 是否随机seed)
    compare_generate_requested = pyqtSignal(dict) # LoRA 对比生成请求
    
    # 日志系统:使用简单的列表,不用信号
    generation_logs = []  # 类变量,存储所有生成日志
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("ComfyUIImageManager", "Settings")
        self._compact_breakpoint = 430
        self._layout_mode = ""
        
        # 内部状态
        self.current_meta = {}
        self.current_loras = {} # 存储当前选中的LoRA {name: weight}
        self.current_lora_meta = {} # 存储LoRA附加信息 {name: {note, prompt, auto_use_prompt}}
        self._ai_is_processing = False # AI处理并发锁
        self._img_prompt_processing = False
        self._img_prompt_loading_button = None
        self._img_original_prompt = None
        self._img_stream_started = False
        self.history_manager = AIHistoryManager()
        self.history_dialogs = {}
        self.current_ai_worker = None
        self.current_img_worker = None
        self._neg_bottom_dragging = False
        self._neg_bottom_start_y = 0
        self._neg_bottom_start_h = 0
        self._neg_bottom_start_top_size = 0
        self._neg_bottom_start_bottom_size = 0
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(8)
        
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.setHandleWidth(2)
        self.main_splitter.setChildrenCollapsible(False)
        self.layout.addWidget(self.main_splitter)
        
        # ========== 1. 顶部核心信息卡片 ==========
        self.info_card = QFrame()
        # 移除硬编码 palette 样式，依赖全局 QSS
        self.info_card.setObjectName("InfoCard") # 方便 QSS 定制
        info_card_layout = QVBoxLayout(self.info_card)
        info_card_layout.setContentsMargins(12, 12, 12, 12)
        info_card_layout.setSpacing(10)
        
        # 第一行：大标题和复制按钮（固定标题栏）
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
        
        info_header = QWidget()
        info_header_layout = QVBoxLayout(info_header)
        info_header_layout.setContentsMargins(12, 12, 12, 6)
        info_header_layout.setSpacing(6)
        info_header_layout.addLayout(title_row)
        
        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("CardSeparator")
        info_header_layout.addWidget(line)
        
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

        # 第四行：调度器 + 重绘幅度 (Denoise)
        add_stat(3, 0, "调度器", "info_scheduler_label")
        add_stat(3, 2, "重绘幅度", "info_denoise_label")

        # 第五行：LoRAs (改为独占行显示)
        lbl_lora = QLabel("LORAS")
        lbl_lora.setStyleSheet(self._label_style)
        lbl_lora.setFixedWidth(self._fixed_label_width) # 强制对齐
        self.info_lora_val = QLabel("-")
        self.info_lora_val.setStyleSheet(self._value_style)
        self.info_lora_val.setWordWrap(True)
        self.stats_grid.addWidget(lbl_lora, 4, 0)
        self.stats_grid.addWidget(self.info_lora_val, 4, 1, 1, 3)
        
        info_card_layout.addLayout(self.stats_grid)

        # --- 新增：原始提示词滚动查看区 (样式向SEED看齐) ---
        def add_scroll_info(label_text, attr_name, height):
            outer = QVBoxLayout()
            outer.setSpacing(4)
            
            header = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet(self._label_style)
            lbl.setFixedWidth(self._fixed_label_width)
            header.addWidget(lbl)
            header.addStretch()
            
            # 增加按钮
            btn_use = QPushButton("调用")
            btn_use.setFixedSize(45, 20)
            btn_use.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_use.setStyleSheet("""
                QPushButton {
                    background-color: transparent; border: 1px solid palette(highlight);
                    border-radius: 2px; font-size: 10px; color: palette(highlight);
                }
                QPushButton:hover { background-color: palette(highlight); color: white; }
            """)
            if "反向" in label_text:
                btn_use.clicked.connect(self._use_selected_neg_prompt)
            else:
                btn_use.clicked.connect(self._use_selected_prompt)
            header.addWidget(btn_use)
            
            edit = QTextEdit()
            edit.setReadOnly(True)
            edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            edit.setMaximumHeight(height)
            edit.setStyleSheet("background-color: palette(alternate-base); border-radius: 4px; padding: 5px; font-size: 11px; color: palette(text); border: none;")
            setattr(self, attr_name, edit)
            
            outer.addLayout(header)
            outer.addWidget(edit)
            info_card_layout.addLayout(outer)

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
        info_card_layout.addStretch()
        
        # 锁定卡片最小高度，防止切换时的视觉剧烈振荡
        self.info_card.setMinimumHeight(320)
        
        self.info_scroll = QScrollArea()
        self.info_scroll.setWidgetResizable(True)
        self.info_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.info_scroll.setWidget(self.info_card)
        
        self.info_outer = QWidget()
        info_outer_layout = QVBoxLayout(self.info_outer)
        info_outer_layout.setContentsMargins(0, 0, 0, 0)
        info_outer_layout.setSpacing(0)
        info_outer_layout.addWidget(info_header)
        info_outer_layout.addWidget(self.info_scroll)
        self.main_splitter.addWidget(self.info_outer)
        
        # ========== 2. 底部专用生成设置区域 (可编辑工作区) ==========
        self.gen_settings_outer = self._setup_generation_settings()
        self.main_splitter.addWidget(self.gen_settings_outer)
        
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 2)
        saved_splitter = self.settings.value("param_panel/workspace_splitter")
        if saved_splitter:
            self.main_splitter.restoreState(saved_splitter)
        else:
            self.main_splitter.setSizes([320, 540])
        self.main_splitter.splitterMoved.connect(lambda *_: self._save_panel_splitter_state())
        
        comfy_root = self.settings.value("comfy_root", "", type=str).strip()
        if comfy_root:
            self._refresh_comfyui_assets()
            self.refresh_lora_options()

    def _save_panel_splitter_state(self):
        self.settings.setValue("param_panel/workspace_splitter", self.main_splitter.saveState())

    def _save_prompt_splitter_state(self):
        if hasattr(self, "prompt_splitter"):
            self.settings.setValue("param_panel/prompt_splitter", self.prompt_splitter.saveState())

    def _populate_resolutions(self, preset_res, history_res):
        """填充分辨率下拉框（预设+历史，去重）"""
        self.last_preset_res = preset_res # 缓存以便管理窗口使用
        self.last_history_res = history_res
        
        # 暂时阻塞信号，防止清除/添加过程触发自动保存导致配置丢失
        self.resolution_combo.blockSignals(True)
        try:
            # 记录当前选中内容，以便刷新后恢复
            current_res = self.resolution_combo.currentData()
            
            # 合并自定义、预设和历史分辨率并去重
            custom_res = []
            custom_strs = self.settings.value("custom_resolutions", [], type=list)
            for res_str in custom_strs:
                try:
                    w_s, h_s = res_str.split('x')
                    custom_res.append((int(w_s), int(h_s)))
                except: continue
                
            all_res = set(preset_res + history_res + custom_res)
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

    def _open_resolution_manager(self):
        """打开分辨率管理对话框"""
        from src.ui.dialogs.resolution_manager_dialog import ResolutionManagerDialog
        
        preset = getattr(self, "last_preset_res", [])
        history = getattr(self, "last_history_res", [])
        
        dlg = ResolutionManagerDialog(preset, history, self)
        if dlg.exec():
            # 刷新一次显示
            main_window = self.window()
            if hasattr(main_window, "refresh_historical_params"):
                main_window.refresh_historical_params()
            else:
                # 备选：如果找不到主窗口刷新方法，尝试手动填充预设
                preset = [(512, 512), (768, 768), (1024, 1024), (512, 768), (768, 512), (1024, 768), (768, 1024)]
                self._populate_resolutions(preset, [])

    def _populate_samplers(self, samplers: List[str]):
        """填充采样器下拉框"""
        self.sampler_combo.blockSignals(True)
        try:
            current_sampler = self.sampler_combo.currentText()
            self.sampler_combo.clear()
            
            # 基础常用采样器列表 (ComfyUI 标准集)
            all_samplers = [
                "euler", "euler_ancestral", "heun", "heunpp2", "dpm_2", "dpm_2_ancestral", 
                "lms", "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu", "dpmpp_2m", 
                "dpmpp_2m_sde", "dpmpp_2m_sde_gpu", "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", 
                "ddim", "uni_pc", "uni_pc_bh2", "deis"
            ]
            
            # 合并历史采样器 (去重)
            if samplers:
                for s in samplers:
                    if s and s not in all_samplers:
                        all_samplers.append(s)
            
            for sampler in all_samplers:
                self.sampler_combo.addItem(sampler)
            
            # 优先恢复之前的选择
            target_sampler = current_sampler
            if not target_sampler:
                target_sampler = self.settings.value("gen_sampler", "euler", type=str)

            if target_sampler:
                index = self.sampler_combo.findText(target_sampler)
                if index >= 0:
                    self.sampler_combo.setCurrentIndex(index)
                    return

            if self.sampler_combo.count() > 0:
                self.sampler_combo.setCurrentIndex(0)
        finally:
            self.sampler_combo.blockSignals(False)

    def _populate_schedulers(self, schedulers: List[str]):
        """填充调度器下拉框"""
        self.scheduler_combo.blockSignals(True)
        try:
            current_scheduler = self.scheduler_combo.currentText()
            self.scheduler_combo.clear()
            
            # 基础常用调度器列表 (ComfyUI 标准集)
            all_schedulers = [
                "normal", "karras", "exponential", "sgm_uniform", "simple", 
                "ddim_uniform", "beta", "linear_quadratic", "ddpm"
            ]
            
            # 合并历史调度器 (去重)
            if schedulers:
                for s in schedulers:
                    if s and s not in all_schedulers:
                        all_schedulers.append(s)
            
            for scheduler in all_schedulers:
                self.scheduler_combo.addItem(scheduler)
            
            # 优先恢复选择
            target_scheduler = current_scheduler
            if not target_scheduler:
                target_scheduler = self.settings.value("gen_scheduler", "normal", type=str)

            if target_scheduler:
                index = self.scheduler_combo.findText(target_scheduler)
                if index >= 0:
                    self.scheduler_combo.setCurrentIndex(index)
                    return

            if self.scheduler_combo.count() > 0:
                self.scheduler_combo.setCurrentIndex(0)
        finally:
            self.scheduler_combo.blockSignals(False)

    def _populate_model_combo(self, combo: QComboBox, items: List[str], settings_key: str):
        combo.blockSignals(True)
        try:
            current_text = combo.currentText()
            combo.clear()
            combo.addItem("自动")
            if items:
                for item in items:
                    combo.addItem(item)
            target = current_text if current_text and current_text != "自动" else self.settings.value(settings_key, "", type=str)
            if target:
                index = combo.findText(target)
                if index >= 0:
                    combo.setCurrentIndex(index)
                    return
            combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(False)

    def _setup_generation_settings(self):
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
        
        header_row = QHBoxLayout()
        header_lbl = QLabel("🛠️ 生成工作区 (在此修改并生成)")
        header_lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: palette(highlight);")
        header_row.addWidget(header_lbl)
        header_row.addStretch()
        self.workspace_toggle_btn = QToolButton()
        self.workspace_toggle_btn.setText("收起")
        self.workspace_toggle_btn.setCheckable(True)
        saved_expanded = self.settings.value("gen_workspace_controls_expanded", True, type=bool)
        self.workspace_toggle_btn.setChecked(saved_expanded)
        self.workspace_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.workspace_toggle_btn.setFixedSize(52, 22)
        self.workspace_toggle_btn.setStyleSheet("""
            QToolButton {
                background-color: palette(button);
                border: 1px solid palette(mid);
                border-radius: 3px;
                color: palette(text);
                font-size: 10px;
            }
            QToolButton:hover { background-color: palette(midlight); }
            QToolButton:pressed { background-color: palette(light); }
        """)
        self.workspace_toggle_btn.toggled.connect(self._toggle_workspace_controls)
        header_row.addWidget(self.workspace_toggle_btn)
        outer_layout.addLayout(header_row)
        
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 禁用焦点触发的自动垂直滚动（防止跳转）
        self.workspace_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.workspace_scroll.verticalScrollBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        workspace_content = QWidget()
        workspace_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        workspace_layout = QVBoxLayout(workspace_content)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(6)
        self.workspace_scroll.setWidget(workspace_content)
        self.workspace_scroll.viewport().installEventFilter(self)

        # --- 1. 可编辑文本区 ---
        def create_edit_block(title, placeholder, height):
            # 纯净标题布局，由调用者决定按钮位置
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(4)
            
            lbl = QLabel(title)
            lbl.setStyleSheet(self._label_style)
            title_row.addWidget(lbl)
            
            return title_row, height

        # 正向提示词
        self.ai_status_label = QLabel("")
        self.ai_status_label.setStyleSheet("color: #6366f1; font-size: 10px;")
        self.neg_ai_status_label = QLabel("")
        self.neg_ai_status_label.setStyleSheet("color: #6366f1; font-size: 10px;")

        tab_idle_style = (
            "QToolButton {"
            "padding: 4px 10px; border: none; border-radius: 6px; color: #64748b; "
            "font-size: 11px; font-weight: 600; background: transparent;}"
            "QToolButton:hover { background: #e2e8f0; color: #334155; }"
        )
        tab_active_style = (
            "QToolButton {"
            "padding: 4px 10px; border: none; border-radius: 6px; color: white; "
            "font-size: 11px; font-weight: 700; background: #1e293b;}"
        )
        icon_btn_style = (
            "QPushButton {"
            "min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;"
            "border: none; border-radius: 6px; color: #64748b; background: transparent; font-size: 12px;}"
            "QPushButton:hover { background: #e2e8f0; color: #334155; }"
            "QPushButton:pressed { background: #cbd5e1; }"
            "QPushButton:disabled { color: #94a3b8; }"
        )
        ai_icon_btn_style = (
            "QPushButton {"
            "min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;"
            "border: none; border-radius: 6px; color: #4f46e5; background: #eef2ff; font-size: 12px; font-weight: 700;}"
            "QPushButton:hover { background: #e0e7ff; color: #4338ca; }"
            "QPushButton:pressed { background: #c7d2fe; }"
            "QPushButton:disabled { color: #94a3b8; background: #e2e8f0; }"
        )

        self.btn_history = QPushButton("历")
        self.btn_history.setToolTip("History (Positive)")
        self.btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history.setStyleSheet(icon_btn_style)
        self.btn_history.clicked.connect(lambda: self._show_history_dialog('positive'))

        self.btn_ai_optimize = QPushButton("AI")
        self.btn_ai_optimize.setToolTip("AI Optimize (Positive)")
        self.btn_ai_optimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_optimize.setStyleSheet(ai_icon_btn_style)
        self.btn_ai_optimize.clicked.connect(self._on_ai_optimize_click)

        self.btn_file_import = QPushButton("文")
        self.btn_file_import.setToolTip("Import Image from File")
        self.btn_file_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_file_import.setStyleSheet(icon_btn_style)
        self.btn_file_import.clicked.connect(self._on_file_import_click)

        self.btn_clipboard_import = QPushButton("贴")
        self.btn_clipboard_import.setToolTip("Import from Clipboard")
        self.btn_clipboard_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clipboard_import.setStyleSheet(icon_btn_style)
        self.btn_clipboard_import.clicked.connect(self._on_clipboard_import_click)

        self.btn_neg_history = QPushButton("历")
        self.btn_neg_history.setToolTip("History (Negative)")
        self.btn_neg_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_neg_history.setStyleSheet(icon_btn_style)
        self.btn_neg_history.clicked.connect(lambda: self._show_history_dialog('negative'))

        self.btn_neg_ai_optimize = QPushButton("AI")
        self.btn_neg_ai_optimize.setToolTip("AI Optimize (Negative)")
        self.btn_neg_ai_optimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_neg_ai_optimize.setStyleSheet(ai_icon_btn_style)
        self.btn_neg_ai_optimize.clicked.connect(self._on_neg_ai_optimize_click)

        self.btn_neg_file_import = QPushButton("文")
        self.btn_neg_file_import.setToolTip("Import Image from File")
        self.btn_neg_file_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_neg_file_import.setStyleSheet(icon_btn_style)
        self.btn_neg_file_import.clicked.connect(self._on_file_import_click)

        self.btn_neg_clipboard_import = QPushButton("贴")
        self.btn_neg_clipboard_import.setToolTip("Import from Clipboard")
        self.btn_neg_clipboard_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_neg_clipboard_import.setStyleSheet(icon_btn_style)
        self.btn_neg_clipboard_import.clicked.connect(self._on_clipboard_import_click)

        prompt_card = QFrame()
        prompt_card.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
            }
        """)
        prompt_card_layout = QVBoxLayout(prompt_card)
        prompt_card_layout.setContentsMargins(0, 0, 0, 0)
        prompt_card_layout.setSpacing(0)

        prompt_header = QWidget()
        prompt_header.setStyleSheet("""
            QWidget {
                background: #f8fafc;
                border-bottom: 1px solid #e2e8f0;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }
        """)
        prompt_header_layout = QHBoxLayout(prompt_header)
        prompt_header_layout.setContentsMargins(8, 6, 8, 6)
        prompt_header_layout.setSpacing(6)

        tab_wrap = QWidget()
        tab_wrap.setStyleSheet("QWidget { background: #e2e8f0; border-radius: 8px; }")
        tab_layout = QHBoxLayout(tab_wrap)
        tab_layout.setContentsMargins(2, 2, 2, 2)
        tab_layout.setSpacing(2)

        self.prompt_tab_positive = QToolButton()
        self.prompt_tab_positive.setText("正向提示")
        self.prompt_tab_positive.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prompt_tab_positive.setCheckable(True)
        self.prompt_tab_positive.clicked.connect(lambda: self._set_prompt_mode("positive"))
        tab_layout.addWidget(self.prompt_tab_positive)

        self.prompt_tab_negative = QToolButton()
        self.prompt_tab_negative.setText("反向提示")
        self.prompt_tab_negative.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prompt_tab_negative.setCheckable(True)
        self.prompt_tab_negative.clicked.connect(lambda: self._set_prompt_mode("negative"))
        tab_layout.addWidget(self.prompt_tab_negative)

        prompt_header_layout.addWidget(tab_wrap, 0, Qt.AlignmentFlag.AlignLeft)
        prompt_header_layout.addStretch()

        self.prompt_action_stack = QStackedWidget()
        prompt_actions = QWidget()
        prompt_actions_layout = QHBoxLayout(prompt_actions)
        prompt_actions_layout.setContentsMargins(0, 0, 0, 0)
        prompt_actions_layout.setSpacing(2)
        prompt_actions_layout.addWidget(self.btn_history)
        prompt_actions_layout.addWidget(self.btn_ai_optimize)
        prompt_actions_layout.addWidget(self.btn_file_import)
        prompt_actions_layout.addWidget(self.btn_clipboard_import)

        neg_actions = QWidget()
        self.neg_actions_layout = QHBoxLayout(neg_actions)
        self.neg_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.neg_actions_layout.setSpacing(2)
        self.neg_actions_layout.addWidget(self.btn_neg_history)
        self.neg_actions_layout.addWidget(self.btn_neg_ai_optimize)
        self.neg_actions_layout.addWidget(self.btn_neg_file_import)
        self.neg_actions_layout.addWidget(self.btn_neg_clipboard_import)

        self.prompt_action_stack.addWidget(prompt_actions)
        self.prompt_action_stack.addWidget(neg_actions)
        prompt_header_layout.addWidget(self.prompt_action_stack, 0, Qt.AlignmentFlag.AlignRight)
        prompt_card_layout.addWidget(prompt_header)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("输入画面描述...")
        self.prompt_edit.setMinimumHeight(96)
        self.prompt_edit.setStyleSheet("""
            QTextEdit {
                border: none;
                background: #ffffff;
                color: #0f172a;
                padding: 10px;
                font-size: 13px;
                line-height: 1.6;
            }
        """)

        self.neg_prompt_edit = QTextEdit()
        self.neg_prompt_edit.setPlaceholderText("输入过滤词...")
        self.neg_prompt_edit.setMinimumHeight(96)
        self.neg_prompt_edit.setStyleSheet("""
            QTextEdit {
                border: none;
                background: #ffffff;
                color: #0f172a;
                padding: 10px;
                font-size: 13px;
                line-height: 1.6;
            }
        """)
        saved_neg_height = self.settings.value("param_panel/neg_prompt_height", 0, type=int)
        if saved_neg_height and saved_neg_height > 0:
            self.neg_prompt_edit.setFixedHeight(max(40, min(saved_neg_height, 520)))

        self.prompt_mode_stack = QStackedWidget()
        self.prompt_mode_stack.addWidget(self.prompt_edit)
        self.prompt_mode_stack.addWidget(self.neg_prompt_edit)
        prompt_card_layout.addWidget(self.prompt_mode_stack, 1)

        counter_row = QHBoxLayout()
        counter_row.setContentsMargins(8, 0, 8, 6)
        counter_row.setSpacing(4)
        counter_row.addStretch()
        self.prompt_counter_label = QLabel("0")
        self.prompt_counter_label.setStyleSheet("color: #94a3b8; font-size: 10px;")
        counter_row.addWidget(self.prompt_counter_label)
        prompt_card_layout.addLayout(counter_row)

        self.prompt_tab_idle_style = tab_idle_style
        self.prompt_tab_active_style = tab_active_style
        self.prompt_edit.textChanged.connect(self._update_prompt_counter)
        self.neg_prompt_edit.textChanged.connect(self._update_prompt_counter)
        self._set_prompt_mode("positive")
        self._update_prompt_counter()
        workspace_layout.addWidget(prompt_card)
        

        # --- 2. 其他参数设置 ---
        self.gen_settings_container = QWidget()
        gen_layout = QVBoxLayout(self.gen_settings_container)
        gen_layout.setContentsMargins(0, 0, 0, 0)
        gen_layout.setSpacing(6)

        # ===== Seed行 =====
        seed_row = QHBoxLayout()
        seed_row.setSpacing(6)

        lbl_seed = QLabel("Seed:")
        lbl_seed.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        seed_row.addWidget(lbl_seed)

        self.seed_input = QLineEdit()
        self.seed_input.setText("-1")
        self.seed_input.setPlaceholderText("输入种子数值")
        self.seed_input.setMinimumWidth(110)
        self.seed_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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

        # 初始化时根据“随机”状态控制输入框
        self.seed_input.setEnabled(not saved_random)

        # 保存上一张图片的seed，用于取消随机时恢复
        self.last_image_seed = None

        # ===== 分辨率行 =====
        res_row = QHBoxLayout()
        res_row.setSpacing(6)

        lbl_res = QLabel("分辨率:")
        lbl_res.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        res_row.addWidget(lbl_res)

        self.resolution_combo = QComboBox()
        self.resolution_combo.setMinimumWidth(110)
        self.resolution_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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

        # 分辨率管理按钮
        self.manage_res_btn = QPushButton("⚙️")
        self.manage_res_btn.setFixedSize(24, 24)
        self.manage_res_btn.setToolTip("管理自定义分辨率")
        self.manage_res_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manage_res_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid palette(mid);
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                border-color: palette(highlight);
                color: palette(highlight);
            }
        """)
        self.manage_res_btn.clicked.connect(self._open_resolution_manager)
        res_row.addWidget(self.manage_res_btn)

        res_row.addStretch()

        gen_layout.addLayout(res_row)

        # ===== Steps和CFG合并到一行 =====
        self.steps_cfg_row = QGridLayout()
        self.steps_cfg_row.setContentsMargins(0, 0, 0, 0)
        self.steps_cfg_row.setHorizontalSpacing(6)
        self.steps_cfg_row.setVerticalSpacing(4)

        self.lbl_steps = QLabel("Steps:")
        self.lbl_steps.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")

        self.steps_value = QSpinBox()
        self.steps_value.setRange(1, 150)
        self.steps_value.setValue(20)
        self.steps_value.setMinimumWidth(56)
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
        self.steps_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.lbl_cfg = QLabel("CFG:")
        self.lbl_cfg.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 40px;")

        self.cfg_value = QDoubleSpinBox()
        self.cfg_value.setRange(1.0, 30.0)
        self.cfg_value.setSingleStep(0.5)
        self.cfg_value.setValue(7.5)
        self.cfg_value.setDecimals(1)
        self.cfg_value.setMinimumWidth(56)
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
        self.cfg_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        gen_layout.addLayout(self.steps_cfg_row)
        
        # ===== 采样器和调度器行 =====
        self.sampler_scheduler_row = QGridLayout()
        self.sampler_scheduler_row.setContentsMargins(0, 0, 0, 0)
        self.sampler_scheduler_row.setHorizontalSpacing(6)
        self.sampler_scheduler_row.setVerticalSpacing(4)

        self.lbl_sampler = QLabel("采样器:")
        self.lbl_sampler.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")

        self.sampler_combo = QComboBox()
        self.sampler_combo.setMinimumWidth(90)
        self.sampler_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sampler_combo.setStyleSheet("padding: 3px; font-size: 11px;")
        self.lbl_scheduler = QLabel("调度器:")
        self.lbl_scheduler.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 40px;")

        self.scheduler_combo = QComboBox()
        self.scheduler_combo.setMinimumWidth(84)
        self.scheduler_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.scheduler_combo.setStyleSheet("padding: 3px; font-size: 11px;")
        gen_layout.addLayout(self.sampler_scheduler_row)

        self.model_row_widget = QWidget()
        model_row = QHBoxLayout(self.model_row_widget)
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(6)

        self.lbl_model = QLabel("模型:")
        self.lbl_model.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        model_row.addWidget(self.lbl_model)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(110)
        self.model_combo.setMaximumWidth(16777215) # 限制最大宽度，防止长名字撑爆边栏
        self.model_combo.setStyleSheet("padding: 3px; font-size: 11px;")
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        model_row.addWidget(self.model_combo)
        model_row.addStretch()

        gen_layout.addWidget(self.model_row_widget)
        self.model_row_widget.setVisible(False)

        unet_row = QHBoxLayout()
        unet_row.setSpacing(6)

        self.lbl_unet = QLabel("UNET:")
        self.lbl_unet.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        unet_row.addWidget(self.lbl_unet)
        self.lbl_unet.setText("模型(UNET):")

        self.unet_combo = QComboBox()
        self.unet_combo.setMinimumWidth(110)
        self.unet_combo.setMaximumWidth(16777215)
        self.unet_combo.setStyleSheet("padding: 3px; font-size: 11px;")
        self.unet_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        unet_row.addWidget(self.unet_combo)
        unet_row.addStretch()

        gen_layout.addLayout(unet_row)

        vae_row = QHBoxLayout()
        vae_row.setSpacing(6)

        lbl_vae = QLabel("AE:")
        lbl_vae.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        vae_row.addWidget(lbl_vae)

        self.vae_combo = QComboBox()
        self.vae_combo.setMinimumWidth(110)
        self.vae_combo.setStyleSheet("padding: 3px; font-size: 11px;")
        self.vae_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        vae_row.addWidget(self.vae_combo)
        vae_row.addStretch()

        gen_layout.addLayout(vae_row)

        clip_row = QHBoxLayout()
        clip_row.setSpacing(6)

        lbl_clip = QLabel("CLIP模型:")
        lbl_clip.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px;")
        clip_row.addWidget(lbl_clip)

        self.clip_combo = QComboBox()
        self.clip_combo.setMinimumWidth(110)
        self.clip_combo.setMaximumWidth(16777215)
        self.clip_combo.setStyleSheet("padding: 3px; font-size: 11px;")
        self.clip_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        clip_row.addWidget(self.clip_combo)
        clip_row.addStretch()

        gen_layout.addLayout(clip_row)
        self._refresh_model_selectors()

        # 禁止滚轮切换选项（除了批量输入框）
        for w in [self.resolution_combo, self.steps_value, self.cfg_value, 
                  self.sampler_combo, self.scheduler_combo, self.model_combo,
                  self.unet_combo, self.vae_combo, self.clip_combo]:
            w.wheelEvent = lambda e: e.ignore()

        self.workspace_controls_container = QWidget()
        controls_layout = QVBoxLayout(self.workspace_controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        controls_layout.addWidget(self.gen_settings_container)

        # ===== LoRA 对比测试区域（可折叠） =====
        self.compare_section_container = QFrame()
        self.compare_section_container.setObjectName("CompareSection")
        compare_layout = QVBoxLayout(self.compare_section_container)
        compare_layout.setContentsMargins(8, 8, 8, 8)
        compare_layout.setSpacing(6)

        compare_header_row = QHBoxLayout()
        compare_header_row.setContentsMargins(0, 0, 0, 0)
        compare_header_row.setSpacing(6)
        self.compare_toggle_btn = QToolButton()
        self.compare_toggle_btn.setCheckable(True)
        self.compare_toggle_btn.setChecked(True)
        self.compare_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.compare_toggle_btn.setFixedSize(18, 18)
        compare_header_row.addWidget(self.compare_toggle_btn)

        compare_title = QLabel("LoRA 对比测试")
        compare_title.setStyleSheet("font-weight: bold; color: palette(text);")
        compare_header_row.addWidget(compare_title)
        compare_header_row.addStretch()
        compare_layout.addLayout(compare_header_row)

        self.compare_content = QWidget()
        compare_content_layout = QVBoxLayout(self.compare_content)
        compare_content_layout.setContentsMargins(0, 0, 0, 0)
        compare_content_layout.setSpacing(6)

        compare_weight_row = QHBoxLayout()
        compare_weight_row.setSpacing(6)
        compare_weight_row.addWidget(QLabel("权重:"))
        self.compare_weights_input = QLineEdit()
        self.compare_weights_input.setPlaceholderText("例如: 0.7,0.75,0.8 或 0.7:0.9:0.05")
        self.compare_weights_input.setMinimumWidth(110)
        self.compare_weights_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        compare_weight_row.addWidget(self.compare_weights_input, 1)
        compare_content_layout.addLayout(compare_weight_row)

        self.compare_mode_row = QGridLayout()
        self.compare_mode_row.setContentsMargins(0, 0, 0, 0)
        self.compare_mode_row.setHorizontalSpacing(6)
        self.compare_mode_row.setVerticalSpacing(4)
        self.compare_lbl_combo = QLabel("组合:")
        self.compare_combo_mode = QComboBox()
        self.compare_combo_mode.addItem("笛卡尔积", "cartesian")
        self.compare_combo_mode.addItem("按位配对", "pairwise")
        self.compare_combo_mode.setMinimumWidth(96)
        self.compare_combo_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.compare_lbl_seed = QLabel("种子:")
        self.compare_seed_mode_combo = QComboBox()
        self.compare_seed_mode_combo.addItem("固定同种子", "fixed")
        self.compare_seed_mode_combo.addItem("每图随机", "random")
        self.compare_seed_mode_combo.setMinimumWidth(96)
        self.compare_seed_mode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.compare_include_baseline = QCheckBox("包含基线图(无LoRA)")
        compare_content_layout.addLayout(self.compare_mode_row)

        self.compare_btn_row = QGridLayout()
        self.compare_btn_row.setContentsMargins(0, 0, 0, 0)
        self.compare_btn_row.setHorizontalSpacing(8)
        self.compare_btn_row.setVerticalSpacing(4)
        self.btn_compare_generate = QPushButton("开始对比生成")
        self.btn_compare_generate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_compare_generate.clicked.connect(self._on_compare_generate_click)
        self.btn_compare_generate.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.btn_open_last_compare = QPushButton("打开最近对比")
        self.btn_open_last_compare.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_last_compare.clicked.connect(self._open_last_compare_from_panel)
        self.btn_open_last_compare.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        compare_content_layout.addLayout(self.compare_btn_row)

        compare_layout.addWidget(self.compare_content)
        controls_layout.addWidget(self.compare_section_container)

        saved_compare_expanded = self.settings.value("param_panel/compare_section_expanded", True, type=bool)
        self.compare_toggle_btn.toggled.connect(self._on_compare_section_toggled)
        self._set_compare_section_expanded(saved_compare_expanded)

        # ===== LoRA管理区域 =====
        self.lora_section_container = QWidget()
        lora_section_layout = QVBoxLayout(self.lora_section_container)
        lora_section_layout.setContentsMargins(0, 0, 0, 0)
        lora_section_layout.setSpacing(6)

        lora_header_row = QHBoxLayout()
        lora_header_row.setSpacing(6)

        lbl_loras = QLabel("LoRAs:")
        lbl_loras.setStyleSheet("color: palette(mid); font-size: 10px; min-width: 60px; font-weight: bold;")
        lora_header_row.addWidget(lbl_loras)

        add_lora_btn = QPushButton("+ 添加")
        add_lora_btn.setMinimumWidth(60)
        add_lora_btn.setFixedHeight(22)
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

        lora_section_layout.addLayout(lora_header_row)

        # 直接使用内容容器，不再嵌套 QScrollArea，避免滚动冲突
        self.lora_container = QWidget()
        self.lora_layout = QVBoxLayout(self.lora_container)
        self.lora_layout.setContentsMargins(0, 0, 0, 0)
        self.lora_layout.setSpacing(3)
        self.lora_layout.addStretch()

        lora_section_layout.addWidget(self.lora_container)

        self.current_loras = {}
        self.current_lora_meta = {}
        
        workspace_layout.addWidget(self.workspace_controls_container)
        workspace_layout.addWidget(self.lora_section_container)
        workspace_layout.addStretch()

        # --- 3. 底部生成按钮 (从上方移动到这里) ---
        self.gen_btn_container = QWidget()
        self.gen_btn_layout = QGridLayout(self.gen_btn_container)
        self.gen_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.gen_btn_layout.setHorizontalSpacing(8)
        self.gen_btn_layout.setVerticalSpacing(4)

        # [NEW] 批量生成计数器 (优化版 - 简洁风格)
        self.batch_count_spin = QSpinBox()
        self.batch_count_spin.setRange(1, 100)
        self.batch_count_spin.setValue(1)
        self.batch_count_spin.setMinimumWidth(56)
        self.batch_count_spin.setMaximumWidth(88)
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
        self.lbl_batch = QLabel("批量:")
        self.lbl_batch.setStyleSheet("color: palette(text); font-weight: bold;")
        
        # 添加 "张" 单位标签
        self.lbl_batch_unit = QLabel("张")
        self.lbl_batch_unit.setStyleSheet("color: palette(mid);")

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
        self.btn_remote_gen.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        outer_layout.addWidget(self.workspace_scroll, 1)
        outer_layout.addWidget(self.gen_btn_container)
        
        # 初始化持久化逻辑
        self._init_workspace_persistence()
        self._toggle_workspace_controls(self.workspace_toggle_btn.isChecked())
        QTimer.singleShot(0, self._apply_responsive_layout)
        return gen_settings_outer

    def _toggle_workspace_controls(self, expanded):
        if hasattr(self, "workspace_controls_container"):
            self.workspace_controls_container.setVisible(expanded)
        if hasattr(self, "workspace_toggle_btn"):
            self.workspace_toggle_btn.setText("收起" if expanded else "展开")
        self.settings.setValue("gen_workspace_controls_expanded", expanded)
        if expanded:
            QTimer.singleShot(0, self._apply_responsive_layout)

    def _set_compare_section_expanded(self, expanded: bool):
        if hasattr(self, "compare_content"):
            self.compare_content.setVisible(bool(expanded))
        if hasattr(self, "compare_toggle_btn"):
            self.compare_toggle_btn.blockSignals(True)
            self.compare_toggle_btn.setChecked(bool(expanded))
            self.compare_toggle_btn.setText("▼" if expanded else "▶")
            self.compare_toggle_btn.blockSignals(False)
        self.settings.setValue("param_panel/compare_section_expanded", bool(expanded))
        if expanded:
            QTimer.singleShot(0, self._apply_responsive_layout)

    def _on_compare_section_toggled(self, checked: bool):
        self._set_compare_section_expanded(bool(checked))

    def _set_prompt_mode(self, mode: str, tab_idle_style: str | None = None, tab_active_style: str | None = None):
        mode = "negative" if str(mode) == "negative" else "positive"
        idle = tab_idle_style or getattr(self, "prompt_tab_idle_style", "")
        active = tab_active_style or getattr(self, "prompt_tab_active_style", "")

        if not hasattr(self, "prompt_mode_stack"):
            return
        self.prompt_mode_stack.setCurrentIndex(0 if mode == "positive" else 1)
        if hasattr(self, "prompt_action_stack"):
            self.prompt_action_stack.setCurrentIndex(0 if mode == "positive" else 1)

        if hasattr(self, "prompt_tab_positive"):
            self.prompt_tab_positive.setChecked(mode == "positive")
            self.prompt_tab_positive.setStyleSheet(active if mode == "positive" else idle)
        if hasattr(self, "prompt_tab_negative"):
            self.prompt_tab_negative.setChecked(mode == "negative")
            self.prompt_tab_negative.setStyleSheet(active if mode == "negative" else idle)

        target = self.prompt_edit if mode == "positive" else self.neg_prompt_edit
        try:
            target.setFocus()
        except Exception:
            pass
        self._update_prompt_counter()

    def _update_prompt_counter(self):
        if not hasattr(self, "prompt_counter_label"):
            return
        current_mode_negative = (
            hasattr(self, "prompt_mode_stack") and self.prompt_mode_stack.currentIndex() == 1
        )
        text = self.neg_prompt_edit.toPlainText() if current_mode_negative else self.prompt_edit.toPlainText()
        self.prompt_counter_label.setText(f"{len((text or '').strip())}/75")

    def _reset_layout_items(self, layout):
        while layout.count():
            layout.takeAt(0)

    def _layout_steps_cfg_row(self, compact: bool):
        if not hasattr(self, "steps_cfg_row"):
            return
        self._reset_layout_items(self.steps_cfg_row)
        for i in range(5):
            self.steps_cfg_row.setColumnStretch(i, 0)
        if compact:
            self.steps_cfg_row.addWidget(self.lbl_steps, 0, 0)
            self.steps_cfg_row.addWidget(self.steps_value, 0, 1)
            self.steps_cfg_row.addWidget(self.lbl_cfg, 1, 0)
            self.steps_cfg_row.addWidget(self.cfg_value, 1, 1)
            self.steps_cfg_row.setColumnStretch(2, 1)
        else:
            self.steps_cfg_row.addWidget(self.lbl_steps, 0, 0)
            self.steps_cfg_row.addWidget(self.steps_value, 0, 1)
            self.steps_cfg_row.addWidget(self.lbl_cfg, 0, 2)
            self.steps_cfg_row.addWidget(self.cfg_value, 0, 3)
            self.steps_cfg_row.setColumnStretch(4, 1)

    def _layout_sampler_scheduler_row(self, compact: bool):
        if not hasattr(self, "sampler_scheduler_row"):
            return
        self._reset_layout_items(self.sampler_scheduler_row)
        for i in range(5):
            self.sampler_scheduler_row.setColumnStretch(i, 0)
        if compact:
            self.sampler_scheduler_row.addWidget(self.lbl_sampler, 0, 0)
            self.sampler_scheduler_row.addWidget(self.sampler_combo, 0, 1)
            self.sampler_scheduler_row.addWidget(self.lbl_scheduler, 1, 0)
            self.sampler_scheduler_row.addWidget(self.scheduler_combo, 1, 1)
            self.sampler_scheduler_row.setColumnStretch(2, 1)
        else:
            self.sampler_scheduler_row.addWidget(self.lbl_sampler, 0, 0)
            self.sampler_scheduler_row.addWidget(self.sampler_combo, 0, 1)
            self.sampler_scheduler_row.addWidget(self.lbl_scheduler, 0, 2)
            self.sampler_scheduler_row.addWidget(self.scheduler_combo, 0, 3)
            self.sampler_scheduler_row.setColumnStretch(4, 1)

    def _layout_neg_prompt_actions(self, compact: bool):
        if not hasattr(self, "neg_actions_layout"):
            return
        if not isinstance(self.neg_actions_layout, QGridLayout):
            return
        self._reset_layout_items(self.neg_actions_layout)
        for i in range(3):
            self.neg_actions_layout.setColumnStretch(i, 0)
        if compact:
            self.neg_actions_layout.addWidget(self.btn_neg_history, 0, 0)
            self.neg_actions_layout.addWidget(self.btn_neg_ai_optimize, 1, 0)
            self.neg_actions_layout.setColumnStretch(1, 1)
        else:
            self.neg_actions_layout.addWidget(self.btn_neg_history, 0, 0)
            self.neg_actions_layout.addWidget(self.btn_neg_ai_optimize, 0, 1)
            self.neg_actions_layout.setColumnStretch(2, 1)

    def _layout_compare_section(self, compact: bool):
        if not hasattr(self, "compare_mode_row") or not hasattr(self, "compare_btn_row"):
            return
        self._reset_layout_items(self.compare_mode_row)
        self._reset_layout_items(self.compare_btn_row)
        for i in range(6):
            self.compare_mode_row.setColumnStretch(i, 0)
        for i in range(3):
            self.compare_btn_row.setColumnStretch(i, 0)
        if compact:
            self.compare_mode_row.addWidget(self.compare_lbl_combo, 0, 0)
            self.compare_mode_row.addWidget(self.compare_combo_mode, 0, 1)
            self.compare_mode_row.addWidget(self.compare_lbl_seed, 1, 0)
            self.compare_mode_row.addWidget(self.compare_seed_mode_combo, 1, 1)
            self.compare_mode_row.addWidget(self.compare_include_baseline, 2, 0, 1, 2)
            self.compare_mode_row.setColumnStretch(2, 1)

            self.compare_btn_row.addWidget(self.btn_compare_generate, 0, 0)
            self.compare_btn_row.addWidget(self.btn_open_last_compare, 1, 0)
            self.compare_btn_row.setColumnStretch(1, 1)
        else:
            self.compare_mode_row.addWidget(self.compare_lbl_combo, 0, 0)
            self.compare_mode_row.addWidget(self.compare_combo_mode, 0, 1)
            self.compare_mode_row.addWidget(self.compare_lbl_seed, 0, 2)
            self.compare_mode_row.addWidget(self.compare_seed_mode_combo, 0, 3)
            self.compare_mode_row.addWidget(self.compare_include_baseline, 0, 4)
            self.compare_mode_row.setColumnStretch(5, 1)

            self.compare_btn_row.addWidget(self.btn_compare_generate, 0, 0)
            self.compare_btn_row.addWidget(self.btn_open_last_compare, 0, 1)
            self.compare_btn_row.setColumnStretch(2, 1)

    def _layout_generate_buttons(self, compact: bool):
        if not hasattr(self, "gen_btn_layout"):
            return
        self._reset_layout_items(self.gen_btn_layout)
        for i in range(6):
            self.gen_btn_layout.setColumnStretch(i, 0)
        available_width = 0
        if hasattr(self, "workspace_scroll"):
            available_width = max(0, int(self.workspace_scroll.viewport().width()) - 20)
        spacing = self.gen_btn_layout.horizontalSpacing()
        if spacing < 0:
            spacing = 8
        needed_width = (
            self.lbl_batch.sizeHint().width()
            + self.batch_count_spin.sizeHint().width()
            + self.lbl_batch_unit.sizeHint().width()
            + max(self.btn_remote_gen.sizeHint().width(), self.btn_remote_gen.minimumSizeHint().width())
            + spacing * 3
            + 20
        )
        force_single_row = available_width >= needed_width

        if compact and not force_single_row:
            self.gen_btn_layout.addWidget(self.lbl_batch, 0, 0)
            self.gen_btn_layout.addWidget(self.batch_count_spin, 0, 1)
            self.gen_btn_layout.addWidget(self.lbl_batch_unit, 0, 2)
            self.gen_btn_layout.addWidget(self.btn_remote_gen, 1, 0, 1, 3)
            self.gen_btn_layout.setColumnStretch(3, 1)
        else:
            self.gen_btn_layout.setColumnStretch(0, 1)
            self.gen_btn_layout.addWidget(self.lbl_batch, 0, 1)
            self.gen_btn_layout.addWidget(self.batch_count_spin, 0, 2)
            self.gen_btn_layout.addWidget(self.lbl_batch_unit, 0, 3)
            self.gen_btn_layout.addWidget(self.btn_remote_gen, 0, 4)
            self.gen_btn_layout.setColumnStretch(5, 1)

    def _apply_responsive_layout(self):
        if not hasattr(self, "workspace_scroll"):
            return
        current_width = self.workspace_scroll.viewport().width()
        compact = current_width <= self._compact_breakpoint
        mode = "compact" if compact else "normal"
        self._layout_mode = mode
        self._layout_steps_cfg_row(compact)
        self._layout_sampler_scheduler_row(compact)
        self._layout_neg_prompt_actions(compact)
        self._layout_compare_section(compact)
        self._layout_generate_buttons(compact)
    
    
    def _normalize_lora_profile_meta(self, profile):
        data = {"note": "", "prompt": "", "auto_use_prompt": True}
        if isinstance(profile, dict):
            data["note"] = str(profile.get("note", "") or "").strip()
            data["prompt"] = str(profile.get("prompt", "") or "").strip()
            data["auto_use_prompt"] = bool(profile.get("auto_use_prompt", True))
        return data

    def _add_lora_item(self, name: str = "", weight: float = 1.0, lora_meta: dict | None = None):
        """添加一个LoRA项到列表（弹出窗口模式）"""
        # 限制最多5个LoRA
        if len(self.current_loras) >= 5:
            print("[UI] 已达到LoRA数量上限（5个）")
            return
        
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(4, 2, 4, 2)
        item_layout.setSpacing(6)
        
        # LoRA选择器 (弹出窗口版)
        lora_selector = LoraSelectorWidget()
        lora_selector.setMinimumWidth(110)
        lora_selector.setMaximumWidth(16777215)
        lora_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lora_selector.set_data_source(self._get_all_loras)
        
        if name:
            lora_selector.set_current_lora(name)
        lora_selector.setProperty("selected_lora_profile", self._normalize_lora_profile_meta(lora_meta))
        
        # 当选择改变时更新数据
        lora_selector.selection_changed.connect(
            lambda text: self._on_lora_selection_changed(item_widget, text, lora_selector)
        )
        
        item_layout.addWidget(lora_selector)
        
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
        weight_spin.setMinimumWidth(58)
        weight_spin.setMaximumWidth(86)
        weight_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        weight_spin.setStyleSheet("""
            QDoubleSpinBox {
                padding: 2px;
                font-size: 11px;
                border: 1px solid palette(mid);
                border-radius: 2px;
            }
        """)
        # 保存引用到selector的userData
        lora_selector.setProperty("weight_spin", weight_spin)
        weight_spin.valueChanged.connect(
            lambda v: self._update_lora_weight_from_combo(lora_selector, round(v, 2))
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
        del_btn.clicked.connect(lambda: self._remove_lora_item_widget(item_widget, lora_selector))
        item_layout.addWidget(del_btn)
        
        # 插入到stretch之前
        count = self.lora_layout.count()
        self.lora_layout.insertWidget(count - 1, item_widget)
        
        # 如果指定了名称，添加到数据并设置属性
        if name and name != "选择LoRA...":
            self.current_loras[name] = weight
            self.current_lora_meta[name] = self._normalize_lora_profile_meta(lora_meta)
            lora_selector.setProperty("selected_lora", name)  # 设置属性，防止重复检测

    def _get_all_loras(self):
        main_window = self.window()
        all_loras = []
        comfy_loras = self._get_comfyui_loras()
        if comfy_loras is not None and len(comfy_loras) >= 0:
            for name in comfy_loras:
                if name and name not in all_loras:
                    all_loras.append(name)
            if self.settings.value("comfy_root", "", type=str):
                return all_loras
        for name in comfy_loras:
            if name and name not in all_loras:
                all_loras.append(name)
        comfy_basenames = set()
        for name in comfy_loras:
            base = os.path.basename(name).lower()
            comfy_basenames.add(base)
            comfy_basenames.add(os.path.splitext(base)[0])
        if hasattr(main_window, 'db_manager'):
            all_loras_raw = main_window.db_manager.get_unique_loras()
            for item in all_loras_raw:
                if isinstance(item, tuple):
                    name = item[0] if item else ""
                else:
                    name = str(item)
                if name:
                    base = os.path.basename(name).lower()
                    base_no = os.path.splitext(base)[0]
                    if base in comfy_basenames or base_no in comfy_basenames:
                        continue
                if name and name not in all_loras:
                    all_loras.append(name)
        return all_loras

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

    def _get_comfyui_loras(self):
        base = self.settings.value("comfy_root", "", type=str).strip()
        if not base:
            self._last_comfyui_lora_status = "未设置 ComfyUI 目录"
            return []
        models_root = self._resolve_comfyui_models_root()
        lora_dir = os.path.join(models_root, "loras") if models_root else ""
        if not lora_dir or not os.path.isdir(lora_dir):
            target_path = lora_dir if lora_dir else os.path.join(base, "models", "loras")
            self._last_comfyui_lora_status = f"未找到目录: {target_path}"
            return []
        results = []
        exts = (".safetensors", ".ckpt", ".pt", ".sft")
        for root, _, files in os.walk(lora_dir):
            for fname in files:
                if fname.lower().endswith(exts):
                    full_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(full_path, lora_dir).replace("\\", "/")
                    if rel_path not in results:
                        results.append(rel_path)
        self.available_loras = results
        if results:
            self._last_comfyui_lora_status = f"已读取 {len(results)} 个 LoRA"
        else:
            self._last_comfyui_lora_status = "LoRA 目录为空"
        return results

    def _get_comfyui_models(self, subdir):
        base = self.settings.value("comfy_root", "", type=str).strip()
        if not base:
            if not hasattr(self, "_last_comfyui_model_status"):
                self._last_comfyui_model_status = {}
            self._last_comfyui_model_status[subdir] = "未设置 ComfyUI 目录"
            return []
        models_root = self._resolve_comfyui_models_root()
        if not models_root:
            if not hasattr(self, "_last_comfyui_model_status"):
                self._last_comfyui_model_status = {}
            self._last_comfyui_model_status[subdir] = "未设置 ComfyUI 目录"
            return []
        alias_map = {
            "checkpoints": ["checkpoints", "checkpoint", "diffusion_models", "stable_diffusion", "stable-diffusion"],
            "unet": ["unet", "unets", "diffusion_models"],
            "vae": ["vae", "vaes", "vae_approx"],
            "clip": ["clip", "text_encoders", "clip_vision", "llm"]
        }
        dir_candidates = alias_map.get(subdir, [subdir])
        results = []
        exts = (".safetensors", ".ckpt", ".pt", ".sft", ".pth", ".bin", ".gguf")
        searched_dirs = []
        existing_dirs = []
        for name in dir_candidates:
            target_dir = os.path.join(models_root, name)
            searched_dirs.append(target_dir)
            if not os.path.isdir(target_dir):
                continue
            existing_dirs.append(target_dir)
            for root, _, files in os.walk(target_dir):
                for fname in files:
                    if fname.lower().endswith(exts):
                        full_path = os.path.join(root, fname)
                        rel_path = os.path.relpath(full_path, target_dir).replace("\\", "/")
                        if rel_path not in results:
                            results.append(rel_path)
        if not hasattr(self, "_last_comfyui_model_status"):
            self._last_comfyui_model_status = {}
        if results:
            self._last_comfyui_model_status[subdir] = f"已读取 {len(results)} 个模型"
        else:
            if not existing_dirs:
                self._last_comfyui_model_status[subdir] = f"未找到目录: {', '.join(searched_dirs)}"
            else:
                self._last_comfyui_model_status[subdir] = f"目录为空: {existing_dirs[0]}"
        return results

    def _refresh_comfyui_assets(self):
        self.available_loras = self._get_comfyui_loras()
        self.available_checkpoints = self._get_comfyui_models("checkpoints")
        self.available_unets = self._get_comfyui_models("unet")
        self.available_vaes = self._get_comfyui_models("vae")
        self.available_clips = self._get_comfyui_models("clip")
        self._refresh_model_selectors()
        status_map = getattr(self, "_last_comfyui_model_status", {})
        if status_map:
            if not hasattr(self, "_last_comfyui_model_popup"):
                self._last_comfyui_model_popup = {}
            for subdir, status in status_map.items():
                if status.startswith("未设置 ComfyUI 目录") or status.startswith("未找到目录"):
                    last_popup = self._last_comfyui_model_popup.get(subdir, "")
                    if last_popup != status:
                        QMessageBox.warning(self, "ComfyUI 目录无效", status)
                        self._last_comfyui_model_popup[subdir] = status

    def _refresh_model_selectors(self):
        if hasattr(self, "model_combo"):
            self._populate_model_combo(self.model_combo, getattr(self, "available_checkpoints", []), "gen_model")
        if hasattr(self, "unet_combo"):
            self._populate_model_combo(self.unet_combo, getattr(self, "available_unets", []), "gen_unet")
        if hasattr(self, "vae_combo"):
            self._populate_model_combo(self.vae_combo, getattr(self, "available_vaes", []), "gen_vae")
        if hasattr(self, "clip_combo"):
            self._populate_model_combo(self.clip_combo, getattr(self, "available_clips", []), "gen_clip")
        if hasattr(self, "model_row_widget") and hasattr(self, "lbl_unet") and hasattr(self, "lbl_model"):
            self.model_row_widget.setVisible(False)
            self.lbl_unet.setText("模型(UNET):")

    def refresh_lora_options(self):
        # 记录外层滚动条位置
        v_bar = self.workspace_scroll.verticalScrollBar()
        old_pos = v_bar.value()
        
        all_loras = self._get_all_loras()
        status = getattr(self, "_last_comfyui_lora_status", "")
        
    def refresh_lora_options(self):
        """刷新LoRA选项（不再更新Dropdown，仅用于保留接口或特殊逻辑）"""
        pass # LoraSelectorWidget 自动处理数据源，这里不再需要手动填充
    
    def _on_lora_selection_changed(self, widget, text, selector):
        """当LoRA选择改变时"""
        if not text:
            # 从数据中移除（如果之前有选择）
            old_data = selector.property("selected_lora")
            if old_data and old_data in self.current_loras:
                del self.current_loras[old_data]
            if old_data and old_data in self.current_lora_meta:
                del self.current_lora_meta[old_data]
            selector.setProperty("selected_lora", None)
            self._save_loras()
            return
        
        old_name = selector.property("selected_lora")

        # 检查是否重复（允许“同一行重新选择同一个LoRA”，用于更新备注/提示词等元数据）
        if text in self.current_loras and text != old_name:
            selector.set_current_lora(old_name if old_name else "")
            return
        
        # 更新数据
        if old_name and old_name in self.current_loras:
            del self.current_loras[old_name]
        if old_name and old_name in self.current_lora_meta:
            del self.current_lora_meta[old_name]

        weight_spin = selector.property("weight_spin")
        profile_raw = selector.property("selected_lora_profile")
        profile_meta = self._normalize_lora_profile_meta(profile_raw)
        recommended_weight = weight_spin.value() if weight_spin else 1.0
        if isinstance(profile_raw, dict) and "recommended_weight" in profile_raw:
            try:
                recommended_weight = float(profile_raw.get("recommended_weight", recommended_weight))
            except Exception:
                pass
        recommended_weight = max(-2.0, min(2.0, float(recommended_weight)))
        if weight_spin:
            weight_spin.blockSignals(True)
            weight_spin.setValue(round(recommended_weight, 2))
            weight_spin.blockSignals(False)
        weight = round(recommended_weight, 2)
        self.current_loras[text] = weight
        self.current_lora_meta[text] = profile_meta
        selector.setProperty("selected_lora", text)
        selector.setProperty(
            "selected_lora_profile",
            {
                "note": profile_meta["note"],
                "prompt": profile_meta["prompt"],
                "auto_use_prompt": profile_meta["auto_use_prompt"],
            },
        )
        self._save_loras()
        # print(f"[UI] 选择LoRA: {text} (权重: {weight})")
    
    # [Removed redundant _log method that was overwritten]

    def _update_lora_weight_from_combo(self, selector, weight):
        """从Selector更新LoRA权重"""
        lora_name = selector.property("selected_lora")
        if lora_name and lora_name in self.current_loras:
            self.current_loras[lora_name] = weight
            self._save_loras()
            # print(f"[UI] 更新LoRA权重: {lora_name} -> {weight}")
    
    def _remove_lora_item_widget(self, widget, selector):
        """删除LoRA项"""
        lora_name = selector.property("selected_lora")
        if lora_name and lora_name in self.current_loras:
            del self.current_loras[lora_name]
        if lora_name and lora_name in self.current_lora_meta:
            del self.current_lora_meta[lora_name]
            # print(f"[UI] 删除LoRA: {lora_name}")
        
        self.lora_layout.removeWidget(widget)
        widget.deleteLater()
        self._save_loras()
    
    def _remove_lora_item(self, name: str, widget: QWidget):
        """删除一个LoRA项（兼容旧方法）"""
        if name in self.current_loras:
            del self.current_loras[name]
        if name in self.current_lora_meta:
            del self.current_lora_meta[name]
        
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
        self.current_lora_meta.clear()
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

    def _on_clipboard_import_click(self):
        if self._img_prompt_processing:
            self._cancel_image_prompt_task()
            return
        if self._ai_is_processing:
            self._temp_notify("当前已有AI任务在执行")
            return
        
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        
        # 1. 优先检查是否有本地图片文件链接（避免拿到缩略图）
        if mime and mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path and self._is_image_file(path):
                    image_b64 = self._image_file_to_base64(path)
                    if image_b64:
                        self._temp_notify(f"📁 正在识图: {os.path.basename(path)}")
                        self._run_image_to_prompt(image_b64, loading_button=self.sender())
                        return

        # 2. 再尝试直接读取剪贴板图像数据
        image = clipboard.image()
        if image and not image.isNull():
            image_b64 = self._qimage_to_base64(image)
            if image_b64:
                self._temp_notify("🎨 正在从剪贴板读取图片进行识图...")
                self._run_image_to_prompt(image_b64, loading_button=self.sender())
                return
                        
        # 3. 如果不是图片，尝试导入文本
        if mime and mime.hasText():
            text = mime.text().strip()
            if text:
                # 确定要粘贴到的目标编辑器
                target_edit = self.prompt_edit
                focus_widget = QApplication.focusWidget()
                
                # 如果当前焦点在反向提示词框，则粘贴到那里
                if focus_widget == self.neg_prompt_edit:
                    target_edit = self.neg_prompt_edit
                
                # 执行覆盖粘贴
                target_edit.setPlainText(text)
                
                # 移动光标到末尾并滚动
                cursor = target_edit.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                target_edit.setTextCursor(cursor)
                target_edit.ensureCursorVisible()
                
                self._temp_notify("📋 剪贴板文本已导入（已覆盖旧内容）")
                return
        
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "剪贴板无有效内容", "未检测到图片或文本内容")

    def _on_file_import_click(self):
        if self._img_prompt_processing:
            self._cancel_image_prompt_task()
            return
        if self._ai_is_processing:
            self._temp_notify("当前已有AI任务在执行")
            return
        
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        file_path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片文件 (*.png *.jpg *.jpeg *.webp)")
        if not file_path:
            return
        
        image_b64 = self._image_file_to_base64(file_path)
        if not image_b64:
            QMessageBox.warning(self, "图片读取失败", "未能读取或解析该图片")
            return
        self._run_image_to_prompt(image_b64, loading_button=self.sender())

    def _run_image_to_prompt(self, image_b64: str, loading_button=None):
        if self._ai_is_processing or self._img_prompt_processing:
            self._temp_notify("当前已有AI任务在执行")
            return
        self._img_prompt_processing = True
        self._img_original_prompt = self.prompt_edit.toPlainText().strip()
        self._img_prompt_loading_button = loading_button if isinstance(loading_button, QPushButton) else None
        if self._img_prompt_loading_button is not None:
            self._img_prompt_loading_button.setText("取消")
            self._img_prompt_loading_button.setEnabled(True)
        else:
            self.btn_file_import.setText("取消")
            self.btn_file_import.setEnabled(True)
            if hasattr(self, "btn_neg_file_import"):
                self.btn_neg_file_import.setText("取消")
                self.btn_neg_file_import.setEnabled(True)
        self.btn_clipboard_import.setEnabled(self.btn_clipboard_import is self._img_prompt_loading_button)
        self.btn_file_import.setEnabled(self.btn_file_import is self._img_prompt_loading_button)
        if hasattr(self, "btn_neg_clipboard_import"):
            self.btn_neg_clipboard_import.setEnabled(self.btn_neg_clipboard_import is self._img_prompt_loading_button)
        if hasattr(self, "btn_neg_file_import"):
            self.btn_neg_file_import.setEnabled(self.btn_neg_file_import is self._img_prompt_loading_button)
        self.btn_ai_optimize.setEnabled(False)
        self.btn_neg_ai_optimize.setEnabled(False)
        main_win = self.window()
        if hasattr(main_win, 'statusBar'):
            main_win.statusBar().showMessage("⏳ 识图中...可点击当前按钮取消")
        
        original_prompt = self._img_original_prompt
        self.current_img_worker = ImagePromptWorker(
            image_b64,
            lora_guidance=self._build_lora_guidance_payload(),
        )
        self._img_stream_started = False
        self.current_img_worker.stream_update.connect(self._on_img_stream_update)
        self.current_img_worker.finished.connect(lambda s, r: self._on_image_prompt_finished(s, r, original_prompt))
        self.current_img_worker.start()

    def _reset_image_prompt_ui(self):
        self._img_prompt_loading_button = None
        self.btn_clipboard_import.setEnabled(True)
        self.btn_file_import.setEnabled(True)
        self.btn_clipboard_import.setText("贴")
        self.btn_file_import.setText("文")
        if hasattr(self, "btn_neg_clipboard_import"):
            self.btn_neg_clipboard_import.setEnabled(True)
            self.btn_neg_clipboard_import.setText("贴")
        if hasattr(self, "btn_neg_file_import"):
            self.btn_neg_file_import.setEnabled(True)
            self.btn_neg_file_import.setText("文")
        self.btn_ai_optimize.setEnabled(True)
        self.btn_neg_ai_optimize.setEnabled(True)

    def _cancel_image_prompt_task(self):
        if not self._img_prompt_processing:
            return
        if self.current_img_worker:
            self.current_img_worker.is_cancelled = True
        self._img_prompt_processing = False
        self.current_img_worker = None
        if self._img_stream_started and self._img_original_prompt is not None:
            self.prompt_edit.setPlainText(self._img_original_prompt)
        self._img_stream_started = False
        self._img_original_prompt = None
        self._reset_image_prompt_ui()
        self._temp_notify("🚫 已取消识图")

    def _on_img_stream_update(self, chunk):
        if not self._img_prompt_processing:
            return
        if not hasattr(self, "_img_stream_started") or not self._img_stream_started:
            self.prompt_edit.clear()
            self._img_stream_started = True
        self.prompt_edit.insertPlainText(chunk)
        cursor = self.prompt_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.prompt_edit.setTextCursor(cursor)

    def _on_image_prompt_finished(self, success, result, original_prompt):
        if not self._img_prompt_processing:
            return
        self._img_prompt_processing = False
        self._reset_image_prompt_ui()
        self.current_img_worker = None
        self._img_original_prompt = None
        
        if success:
            # self.ai_status_label.setText("✅ 识图完成")
            # QTimer.singleShot(3000, lambda: self.ai_status_label.setText(""))
            self._temp_notify("✅ 识图完成")
            merged_prompt, _ = self._merge_prompt_with_lora_extras(result)
            self.prompt_edit.setPlainText(merged_prompt)
            self.history_manager.add_record("positive", original_prompt, merged_prompt)
        else:
            # self.ai_status_label.setText("❌ 识图失败")
            # QTimer.singleShot(3000, lambda: self.ai_status_label.setText(""))
            self._temp_notify("❌ 识图失败")
            if hasattr(self, "_img_stream_started") and self._img_stream_started:
                self.prompt_edit.setPlainText(original_prompt)
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "图生文失败", result)

    def _is_image_file(self, path: str) -> bool:
        ext = os.path.splitext(path)[1].lower()
        return ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]

    def _image_file_to_base64(self, path: str) -> str:
        image = QImage(path)
        if image.isNull():
            return ""
        return self._qimage_to_base64(image)

    def _qimage_to_base64(self, image: QImage) -> str:
        if image is None or image.isNull():
            return ""
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return base64.b64encode(bytes(byte_array)).decode("utf-8")

    def _show_history_dialog(self, prompt_type):
        if prompt_type not in self.history_dialogs:
            self.history_dialogs[prompt_type] = self._build_history_dialog(prompt_type)
        dialog = self.history_dialogs[prompt_type]
        self._refresh_history_dialog(dialog, prompt_type)
        if dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
        else:
            dialog.show()

    def _build_history_dialog(self, prompt_type):
        dialog = QDialog(self)
        title = "正向提示词历史记录" if prompt_type == "positive" else "反向提示词历史记录"
        dialog.setWindowTitle(title)
        dialog.resize(720, 480)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        
        layout = QVBoxLayout(dialog)
        
        header_row = QHBoxLayout()
        header_label = QLabel(title)
        header_label.setStyleSheet("font-weight: bold; font-size: 12px; color: palette(text);")
        header_row.addWidget(header_label)
        header_row.addStretch()
        count_label = QLabel("")
        count_label.setStyleSheet("color: palette(mid); font-size: 10px;")
        header_row.addWidget(count_label)
        layout.addLayout(header_row)
        
        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setChildrenCollapsible(False)
        # 左侧列表面板 (增加搜索框)
        left_widget = QWidget()
        left_widget.setMinimumWidth(380) # 加宽以确保您的原始设计（右侧按钮）能完整显示
        left_col = QVBoxLayout(left_widget)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_label = QLabel("系列")
        left_label.setStyleSheet("color: palette(mid); font-size: 10px;")
        left_col.addWidget(left_label)
        session_list = QListWidget()
        session_list.setMinimumWidth(260)
        left_col.addWidget(session_list)
        body_splitter.addWidget(left_widget)
        
        right_widget = QWidget()
        right_col = QVBoxLayout(right_widget)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_label = QLabel("版本")
        right_label.setStyleSheet("color: palette(mid); font-size: 10px;")
        right_col.addWidget(right_label)
        version_list = QListWidget()
        right_col.addWidget(version_list)
        body_splitter.addWidget(right_widget)
        
        body_splitter.setStretchFactor(0, 2)
        body_splitter.setStretchFactor(1, 3)
        layout.addWidget(body_splitter)
        
        preview_label = QLabel("预览")
        preview_label.setStyleSheet("color: palette(mid); font-size: 10px;")
        layout.addWidget(preview_label)
        preview_edit = QTextEdit()
        preview_edit.setReadOnly(True)
        preview_edit.setMinimumHeight(140)
        preview_edit.setStyleSheet("background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px; padding: 6px;")
        layout.addWidget(preview_edit)
        
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("应用到提示词")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn = QPushButton("复制")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn = QPushButton("删除系列")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setStyleSheet("color: #dc2626;")
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(dialog.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        
        dialog.session_list = session_list
        dialog.version_list = version_list
        dialog.preview_edit = preview_edit
        dialog.apply_btn = apply_btn
        dialog.copy_btn = copy_btn
        dialog.delete_btn = delete_btn
        dialog.count_label = count_label
        dialog.selected_text = ""
        
        session_list.currentItemChanged.connect(lambda item: self._on_history_session_selected(dialog, item))
        version_list.currentItemChanged.connect(lambda item: self._on_history_version_selected(dialog, item))
        version_list.itemDoubleClicked.connect(lambda _: self._apply_history_selection(prompt_type, dialog))
        apply_btn.clicked.connect(lambda: self._apply_history_selection(prompt_type, dialog))
        copy_btn.clicked.connect(lambda: self._copy_history_selection(dialog))
        delete_btn.clicked.connect(lambda: self._delete_history_session(prompt_type, dialog))
        return dialog

    def _refresh_history_dialog(self, dialog, prompt_type):
        sessions = self.history_manager.get_sessions(prompt_type)
        dialog.session_list.clear()
        dialog.version_list.clear()
        dialog.preview_edit.clear()
        dialog.selected_text = ""
        
        if not sessions:
            dialog.session_list.setEnabled(False)
            dialog.version_list.setEnabled(False)
            dialog.apply_btn.setEnabled(False)
            dialog.copy_btn.setEnabled(False)
            dialog.delete_btn.setEnabled(False)
            dialog.preview_edit.setPlainText("暂无历史记录")
            dialog.count_label.setText("0 条")
            return
        
        dialog.session_list.setEnabled(True)
        dialog.version_list.setEnabled(True)
        dialog.apply_btn.setEnabled(True)
        dialog.copy_btn.setEnabled(True)
        dialog.delete_btn.setEnabled(True)
        dialog.count_label.setText(f"{len(sessions)} 条")
        
        import datetime
        total = len(sessions)
        for i, session in enumerate(reversed(sessions)):
            base = session.get("base", "")
            ts = session.get("timestamp", 0)
            time_str = datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
            base_preview = (base[:24] + "...") if len(base) > 24 else (base or "空提示词")
            item = QListWidgetItem(f"系列 {total - i} · {time_str} · {base_preview}")
            item.setData(Qt.ItemDataRole.UserRole, session)
            dialog.session_list.addItem(item)
        dialog.session_list.setCurrentRow(0)

    def _on_history_session_selected(self, dialog, item):
        dialog.version_list.clear()
        dialog.preview_edit.clear()
        dialog.selected_text = ""
        if not item:
            return
        session = item.data(Qt.ItemDataRole.UserRole)
        if not session:
            return
        base = session.get("base", "")
        chain = session.get("chain", [])
        item_base = QListWidgetItem("原始版本")
        item_base.setData(Qt.ItemDataRole.UserRole, base)
        dialog.version_list.addItem(item_base)
        for idx, ver in enumerate(chain):
            item_ver = QListWidgetItem(f"版本 {idx + 1}")
            item_ver.setData(Qt.ItemDataRole.UserRole, ver)
            dialog.version_list.addItem(item_ver)
        dialog.version_list.setCurrentRow(0)

    def _on_history_version_selected(self, dialog, item):
        if not item:
            return
        text = item.data(Qt.ItemDataRole.UserRole)
        dialog.selected_text = text or ""
        dialog.preview_edit.setPlainText(dialog.selected_text)

    def _apply_history_selection(self, prompt_type, dialog):
        text = dialog.selected_text
        if not text:
            return
        self._restore_history(prompt_type, text)

    def _copy_history_selection(self, dialog):
        text = dialog.selected_text
        if not text:
            return
        QApplication.clipboard().setText(text)

    def _delete_history_session(self, prompt_type, dialog):
        item = dialog.session_list.currentItem()
        if not item:
            return
        session = item.data(Qt.ItemDataRole.UserRole)
        if not session:
            return
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "删除历史系列",
            "确定删除当前系列吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        sessions = self.history_manager.sessions.get(prompt_type, [])
        if session in sessions:
            sessions.remove(session)
        self._refresh_history_dialog(dialog, prompt_type)

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
        if not self._ai_is_processing:
            if self.current_ai_worker is self.sender():
                self.current_ai_worker = None
            return

        self._ai_is_processing = False
        target_btn.setText("AI")
        target_btn.setEnabled(True)
        self.current_ai_worker = None
        self._ai_original_prompt = None
        
        if success:
            # status_label.setText("✅ 优化成功") # Label removed
            # QTimer.singleShot(3000, lambda: status_label.setText(""))
            final_text = (result or "").strip()
            original_text = (original_prompt or "").strip()
            target_edit.setPlainText(final_text or original_text)

            if final_text == original_text:
                self._temp_notify("ℹ️ 未检测到可优化内容，已保持原提示词")
            else:
                self._temp_notify("✅ AI优化成功")
                # Record History
                p_type = 'negative' if is_negative else 'positive'
                self.history_manager.add_record(p_type, original_prompt, final_text)
        else:
            # status_label.setText("❌ 失败")
            self._temp_notify("❌ 优化失败")
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
        
        if self._img_prompt_processing:
            self._temp_notify("当前正在执行图生文任务")
            return
        
        # 1. Cancel Logic
        if self._ai_is_processing:
            if self.current_ai_worker:
                self.current_ai_worker.is_cancelled = True
            
            # Reset UI
            self._ai_is_processing = False
            target_btn.setText("AI")
            # status_label.setText("🚫 已取消") # Label removed
            if hasattr(self, '_temp_notify'): self._temp_notify("🚫 已取消")
            # QTimer.singleShot(2000, lambda: status_label.setText(""))
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
                # status_label.setText("请在设置中配置GLM API Key")
                # QTimer.singleShot(3000, lambda: status_label.setText(""))
                self._temp_notify("请在设置中配置GLM API Key")
                return
        
        # 1. 弹出自定义对话框,询问用户需求
        existing_prompt = target_edit.toPlainText().strip()
        if not is_negative:
            existing_prompt = self._replace_current_lora_aliases_with_triggers(existing_prompt)
        label_prefix = "反向" if is_negative else ""
        
        # 预设标签
        if is_negative:
            preset_tags = [
                "一键优化", "去除马赛克", "去除水印/文字", "提升清晰度", "修正肢体崩坏", "过滤低质量",
                "避免多余手指", "避免脸部崩坏", "避免过曝", "避免噪点"
            ]
        else:
            preset_tags = [
                "一键优化", "换背景", "丰富画面细节", "改为夜景风格", "电影级光影", "质感提升", "增加环境描述",
                "全身照", "半身照", "近景特写", "远景构图", "增强景深"
            ]

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
        target_btn.setText("...")
        # status_label.setText("⏳ AI正在处理...")
        self._ai_original_prompt = existing_prompt
        
        # 3. 启动后台线程
        lora_guidance = {} if is_negative else self._build_lora_guidance_payload()
        self.current_ai_worker = AIWorker(
            user_input,
            existing_prompt,
            is_negative,
            lora_guidance=lora_guidance,
        )
        self.current_ai_worker.finished.connect(lambda s, r: self._on_ai_finished(s, r, is_negative, existing_prompt))
        
        # 连接流式更新信号
        self._ai_stream_started = False
        self.current_ai_worker.stream_update.connect(lambda chunk: self._on_ai_stream_update(chunk, is_negative))
        
        self.current_ai_worker.start()
    
    def _on_add_lora_click(self):

        """添加新的LoRA行"""
        # 添加前先刷新一次候选项
        self._refresh_comfyui_assets()
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
        
        if copy_func:
            btn_copy = QPushButton("复制")
            btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_copy.setFixedWidth(50)
            btn_copy.setStyleSheet("background: transparent; border: 1px solid palette(mid); border-radius: 3px; font-size: 10px; color: palette(mid);")
            btn_copy.clicked.connect(copy_func)
            header.addWidget(btn_copy)
            
        # 增加“调用”按钮
        btn_use = QPushButton("调用")
        btn_use.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_use.setFixedWidth(50)
        btn_use.setStyleSheet("""
            QPushButton {
                background-color: palette(button); 
                border: 1px solid palette(highlight); 
                border-radius: 3px; 
                font-size: 10px; 
                color: palette(highlight);
                font-weight: bold;
            }
            QPushButton:hover { background-color: palette(highlight); color: white; }
        """)
        # 根据标题绑定不同的调用逻辑
        if "反向" in title:
            btn_use.clicked.connect(self._use_selected_neg_prompt)
        else:
            btn_use.clicked.connect(self._use_selected_prompt)
        header.addWidget(btn_use)
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
            # 仅禁用编辑，不改动当前显示值
            return
        else:
            # 取消随机后必须有确定种子，避免仍然走随机分支
            text = self.seed_input.text().strip()
            if text and text != "-1":
                return
            if self.last_image_seed not in (None, "", "-1"):
                self.seed_input.setText(str(self.last_image_seed))
                return
            saved_seed = self.settings.value("gen_seed", "1", type=str).strip()
            if not saved_seed or saved_seed == "-1":
                saved_seed = "1"
            self.seed_input.setText(saved_seed)
    
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
        if not meta_data:
            self.clear_info()
            self.btn_apply_workspace.setEnabled(False)
            self.btn_remote_gen.setEnabled(False)
            return

        # 检查是否是同一张图的冗余更新
        new_path = meta_data.get('tech_info', {}).get('path')
        old_path = self.current_meta.get('tech_info', {}).get('path') if self.current_meta else None
        if new_path and old_path and new_path == old_path:
            return
            
        self.current_meta = meta_data # 保存当前元数据
            
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
        
        scheduler = params.get('Scheduler', params.get('scheduler', '-'))
        self.info_scheduler_label.setText(f"{scheduler}")
        
        denoise = params.get('Denoise', params.get('denoise', '-'))
        self.info_denoise_label.setText(f"{denoise}")
        
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

        update_detail("scheduler", params.get('Scheduler', params.get('scheduler')))
        update_detail("denoise", params.get('Denoise', params.get('denoise')))
        update_detail("model_hash", params.get('Model hash', params.get('model_hash')))
        
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

        # 5. Sampler & Scheduler
        try:
            sampler = params.get('Sampler', params.get('sampler_name'))
            if sampler:
                idx = self.sampler_combo.findText(sampler)
                if idx >= 0: self.sampler_combo.setCurrentIndex(idx)
            
            scheduler = params.get('Scheduler', params.get('scheduler'))
            if scheduler:
                idx = self.scheduler_combo.findText(scheduler)
                if idx >= 0: self.scheduler_combo.setCurrentIndex(idx)
        except: pass

        try:
            model_name = self.model_label.text().replace("🎨 ", "").strip()
            if model_name and model_name not in ["未选择模型", "未知模型"]:
                resolved = self._find_best_model_match(model_name)
                target = resolved or model_name
                idx = self.model_combo.findText(target)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
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
                meta = {
                    "note": lora.get("note", ""),
                    "prompt": lora.get("prompt", ""),
                    "auto_use_prompt": lora.get("auto_use_prompt", True),
                }
                if name:
                    self._add_lora_item(name, weight, lora_meta=meta)
            elif isinstance(lora, str):
                name, weight = _parse_lora_string(lora)
                if name:
                    self._add_lora_item(name, weight)
        self._save_loras()

    def _use_selected_prompt(self):
        """将选中的正向提示词调用到工作区"""
        text = self.info_prompt_val.toPlainText().strip()
        if text:
            self.prompt_edit.setPlainText(text)
            self._temp_notify("✅ 正向提示词已调用")

    def _use_selected_neg_prompt(self):
        """将选中的反向提示词调用到工作区"""
        text = self.info_neg_val.toPlainText().strip()
        if text:
            self.neg_prompt_edit.setPlainText(text)
            self._temp_notify("✅ 反向提示词已调用")

    def _save_loras(self):
        """保存当前LoRA配置到Settings"""
        try:
            lora_list = []
            for name, weight in self.current_loras.items():
                meta = self._normalize_lora_profile_meta(self.current_lora_meta.get(name, {}))
                lora_list.append(
                    {
                        "name": name,
                        "weight": weight,
                        "note": meta["note"],
                        "prompt": meta["prompt"],
                        "auto_use_prompt": meta["auto_use_prompt"],
                    }
                )
            
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
                    meta = {
                        "note": lora.get("note", ""),
                        "prompt": lora.get("prompt", ""),
                        "auto_use_prompt": lora.get("auto_use_prompt", True),
                    }
                    if name:
                        self._add_lora_item(name, weight, lora_meta=meta)
                elif isinstance(lora, str):
                    name = lora.strip()
                    if name:
                        self._add_lora_item(name, 1.0)
        except Exception as e:
            print(f"Error loading LoRAs: {e}")

    def _normalize_prompt_piece(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip()).lower()
        return re.sub(r"[，,;；。.!！？?\-_/|]+", "", normalized)

    def _split_prompt_pieces(self, prompt: str) -> List[str]:
        if not prompt:
            return []
        parts = re.split(r"[,，;；。\.\n!?！？]+", prompt)
        return [p.strip() for p in parts if p and p.strip()]

    def _collect_lora_prompt_extras(self) -> List[str]:
        extras = []
        seen = set()
        for name in self.current_loras.keys():
            meta = self.current_lora_meta.get(name, {})
            if not isinstance(meta, dict):
                continue
            if not bool(meta.get("auto_use_prompt", True)):
                continue
            prompt = str(meta.get("prompt", "") or "").strip()
            if not prompt:
                continue
            norm = self._normalize_prompt_piece(prompt)
            if norm and norm not in seen:
                seen.add(norm)
                extras.append(prompt)
        return extras

    def _build_lora_guidance_payload(self) -> Dict[str, Any]:
        loras: List[Dict[str, Any]] = []
        extras = self._collect_lora_prompt_extras()
        for name, weight in self.current_loras.items():
            meta = self._normalize_lora_profile_meta(self.current_lora_meta.get(name, {}))
            loras.append(
                {
                    "name": name,
                    "weight": float(weight),
                    "prompt": str(meta.get("prompt", "") or "").strip(),
                    "auto_use_prompt": bool(meta.get("auto_use_prompt", True)),
                }
            )
        return {"loras": loras, "extras": extras}

    def _replace_current_lora_aliases_with_triggers(self, text: str) -> str:
        if not text:
            return text
        guidance = self._build_lora_guidance_payload()
        mappings: List[Tuple[str, str]] = []
        for item in guidance.get("loras", []):
            trigger = str(item.get("prompt", "") or "").strip()
            name = str(item.get("name", "") or "").strip()
            if not trigger or not name:
                continue

            aliases = {name, os.path.basename(name)}
            stem, _ = os.path.splitext(os.path.basename(name))
            if stem:
                aliases.add(stem)
                for token in re.split(r"[-_.\s]+", stem):
                    token = token.strip()
                    if len(token) >= 2:
                        aliases.add(token)

            norm_trigger = self._normalize_prompt_piece(trigger)
            for alias in aliases:
                alias = str(alias or "").strip()
                if not alias:
                    continue
                if self._normalize_prompt_piece(alias) == norm_trigger:
                    continue
                mappings.append((alias, trigger))

        merged = text
        for alias, trigger in sorted(mappings, key=lambda x: len(x[0]), reverse=True):
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])"
            merged = re.sub(pattern, trigger, merged, flags=re.IGNORECASE)
        return merged

    def _merge_prompt_with_lora_extras(self, base_prompt: str):
        base_prompt = self._replace_current_lora_aliases_with_triggers((base_prompt or "").strip())
        extras = self._collect_lora_prompt_extras()
        if not extras:
            return base_prompt, 0

        pieces = self._split_prompt_pieces(base_prompt)
        deduped_pieces: List[str] = []
        existing = set()
        for piece in pieces:
            norm_piece = self._normalize_prompt_piece(piece)
            if not norm_piece or norm_piece in existing:
                continue
            existing.add(norm_piece)
            deduped_pieces.append(piece)
        base_prompt = "，".join(deduped_pieces) if deduped_pieces else ""

        append_parts = []
        for text in extras:
            norm = self._normalize_prompt_piece(text)
            if norm and norm not in existing:
                existing.add(norm)
                append_parts.append(text)

        if not append_parts:
            return self._enforce_single_lora_trigger_occurrence(base_prompt, extras), 0
        if base_prompt:
            merged = f"{base_prompt}，{'，'.join(append_parts)}"
        else:
            merged = "，".join(append_parts)
        return self._enforce_single_lora_trigger_occurrence(merged, extras), len(append_parts)

    def _enforce_single_lora_trigger_occurrence(self, prompt: str, extras: List[str]) -> str:
        text = (prompt or "").strip()
        if not text or not extras:
            return text

        for extra in extras:
            trigger = str(extra or "").strip()
            if not trigger:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(trigger)}(?![A-Za-z0-9_])", re.IGNORECASE)
            matches = list(pattern.finditer(text))
            if len(matches) <= 1:
                continue

            rebuilt: List[str] = []
            last_idx = 0
            for idx, m in enumerate(matches):
                if idx == 0:
                    rebuilt.append(text[last_idx:m.end()])
                else:
                    rebuilt.append(text[last_idx:m.start()])
                last_idx = m.end()
            rebuilt.append(text[last_idx:])
            text = "".join(rebuilt)

        pieces = self._split_prompt_pieces(text)
        return "，".join(pieces) if pieces else text

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

        # 7. Sampler & Scheduler (Combo) - Saving logic
        self.sampler_combo.currentTextChanged.connect(
            lambda t: self.settings.setValue("gen_sampler", t)
        )
        self.scheduler_combo.currentTextChanged.connect(
            lambda t: self.settings.setValue("gen_scheduler", t)
        )
        # Note: Loading is handled in _populate_samplers/_populate_schedulers

        self.model_combo.currentTextChanged.connect(
            lambda t: self.settings.setValue("gen_model", t)
        )
        self.unet_combo.currentTextChanged.connect(
            lambda t: self.settings.setValue("gen_unet", t)
        )
        self.vae_combo.currentTextChanged.connect(
            lambda t: self.settings.setValue("gen_vae", t)
        )
        self.clip_combo.currentTextChanged.connect(
            lambda t: self.settings.setValue("gen_clip", t)
        )

        # 8. Compare settings
        self.compare_weights_input.textChanged.connect(
            lambda t: self.settings.setValue("compare_weights", t)
        )
        saved_compare_weights = self.settings.value("compare_weights", "0.7,0.75,0.8,0.85", type=str)
        if saved_compare_weights:
            self.compare_weights_input.setText(saved_compare_weights)

        self.compare_combo_mode.currentIndexChanged.connect(
            lambda _: self.settings.setValue("compare_combo_mode", self.compare_combo_mode.currentData())
        )
        saved_combo_mode = self.settings.value("compare_combo_mode", "cartesian", type=str)
        idx_combo_mode = self.compare_combo_mode.findData(saved_combo_mode)
        self.compare_combo_mode.setCurrentIndex(idx_combo_mode if idx_combo_mode >= 0 else 0)

        self.compare_seed_mode_combo.currentIndexChanged.connect(
            lambda _: self.settings.setValue("compare_seed_mode", self.compare_seed_mode_combo.currentData())
        )
        saved_seed_mode = self.settings.value("compare_seed_mode", "fixed", type=str)
        idx_seed_mode = self.compare_seed_mode_combo.findData(saved_seed_mode)
        self.compare_seed_mode_combo.setCurrentIndex(idx_seed_mode if idx_seed_mode >= 0 else 0)

        self.compare_include_baseline.toggled.connect(
            lambda checked: self.settings.setValue("compare_include_baseline", checked)
        )
        self.compare_include_baseline.setChecked(
            self.settings.value("compare_include_baseline", False, type=bool)
        )

        # 9. LoRAs
        self._load_loras()

    def _open_last_compare_from_panel(self):
        self.compare_generate_requested.emit({"action": "open_last"})

    def _parse_compare_weights(self) -> List[float]:
        return parse_compare_weights_expression(self.compare_weights_input.text())

    def _get_compare_seed(self, seed_mode: str) -> int:
        if seed_mode == "fixed":
            seed_text = self.seed_input.text().strip()
            try:
                seed_val = int(seed_text)
            except Exception:
                seed_val = -1
            if seed_val == -1:
                fallback_seed = self.last_image_seed if self.last_image_seed not in (None, "", "-1") else 1
                try:
                    seed_val = int(fallback_seed)
                except Exception:
                    seed_val = 1
                self.seed_input.setText(str(seed_val))
            return int(seed_val)
        return random.SystemRandom().randint(10**17, 18446744073709551614)

    def _alloc_workflow_node_id(self, workflow: Dict[str, Any]) -> str:
        numeric_ids = [int(k) for k in workflow.keys() if str(k).isdigit()]
        return str((max(numeric_ids) if numeric_ids else 0) + 1)

    def _find_prompt_node_ids_for_workflow(self, workflow: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        # 首选 KSampler 的 positive/negative 回链
        for _, node in workflow.items():
            ctype = str(node.get("class_type", "")).lower()
            if "ksampler" not in ctype:
                continue
            inputs = node.get("inputs", {})
            pos_link = inputs.get("positive")
            neg_link = inputs.get("negative")
            pos_id = str(pos_link[0]) if isinstance(pos_link, list) and pos_link else None
            neg_id = str(neg_link[0]) if isinstance(neg_link, list) and neg_link else None
            return pos_id, neg_id
        return None, None

    def _apply_compare_loras(
        self,
        workflow: Dict[str, Any],
        lora_items: List[Tuple[str, float]]
    ) -> List[str]:
        missing_loras: List[str] = []
        lora_nodes = []
        for nid, node in workflow.items():
            ctype = str(node.get("class_type", "")).lower()
            if "loraloader" in ctype:
                try:
                    sort_id = int(nid)
                except Exception:
                    sort_id = 10**9
                lora_nodes.append((sort_id, str(nid)))
        lora_nodes.sort(key=lambda x: x[0])

        if not lora_nodes:
            return [name for name, _ in lora_items]

        first_id = lora_nodes[0][1]
        first_node = workflow.get(first_id, {})
        first_inputs = first_node.get("inputs", {})
        chain_ids = [nid for _, nid in lora_nodes]

        # 如果节点数量不足，则按首个 LoRA 节点链式扩容
        if len(lora_items) > len(chain_ids) and "model" in first_inputs:
            prev_id = first_id
            appended_ids = []
            for _ in range(len(lora_items) - len(chain_ids)):
                new_id = self._alloc_workflow_node_id(workflow)
                new_node = copy.deepcopy(first_node)
                new_inputs = new_node.setdefault("inputs", {})
                new_inputs["model"] = [prev_id, 0]
                if "clip" in new_inputs:
                    new_inputs["clip"] = [prev_id, 1]
                workflow[new_id] = new_node
                appended_ids.append(new_id)
                prev_id = new_id

            # 将原先消费 first_id 输出的 model/clip 引用重定向到链尾
            if appended_ids:
                final_id = appended_ids[-1]
                for nid, node in workflow.items():
                    if nid in appended_ids:
                        continue
                    inputs = node.get("inputs", {})
                    for key, value in inputs.items():
                        if not isinstance(value, list) or len(value) < 2:
                            continue
                        if str(value[0]) != first_id:
                            continue
                        if value[1] == 0:
                            inputs[key] = [final_id, 0]
                        elif value[1] == 1 and "clip" in first_inputs:
                            inputs[key] = [final_id, 1]

                chain_ids = [nid for _, nid in lora_nodes] + appended_ids

        # baseline 或多余节点都要静音
        for idx, nid in enumerate(chain_ids):
            node = workflow.get(nid, {})
            inputs = node.get("inputs", {})
            if idx < len(lora_items):
                lora_name, lora_weight = lora_items[idx]
                resolved = self._find_best_lora_match(lora_name)
                if "lora_name" in inputs:
                    if resolved:
                        inputs["lora_name"] = resolved
                    else:
                        missing_loras.append(lora_name)
                applied_weight = lora_weight if resolved or "lora_name" not in inputs else 0.0
                if "strength_model" in inputs:
                    inputs["strength_model"] = applied_weight
                if "strength_clip" in inputs:
                    inputs["strength_clip"] = applied_weight
            else:
                if "strength_model" in inputs:
                    inputs["strength_model"] = 0.0
                if "strength_clip" in inputs:
                    inputs["strength_clip"] = 0.0

        return sorted(set(missing_loras))

    def _build_compare_workflow(self, variant: Dict[str, Any], seed_mode: str) -> Dict[str, Any]:
        workflow = copy.deepcopy(DEFAULT_T2I_WORKFLOW)

        prompt_text = self.prompt_edit.toPlainText().strip()
        neg_text = self.neg_prompt_edit.toPlainText().strip()
        prompt_text, _ = self._merge_prompt_with_lora_extras(prompt_text)

        pos_id, neg_id = self._find_prompt_node_ids_for_workflow(workflow)
        if pos_id and pos_id in workflow:
            workflow[pos_id].setdefault("inputs", {})["text"] = prompt_text
        if neg_id and neg_id in workflow:
            workflow[neg_id].setdefault("inputs", {})["text"] = neg_text

        res_data = self.resolution_combo.currentData()
        user_width, user_height = res_data if res_data else (1200, 1600)
        user_steps = self.steps_value.value()
        user_cfg = self.cfg_value.value()
        user_sampler = self.sampler_combo.currentText()
        user_scheduler = self.scheduler_combo.currentText()

        seed_value = variant.get("seed")
        if seed_mode == "random" and seed_value is None:
            seed_value = random.SystemRandom().randint(10**17, 18446744073709551614)

        for node_id, node in workflow.items():
            class_type = str(node.get("class_type", "")).lower()
            inputs = node.setdefault("inputs", {})

            if "ksampler" in class_type:
                if "seed" in inputs and seed_value is not None:
                    inputs["seed"] = int(seed_value)
                if "steps" in inputs:
                    inputs["steps"] = user_steps
                if "cfg" in inputs:
                    inputs["cfg"] = user_cfg
                if "sampler_name" in inputs and user_sampler:
                    inputs["sampler_name"] = user_sampler
                if "scheduler" in inputs and user_scheduler:
                    inputs["scheduler"] = user_scheduler

            if "latentimage" in class_type and "empty" in class_type:
                if "width" in inputs:
                    inputs["width"] = user_width
                if "height" in inputs:
                    inputs["height"] = user_height
                if "batch_size" in inputs:
                    inputs["batch_size"] = 1

            if "checkpointloader" in class_type and "ckpt_name" in inputs:
                selected_model = self.model_combo.currentText() if hasattr(self, "model_combo") else ""
                if selected_model and selected_model != "自动":
                    resolved_model = self._find_best_model_match(selected_model)
                    if resolved_model:
                        inputs["ckpt_name"] = resolved_model

            if "unetloader" in class_type and "unet_name" in inputs:
                selected_unet = self.unet_combo.currentText() if hasattr(self, "unet_combo") else ""
                if selected_unet and selected_unet != "自动":
                    resolved_unet = self._find_best_unet_match(selected_unet)
                    if resolved_unet:
                        inputs["unet_name"] = resolved_unet

            if "vaeloader" in class_type and "vae_name" in inputs:
                selected_vae = self.vae_combo.currentText() if hasattr(self, "vae_combo") else ""
                if selected_vae and selected_vae != "自动":
                    resolved_vae = self._find_best_vae_match(selected_vae)
                    if resolved_vae:
                        inputs["vae_name"] = resolved_vae

            if "cliploader" in class_type and "clip_name" in inputs:
                selected_clip = self.clip_combo.currentText() if hasattr(self, "clip_combo") else ""
                if selected_clip and selected_clip != "自动":
                    resolved_clip = self._find_best_clip_match(selected_clip)
                    if resolved_clip:
                        inputs["clip_name"] = resolved_clip

        lora_items = variant.get("lora_items", [])
        missing_loras = self._apply_compare_loras(workflow, lora_items)
        if missing_loras:
            self._temp_notify(f"⚠️ LoRA 未匹配到: {'、'.join(missing_loras)}")
        return workflow

    def _build_compare_variants(self) -> Tuple[List[Dict[str, Any]], str]:
        weights = self._parse_compare_weights()
        combo_mode = str(self.compare_combo_mode.currentData() or "cartesian")
        seed_mode = str(self.compare_seed_mode_combo.currentData() or "fixed")
        include_baseline = self.compare_include_baseline.isChecked()
        lora_names = list(self.current_loras.keys())

        if not lora_names and not include_baseline:
            raise ValueError("当前没有选择 LoRA，至少选择一个 LoRA 或勾选基线图。")

        variants: List[Dict[str, Any]] = []
        if include_baseline:
            variants.append(
                {
                    "variant_id": "baseline",
                    "label": "基线图 (无LoRA)",
                    "lora_items": [],
                    "is_baseline": True,
                }
            )

        if lora_names:
            if combo_mode == "pairwise":
                if len(lora_names) != len(weights):
                    raise ValueError(
                        f"按位配对模式要求 LoRA 数量({len(lora_names)}) 与权重数量({len(weights)})一致。"
                    )
                pairs = list(zip(lora_names, weights))
            else:
                pairs = [(lora_name, weight) for lora_name in lora_names for weight in weights]

            for idx, (lora_name, weight) in enumerate(pairs):
                variants.append(
                    {
                        "variant_id": f"variant_{idx + 1}",
                        "label": f"{os.path.basename(lora_name)} @ {weight:g}",
                        "lora_name": lora_name,
                        "lora_weight": float(weight),
                        "lora_items": [(lora_name, float(weight))],
                    }
                )

        # 填充 seed
        fixed_seed = self._get_compare_seed(seed_mode) if seed_mode == "fixed" else None
        for variant in variants:
            if seed_mode == "fixed":
                variant["seed"] = fixed_seed
            else:
                variant["seed"] = random.SystemRandom().randint(10**17, 18446744073709551614)
            variant["seed_mode"] = seed_mode
        return variants, seed_mode

    def _on_compare_generate_click(self):
        try:
            variants, seed_mode = self._build_compare_variants()
        except Exception as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return

        expected_count = len(variants)
        if expected_count <= 0:
            QMessageBox.warning(self, "提示", "没有可提交的对比任务。")
            return

        if expected_count > 20:
            ret = QMessageBox.question(
                self,
                "数量较多",
                f"本次将提交 {expected_count} 个对比任务，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        self._refresh_comfyui_assets()
        session_id = str(uuid.uuid4())
        session_name = f"LoRA对比 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        workflows: List[Dict[str, Any]] = []
        contexts: List[Dict[str, Any]] = []
        for idx, variant in enumerate(variants):
            workflow = self._build_compare_workflow(variant, seed_mode=seed_mode)
            workflows.append(workflow)
            contexts.append(
                {
                    "session_id": session_id,
                    "variant_id": variant["variant_id"],
                    "variant_index": idx,
                    "label": variant["label"],
                    "seed_mode": seed_mode,
                    "seed": variant.get("seed"),
                }
            )

        payload = {
            "action": "start",
            "session_id": session_id,
            "session_name": session_name,
            "expected_count": expected_count,
            "seed_mode": seed_mode,
            "variants": variants,
            "workflows": workflows,
            "contexts": contexts,
            "prompt": self.prompt_edit.toPlainText().strip(),
            "negative_prompt": self.neg_prompt_edit.toPlainText().strip(),
        }
        self.compare_generate_requested.emit(payload)
        self._temp_notify(f"已提交 LoRA 对比任务: {expected_count} 张")

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
        self._refresh_comfyui_assets()
            
        params = self.current_meta.get('params', {}) if self.current_meta else {} 
        # 智能同步修改后的提示词到工作流 (V5.4 精准透明版)
        new_prompt = self.prompt_edit.toPlainText().strip()
        new_neg = self.neg_prompt_edit.toPlainText().strip()
        new_prompt, lora_prompt_count = self._merge_prompt_with_lora_extras(new_prompt)
        self._log(f"[Comfy] 已附加 LoRA 提示词: {lora_prompt_count} 条")
        
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
            try:
                parsed_seed = int(user_seed_text) if user_seed_text else None
            except Exception:
                parsed_seed = None
            if parsed_seed is None or parsed_seed == -1:
                fallback_seed = self.last_image_seed if self.last_image_seed not in (None, "", "-1") else 1
                try:
                    user_seed = int(fallback_seed)
                except Exception:
                    user_seed = 1
                self.seed_input.setText(str(user_seed))
            else:
                user_seed = parsed_seed
        
        # 从下拉框获取分辨率
        res_data = self.resolution_combo.currentData()
        user_width, user_height = res_data if res_data else (512, 768)
        
        user_cfg = self.steps_value.value() if hasattr(self, 'steps_value') else 7.5 # fallback for cfg reading? Wait.
        # Wait, the line above has a bug in my thought, let me re-check steps/cfg lines.
        # Line 2868 is user_steps = self.steps_value.value()
        # Line 2869 is user_cfg = self.cfg_value.value()
        # Line 2870 is user_sampler = self.sampler_combo.currentText()
        
        user_steps = self.steps_value.value()
        user_cfg = self.cfg_value.value()
        user_sampler = self.sampler_combo.currentText()
        user_scheduler = self.scheduler_combo.currentText()
        
        # 3. 注入用户自定义参数到workflow
        self._log(f"\n[Comfy] ========== 参数注入开始 ==========")
        self._log(f"[Comfy] 用户参数:")
        self._log(f"  → Seed: {user_seed if user_seed is not None else '随机'}")
        self._log(f"  → 分辨率: {user_width}x{user_height}")
        self._log(f"  → Steps: {user_steps}")
        self._log(f"  → CFG: {user_cfg}")
        self._log(f"  → Sampler: {user_sampler}")
        self._log(f"  → Scheduler: {user_scheduler}")
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
                    seed_mode = "固定Seed" if user_seed is not None else "超随机Seed"
                    self._log(f"[Comfy] -> 注入{seed_mode}: 节点 {node_id} -> {final_seed}")
                
                # Steps
                if 'steps' in inputs:
                    inputs['steps'] = user_steps
                    self._log(f"[Comfy] -> 注入Steps: 节点 {node_id} -> {user_steps}")
                
                # CFG
                if 'cfg' in inputs:
                    inputs['cfg'] = user_cfg
                    self._log(f"[Comfy] -> 注入CFG: 节点 {node_id} -> {user_cfg}")
                
                # Sampler & Scheduler
                if 'sampler_name' in inputs and user_sampler:
                    inputs['sampler_name'] = user_sampler
                    self._log(f"[Comfy] -> 注入Sampler: 节点 {node_id} -> {user_sampler}")
                
                if 'scheduler' in inputs and user_scheduler:
                    inputs['scheduler'] = user_scheduler
                    self._log(f"[Comfy] -> 注入Scheduler: 节点 {node_id} -> {user_scheduler}")
            
            # CheckpointLoader节点: 注入模型名称
            if 'checkpointloader' in class_type:
                if 'ckpt_name' in inputs:
                    selected_model = None
                    if hasattr(self, "model_combo"):
                        selected_model = self.model_combo.currentText()
                    current_model = selected_model if selected_model and selected_model != "自动" else self.model_label.text().replace("🎨 ", "").strip()
                    
                    if current_model and current_model not in ["未选择模型", "未知模型"]:
                        real_model_name = self._find_best_model_match(current_model)
                        
                        if real_model_name:
                            inputs['ckpt_name'] = real_model_name
                            self._log(f"[Comfy] -> 注入Model (精准匹配): {real_model_name}")
                        else:
                            if '.' not in current_model:
                                current_model += ".safetensors"
                                self._log(f"[Comfy] ⚠️ 本地未找到匹配模型，尝试自动补全: {current_model}")
                            
                            inputs['ckpt_name'] = current_model
                            self._log(f"[Comfy] -> 注入Model: 节点 {node_id} -> {current_model}")
                    else:
                        fallback_model = None
                        if hasattr(self, 'available_models') and self.available_models:
                            fallback_model = self.available_models[0]
                        
                        if fallback_model:
                            inputs['ckpt_name'] = fallback_model
                            self._log(f"[Comfy] -> 注入Model (默认回退): {fallback_model}")
                        else:
                            self._log(f"[Comfy] ⚠️ 未注入模型: UI未选择有效模型且未获取可用模型列表")
            
            # UNETLoader节点: 注入UNET模型名称
            if 'unetloader' in class_type:
                if 'unet_name' in inputs:
                    selected_unet = None
                    if hasattr(self, "unet_combo"):
                        selected_unet = self.unet_combo.currentText()
                    current_model = self.model_label.text().replace("🎨 ", "").strip()
                    desired_unet = selected_unet if selected_unet and selected_unet != "自动" else (current_model if current_model and current_model not in ["未选择模型", "未知模型"] else inputs.get("unet_name"))
                    resolved_unet = self._find_best_unet_match(desired_unet) if desired_unet else None
                    if resolved_unet:
                        inputs['unet_name'] = resolved_unet
                        self._log(f"[Comfy] -> 注入UNET Model: 节点 {node_id} -> {resolved_unet}")
                    else:
                        self._log(f"[Comfy] ⚠️ 未注入UNET模型: 未找到匹配项")

            if 'vaeloader' in class_type:
                if 'vae_name' in inputs:
                    selected_vae = None
                    if hasattr(self, "vae_combo"):
                        selected_vae = self.vae_combo.currentText()
                    desired_vae = selected_vae if selected_vae and selected_vae != "自动" else inputs.get("vae_name")
                    resolved_vae = self._find_best_vae_match(desired_vae) if desired_vae else None
                    if resolved_vae:
                        inputs['vae_name'] = resolved_vae
                        self._log(f"[Comfy] -> 注入VAE: 节点 {node_id} -> {resolved_vae}")
                    else:
                        self._log(f"[Comfy] ⚠️ 未注入VAE: 未找到匹配项")

            if 'cliploader' in class_type:
                if 'clip_name' in inputs:
                    selected_clip = None
                    if hasattr(self, "clip_combo"):
                        selected_clip = self.clip_combo.currentText()
                    desired_clip = selected_clip if selected_clip and selected_clip != "自动" else inputs.get("clip_name")
                    resolved_clip = self._find_best_clip_match(desired_clip) if desired_clip else None
                    if resolved_clip:
                        inputs['clip_name'] = resolved_clip
                        self._log(f"[Comfy] -> 注入CLIP: 节点 {node_id} -> {resolved_clip}")
                    else:
                        self._log(f"[Comfy] ⚠️ 未注入CLIP: 未找到匹配项")

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
            missing_loras = set()
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
                        resolved_lora_name = self._find_best_lora_match(lora_name)
                        if 'lora_name' in inputs:
                            if resolved_lora_name:
                                inputs['lora_name'] = resolved_lora_name
                                self._log(f"[Comfy] -> 注入LoRA名称: 节点 {nid} -> {resolved_lora_name}")
                            else:
                                if 'strength_model' in inputs:
                                    inputs['strength_model'] = 0.0
                                if 'strength_clip' in inputs:
                                    inputs['strength_clip'] = 0.0
                                lora_weight = 0.0
                                self._log(f"[Comfy] ⚠️ LoRA 未找到，未写入: {lora_name}")
                                missing_loras.add(lora_name)
                        
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
        if self.current_loras:
            try:
                if missing_loras:
                    missing_text = "、".join(sorted(missing_loras))
                    self._temp_notify(f"⚠️ LoRA 未匹配到: {missing_text}")
            except:
                pass
        
        # 发送请求信号
        batch_count = self.batch_count_spin.value()
        self.remote_gen_requested.emit(workflow, batch_count, self.seed_random_checkbox.isChecked())
        QTimer.singleShot(800, _restore_btn)

    def set_available_models(self, models: List[str]):
        """设置可用模型列表 (来自ComfyUI)"""
        self.available_models = models
        # print(f"[UI] 已接收可用模型列表: {len(models)} 个")

    def _find_best_model_match(self, ui_name: str) -> str:
        """在可用模型列表中寻找最佳匹配 (优先精准，后包含)"""
        available = []
        if hasattr(self, 'available_models') and self.available_models:
            available = self.available_models
        elif hasattr(self, 'available_checkpoints') and self.available_checkpoints:
            available = self.available_checkpoints
        if not available:
            return None
            
        # 0. 预处理：移除潜在的 "🎨 " 前缀 (防守性编程)
        clean_name = ui_name.replace("🎨 ", "").strip()
        
        # 1. 精确匹配
        if clean_name in available:
            return clean_name
            
        # 2. 尝试加上 .safetensors 或 .ckpt 后匹配
        for ext in ['.safetensors', '.ckpt', '.pt', '.sft']:
            if clean_name + ext in available:
                return clean_name + ext
        
        # 3. 忽略路径匹配 (ui_name = "model.safetensors", available = "SDXL/model.safetensors")
        for m in available:
            if m.endswith(clean_name) or m.endswith(clean_name + ".safetensors"):
                return m
                
        # 4. 模糊包含匹配 (最宽松 - 慎用，但在不匹配时好过没有)
        # ui_name = "turbo_bf16" -> "z_image_turbo_bf16.safetensors"
        for m in available:
            if clean_name in m:
                return m
                
        return None

    def _find_best_lora_match(self, ui_name: str) -> str:
        if not hasattr(self, 'available_loras') or not self.available_loras:
            return None
        
        # ui_name 可能是绝对路径 (来自新选择器) 也可能是相对路径/文件名 (来自旧保存/输入)
        clean_name = ui_name.replace("🎨 ", "").strip()
        clean_lower = clean_name.lower().replace("\\", "/") # 归一化查找
        
        # 1. 尝试直接匹配 (精确)
        if clean_name in self.available_loras:
            return clean_name
        
        # 2. 尝试匹配相对路径 (如果 ui_name 是绝对路径)
        # 遍历 available_loras (它们通常是相对路径)，看是否 ui_name 以它结尾
        # 例如: ui_name = "D:/ComfyUI/models/loras/style/anime.safetensors"
        # available = "style/anime.safetensors"
        # -> ui_name.endswith(available) -> True
        for m in self.available_loras:
            m_norm = m.replace("\\", "/")
            if clean_lower.endswith(m_norm.lower()):
                 return m
        
        # 3. 尝试扩展名匹配
        for ext in ['.safetensors', '.ckpt', '.pt', '.sft']:
            if clean_name + ext in self.available_loras:
                return clean_name + ext
        
        # 4. 尝试文件名匹配 (最宽松)
        base_clean = os.path.basename(clean_name).lower()
        base_no_ext = os.path.splitext(base_clean)[0]
        
        candidates = []
        for m in self.available_loras:
            base = os.path.basename(m).lower()
            base_no = os.path.splitext(base)[0]
            if base == base_clean or base_no == base_no_ext:
                candidates.append(m)
        
        if len(candidates) >= 1:
            # 如果有多个候选 (比如不同文件夹下同名)，优先选最短的(通常是根目录)? 或者选第一个
            # 这里简单选第一个
            return candidates[0]
            
        return None

    def _find_best_unet_match(self, ui_name: str) -> str:
        if not hasattr(self, 'available_unets') or not self.available_unets:
            return None
        clean_name = ui_name.replace("🎨 ", "").strip()
        if clean_name in self.available_unets:
            return clean_name
        for ext in ['.safetensors', '.ckpt', '.pt', '.sft']:
            if clean_name + ext in self.available_unets:
                return clean_name + ext
        for m in self.available_unets:
            if m.endswith(clean_name) or m.endswith(clean_name + ".safetensors"):
                return m
        for m in self.available_unets:
            if clean_name in m:
                return m
        return None

    def _find_best_vae_match(self, ui_name: str) -> str:
        if not hasattr(self, 'available_vaes') or not self.available_vaes:
            return None
        clean_name = ui_name.replace("🎨 ", "").strip()
        if clean_name in self.available_vaes:
            return clean_name
        for ext in ['.safetensors', '.ckpt', '.pt', '.sft']:
            if clean_name + ext in self.available_vaes:
                return clean_name + ext
        for m in self.available_vaes:
            if m.endswith(clean_name) or m.endswith(clean_name + ".safetensors"):
                return m
        for m in self.available_vaes:
            if clean_name in m:
                return m
        return None

    def _find_best_clip_match(self, ui_name: str) -> str:
        if not hasattr(self, 'available_clips') or not self.available_clips:
            return None
        clean_name = ui_name.replace("🎨 ", "").strip()
        if clean_name in self.available_clips:
            return clean_name
        for ext in ['.safetensors', '.ckpt', '.pt', '.sft']:
            if clean_name + ext in self.available_clips:
                return clean_name + ext
        for m in self.available_clips:
            if m.endswith(clean_name) or m.endswith(clean_name + ".safetensors"):
                return m
        for m in self.available_clips:
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
        if hasattr(self, "workspace_scroll") and source is self.workspace_scroll.viewport():
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self._apply_responsive_layout()
                return False
        if hasattr(self, "neg_bottom_handle") and source is self.neg_bottom_handle:
            if event.type() == QEvent.Type.MouseButtonPress:
                self._neg_bottom_dragging = True
                try:
                    self._neg_bottom_start_y = int(event.globalPosition().y())
                except Exception:
                    self._neg_bottom_start_y = int(event.pos().y())
                self._neg_bottom_start_h = int(self.neg_prompt_edit.height())
                sizes = self.prompt_splitter.sizes() if hasattr(self, "prompt_splitter") else [0, 0]
                self._neg_bottom_start_top_size = int(sizes[0]) if len(sizes) > 0 else 0
                self._neg_bottom_start_bottom_size = int(sizes[1]) if len(sizes) > 1 else 0
                return True
            if event.type() == QEvent.Type.MouseMove and self._neg_bottom_dragging:
                try:
                    current_y = int(event.globalPosition().y())
                except Exception:
                    current_y = int(event.pos().y())
                delta = current_y - self._neg_bottom_start_y
                new_h = max(40, min(520, self._neg_bottom_start_h + delta))
                self.neg_prompt_edit.setFixedHeight(new_h)
                if hasattr(self, "prompt_splitter"):
                    bottom_delta = new_h - self._neg_bottom_start_h
                    target_bottom = max(72, self._neg_bottom_start_bottom_size + bottom_delta)
                    target_top = max(80, self._neg_bottom_start_top_size)
                    target_total = target_top + target_bottom + self.prompt_splitter.handleWidth()
                    self.prompt_splitter.setFixedHeight(target_total)
                    self.prompt_splitter.setSizes([target_top, target_bottom])
                    self.prompt_splitter.updateGeometry()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._neg_bottom_dragging:
                self._neg_bottom_dragging = False
                self.settings.setValue("param_panel/neg_prompt_height", int(self.neg_prompt_edit.height()))
                if hasattr(self, "prompt_splitter"):
                    self._save_prompt_splitter_state()
                return True
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
