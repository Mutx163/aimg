from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTextEdit, QScrollArea,
                             QFrame, QGridLayout, QHBoxLayout, QPushButton, QApplication, 
                             QSplitter, QGroupBox, QSpinBox, QDoubleSpinBox, QSlider, 
                             QComboBox, QLineEdit, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from typing import List
import random
import copy

class ParameterPanel(QWidget):
    """
    重设计的参数信息面板 - V4.0
    采用卡片化、层次化设计，参考SD WebUI最佳实践
    """
    remote_gen_requested = pyqtSignal(dict) # 发送修改后的工作流
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
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
        
        # 恢复之前的选择，如果没有选择，则默认选择512x768
        target_res = current_res if current_res else (512, 768)
        
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

    def _populate_samplers(self, samplers: List[str]):
        """填充采样器下拉框"""
        print(f"[UI] _populate_samplers被调用，采样器列表: {samplers}")
        
        # 记录当前选中
        current_sampler = self.sampler_combo.currentText()
        self.sampler_combo.clear()
        
        if samplers:
            for sampler in samplers:
                self.sampler_combo.addItem(sampler)
                print(f"[UI] 添加采样器: {sampler}")
        else:
            # 如果没有历史记录，添加一些常用采样器
            default_samplers = ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde"]
            print(f"[UI] 没有历史采样器，使用默认列表: {default_samplers}")
            for sampler in default_samplers:
                self.sampler_combo.addItem(sampler)
        
        # 优先恢复之前的选择
        if current_sampler:
            index = self.sampler_combo.findText(current_sampler)
            if index >= 0:
                self.sampler_combo.setCurrentIndex(index)
                return

        # 默认选择第一个
        if self.sampler_combo.count() > 0:
            self.sampler_combo.setCurrentIndex(0)
            print(f"[UI] 采样器下拉框已填充，共 {self.sampler_combo.count()} 项")
        else:
            print(f"[UI] 警告：采样器下拉框为空！")

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
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(12)
        
        header_lbl = QLabel("🛠️ 生成工作区 (在此修改并生成)")
        header_lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: palette(highlight);")
        outer_layout.addWidget(header_lbl)

        # --- 1. 可编辑文本区 ---
        def create_edit_block(title, placeholder, height):
            outer_layout.addWidget(QLabel(title, styleSheet=self._label_style))
            edit = QTextEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMaximumHeight(height)
            edit.setStyleSheet("background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px; padding: 5px;")
            outer_layout.addWidget(edit)
            return edit

        self.prompt_edit = create_edit_block("✨ 正向提示词", "输入新的提示词进行创作...", 100)
        self.neg_prompt_edit = create_edit_block("🚫 反向提示词", "输入过滤词...", 80)
        
        # --- 2. 其他参数设置 ---
        self.gen_settings_container = QWidget()
        gen_layout = QVBoxLayout(self.gen_settings_container)
        gen_layout.setContentsMargins(0, 0, 0, 0)
        gen_layout.setSpacing(10)
        
        # 将整个外层容器添加到父布局
        parent_layout.addWidget(gen_settings_outer)
        
        # ===== Seed行 =====
        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)
        
        lbl_seed = QLabel("Seed:")
        lbl_seed.setStyleSheet("color: palette(mid); font-size: 11px; min-width: 80px;")
        seed_row.addWidget(lbl_seed)
        
        self.seed_input = QLineEdit()
        self.seed_input.setText("-1")  # 默认显示-1表示随机
        self.seed_input.setPlaceholderText("输入种子数值")
        self.seed_input.setMinimumWidth(160)
        self.seed_input.setStyleSheet("padding: 4px; border-radius: 3px;")
        seed_row.addWidget(self.seed_input)
        
        # 改用复选框替代按钮
        from PyQt6.QtWidgets import QCheckBox
        self.seed_random_checkbox = QCheckBox("随机")
        self.seed_random_checkbox.setToolTip("勾选后每次生成使用随机种子")
        self.seed_random_checkbox.setChecked(True)  # 默认随机
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
        res_row.setSpacing(8)
        
        lbl_res = QLabel("分辨率:")
        lbl_res.setStyleSheet("color: palette(mid); font-size: 11px; min-width: 80px;")
        res_row.addWidget(lbl_res)
        
        self.resolution_combo = QComboBox()
        self.resolution_combo.setMinimumWidth(200)
        self.resolution_combo.setStyleSheet("padding: 4px;")
        
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
        
        # ===== Steps行 =====
        steps_row = QHBoxLayout()
        steps_row.setSpacing(8)
        
        lbl_steps = QLabel("Steps:")
        lbl_steps.setStyleSheet("color: palette(mid); font-size: 11px; min-width: 80px;")
        steps_row.addWidget(lbl_steps)
        
        self.steps_value = QSpinBox()
        self.steps_value.setRange(1, 150)
        self.steps_value.setValue(20)
        self.steps_value.setMinimumWidth(100)
        self.steps_value.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.steps_value.setStyleSheet("""
            QSpinBox {
                padding: 6px;
                font-size: 12px;
                border: 1px solid palette(mid);
                border-radius: 3px;
                background-color: palette(base);
            }
            QSpinBox:focus {
                border: 2px solid palette(highlight);
            }
        """)
        steps_row.addWidget(self.steps_value)
        steps_row.addStretch()
        
        gen_layout.addLayout(steps_row)
        
        # ===== CFG行 =====
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(8)
        
        lbl_cfg = QLabel("CFG Scale:")
        lbl_cfg.setStyleSheet("color: palette(mid); font-size: 11px; min-width: 80px;")
        cfg_row.addWidget(lbl_cfg)
        
        self.cfg_value = QDoubleSpinBox()
        self.cfg_value.setRange(1.0, 30.0)
        self.cfg_value.setSingleStep(0.5)
        self.cfg_value.setValue(7.5)
        self.cfg_value.setDecimals(1)
        self.cfg_value.setMinimumWidth(100)
        self.cfg_value.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.cfg_value.setStyleSheet("""
            QDoubleSpinBox {
                padding: 6px;
                font-size: 12px;
                border: 1px solid palette(mid);
                border-radius: 3px;
                background-color: palette(base);
            }
            QDoubleSpinBox:focus {
                border: 2px solid palette(highlight);
            }
        """)
        cfg_row.addWidget(self.cfg_value)
        cfg_row.addStretch()
        
        gen_layout.addLayout(cfg_row)
        
        # ===== 采样器行 =====
        sampler_row = QHBoxLayout()
        sampler_row.setSpacing(8)
        
        lbl_sampler = QLabel("采样器:")
        lbl_sampler.setStyleSheet("color: palette(mid); font-size: 11px; min-width: 80px;")
        sampler_row.addWidget(lbl_sampler)
        
        self.sampler_combo = QComboBox()
        self.sampler_combo.setMinimumWidth(200)
        self.sampler_combo.setStyleSheet("padding: 4px;")
        sampler_row.addWidget(self.sampler_combo)
        sampler_row.addStretch()
        
        gen_layout.addLayout(sampler_row)
        
        # ===== LoRA管理区域 =====
        lora_header_row = QHBoxLayout()
        lora_header_row.setSpacing(8)
        
        lbl_loras = QLabel("LoRAs:")
        lbl_loras.setStyleSheet("color: palette(mid); font-size: 11px; min-width: 80px; font-weight: bold;")
        lora_header_row.addWidget(lbl_loras)
        lora_header_row.addStretch()
        
        gen_layout.addLayout(lora_header_row)
        
        # LoRA列表容器（滚动区域）
        self.lora_scroll = QScrollArea()
        self.lora_scroll.setWidgetResizable(True)
        self.lora_scroll.setMaximumHeight(150)
        self.lora_scroll.setStyleSheet("QScrollArea { border: 1px solid palette(mid); border-radius: 3px; background-color: palette(base); }")
        
        self.lora_container = QWidget()
        self.lora_layout = QVBoxLayout(self.lora_container)
        self.lora_layout.setContentsMargins(4, 4, 4, 4)
        self.lora_layout.setSpacing(4)
        self.lora_layout.addStretch()  # 底部弹簧，让项目靠上显示
        
        self.lora_scroll.setWidget(self.lora_container)
        gen_layout.addWidget(self.lora_scroll)
        
        # 存储LoRA数据: {name: weight}
        self.current_loras = {}
        
        # 添加LoRA按钮
        add_lora_btn = QPushButton("+ 添加LoRA")
        add_lora_btn.setMaximumWidth(120)
        add_lora_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 8px;
                background-color: palette(button);
                border: 1px solid palette(mid);
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: palette(light);
            }
        """)
        add_lora_btn.clicked.connect(self._on_add_lora_click)
        gen_layout.addWidget(add_lora_btn)
        
        outer_layout.addWidget(self.gen_settings_container)
        
        # --- 3. 底部生成按钮 (从上方移动到这里) ---
        self.btn_remote_gen = QPushButton("🔥 开始远程生成")
        self.btn_remote_gen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remote_gen.setMinimumHeight(40)
        self.btn_remote_gen.setObjectName("RemoteGenButton")
        self.btn_remote_gen.setStyleSheet("""
            QPushButton#RemoteGenButton {
                background-color: #ff4d00;
                color: white;
                border: none;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
                margin-top: 5px;
            }
            QPushButton#RemoteGenButton:hover { background-color: #ff6a00; }
            QPushButton#RemoteGenButton:pressed { background-color: #e64500; }
            QPushButton#RemoteGenButton:disabled { background-color: #444; color: #888; }
        """)
        self.btn_remote_gen.clicked.connect(self._on_remote_gen_click)
        outer_layout.addWidget(self.btn_remote_gen)
        
        # 将整个外层容器添加到父布局
        parent_layout.addWidget(gen_settings_outer)
    
    
    def _add_lora_item(self, name: str = "", weight: float = 1.0):
        """添加一个LoRA项到列表（下拉框模式）"""
        # 限制最多5个LoRA
        if len(self.current_loras) >= 5:
            print("[UI] 已达到LoRA数量上限（5个）")
            return
        
        # 获取所有可用的LoRA
        main_window = self.window()
        if not hasattr(main_window, 'db_manager'):
            return
        
        all_loras_raw = main_window.db_manager.get_unique_loras()
        all_loras = []
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
        
        # 如果指定了名称，选中它
        if name:
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
        weight_spin.setValue(weight)
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
            lambda v: self._update_lora_weight_from_combo(lora_combo, v)
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
            print(f"[UI] 添加LoRA: {name} (权重: {weight})")
    
    def _on_lora_selection_changed(self, widget, text, combo):
        """当LoRA选择改变时"""
        if text == "选择LoRA..." or not text:
            # 从数据中移除（如果之前有选择）
            old_data = combo.property("selected_lora")
            if old_data and old_data in self.current_loras:
                del self.current_loras[old_data]
            combo.setProperty("selected_lora", None)
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
            print(f"[UI] LoRA '{text}' 已被使用")
            return
        
        # 更新数据
        old_name = combo.property("selected_lora")
        if old_name and old_name in self.current_loras:
            del self.current_loras[old_name]
        
        weight_spin = combo.property("weight_spin")
        weight = weight_spin.value() if weight_spin else 1.0
        self.current_loras[text] = weight
        combo.setProperty("selected_lora", text)
        print(f"[UI] 选择LoRA: {text} (权重: {weight})")
    
    def _update_lora_weight_from_combo(self, combo, weight):
        """从ComboBox更新LoRA权重"""
        lora_name = combo.property("selected_lora")
        if lora_name and lora_name in self.current_loras:
            self.current_loras[lora_name] = weight
            print(f"[UI] 更新LoRA权重: {lora_name} -> {weight}")
    
    def _remove_lora_item_widget(self, widget, combo):
        """删除LoRA项（ComboBox模式）"""
        lora_name = combo.property("selected_lora")
        if lora_name and lora_name in self.current_loras:
            del self.current_loras[lora_name]
            print(f"[UI] 删除LoRA: {lora_name}")
        
        self.lora_layout.removeWidget(widget)
        widget.deleteLater()
    
    def _remove_lora_item(self, name: str, widget: QWidget):
        """删除一个LoRA项（兼容旧方法）"""
        if name in self.current_loras:
            del self.current_loras[name]
        
        self.lora_layout.removeWidget(widget)
        widget.deleteLater()
        print(f"[UI] 删除LoRA: {name}")
    
    def _update_lora_weight(self, name: str, weight: float):
        """更新LoRA权重"""
        if name in self.current_loras:
            self.current_loras[name] = weight
            print(f"[UI] 更新LoRA权重: {name} -> {weight}")
    
    def _clear_lora_list(self):
        """清空LoRA列表"""
        # 删除所有LoRA项（保留stretch）
        while self.lora_layout.count() > 1:
            item = self.lora_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.current_loras.clear()
        print(f"[UI] 清空LoRA列表")
    
    
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
            # 自动切换为固定模式，方便用户微调
            self.seed_random_checkbox.setChecked(False)
        
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
        sampler = params.get('Sampler', params.get('sampler_name'))
        if sampler:
            for i in range(self.sampler_combo.count()):
                if self.sampler_combo.itemText(i) == sampler:
                    self.sampler_combo.setCurrentIndex(i)
                    break
                    
        # 6. LoRAs
        self._clear_lora_list()
        for lora in loras:
            name, weight = "", 1.0
            if isinstance(lora, dict):
                name = lora.get('name', '')
                weight = lora.get('weight', 1.0)
            elif isinstance(lora, str):
                name = lora
            if name:
                # 简单清理名称（移除括号权重）
                clean_name = name.split('(')[0].strip()
                self._add_lora_item(clean_name, float(weight))
        
        self._temp_notify("✨ 已成功调用参数到工作区")

    def _on_remote_gen_click(self):
        """处理远程生成点击"""
        if not hasattr(self, 'current_meta') or not self.current_meta:
            return
        
        raw_workflow = self.current_meta.get('workflow')
        if not raw_workflow:
            return
            
        # 使用深拷贝防止修改内存中的原始元数据副本
        workflow = copy.deepcopy(raw_workflow)
            
        # 智能同步修改后的提示词到工作流 (V5.4 精准透明版)
        new_prompt = self.prompt_edit.toPlainText().strip()
        new_neg = self.neg_prompt_edit.toPlainText().strip()
        
        pos_node_id = self.current_meta.get('prompt_node_id')
        neg_node_id = self.current_meta.get('negative_prompt_node_id')
        
        print(f"\n[Comfy] --- 准备提交生成任务 ---")
        
        # 1. 注入提示词
        if pos_node_id and pos_node_id in workflow:
            workflow[pos_node_id]['inputs']['text'] = new_prompt
            print(f"[Comfy] -> 正向提示词注入节点: {pos_node_id} (CLIPTextEncode)")
        
        if neg_node_id and neg_node_id in workflow:
            workflow[neg_node_id]['inputs']['text'] = new_neg
            print(f"[Comfy] -> 反向提示词注入节点: {neg_node_id} (CLIPTextEncode)")
        
        # 2. 读取用户自定义参数
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
        print(f"\n[Comfy] ========== 参数注入开始 ==========")
        print(f"[Comfy] 用户参数:")
        print(f"  → Seed: {user_seed if user_seed is not None else '随机'}")
        print(f"  → 分辨率: {user_width}x{user_height}")
        print(f"  → Steps: {user_steps}")
        print(f"  → CFG: {user_cfg}")
        print(f"  → Sampler: {user_sampler}")
        print(f"  → LoRAs: {list(self.current_loras.keys())}")
        
        # 遍历workflow节点注入参数
        print(f"\n[Comfy] 开始遍历workflow节点...")
        modified_nodes = []
        
        for node_id, node in workflow.items():
            class_type = node.get('class_type', '').lower()
            inputs = node.get('inputs', {})
            
            print(f"[Comfy] 检查节点 {node_id}: {node.get('class_type')} ({class_type})")
            
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
                    self.seed_label.setText(str(final_seed)) # 同时更新顶部展示卡片
                    print(f"[Comfy] -> 注入超随机Seed: 节点 {node_id} -> {final_seed}")
                
                # Steps
                if 'steps' in inputs:
                    inputs['steps'] = user_steps
                    print(f"[Comfy] -> 注入Steps: 节点 {node_id} -> {user_steps}")
                
                # CFG
                if 'cfg' in inputs:
                    inputs['cfg'] = user_cfg
                    print(f"[Comfy] -> 注入CFG: 节点 {node_id} -> {user_cfg}")
                
                # Sampler
                if 'sampler_name' in inputs and user_sampler:
                    inputs['sampler_name'] = user_sampler
                    print(f"[Comfy] -> 注入Sampler: 节点 {node_id} -> {user_sampler}")
            
            # LoraLoader节点：注入LoRA名称和权重
            if 'loraloader' in class_type:
                # 简单模式：只修改现有LoraLoader节点
                # 从current_loras中获取第一个LoRA（如果有多个LoraLoader，按顺序分配）
                if self.current_loras:
                    lora_list = list(self.current_loras.items())
                    # 找到这是第几个LoraLoader节点
                    lora_loader_count = sum(1 for nid, n in workflow.items() 
                                           if nid < node_id and 'loraloader' in n.get('class_type', '').lower())
                    
                    if lora_loader_count < len(lora_list):
                        lora_name, lora_weight = lora_list[lora_loader_count]
                        
                        # 注入LoRA名称
                        if 'lora_name' in inputs:
                            inputs['lora_name'] = lora_name
                            print(f"[Comfy] -> 注入LoRA名称: 节点 {node_id} -> {lora_name}")
                        
                        # 注入LoRA权重
                        for weight_key in ['strength_model', 'strength_clip']:
                            if weight_key in inputs:
                                inputs[weight_key] = lora_weight
                        print(f"[Comfy] -> 注入LoRA权重: 节点 {node_id} -> {lora_weight}")
            
            # Latent节点：注入分辨率（支持多种类型）
            # EmptyLatentImage, EmptySD3LatentImage, EmptySDXLLatentImage等
            if 'latentimage' in class_type and 'empty' in class_type:
                print(f"[Comfy] 找到Latent节点 {node_id}: {node.get('class_type')}")
                print(f"[Comfy]   原始参数: width={inputs.get('width')}, height={inputs.get('height')}")
                
                if 'width' in inputs and 'height' in inputs:
                    old_width = inputs['width']
                    old_height = inputs['height']
                    inputs['width'] = user_width
                    inputs['height'] = user_height
                    modified_nodes.append(node_id)
                    print(f"[Comfy] ✅ 注入分辨率: 节点 {node_id}")
                    print(f"[Comfy]   {old_width}x{old_height} → {user_width}x{user_height}")
                else:
                    print(f"[Comfy] ⚠️ 节点缺少width/height字段: {list(inputs.keys())}")

        print(f"\n[Comfy] ========== 参数注入完成 ==========")
        print(f"[Comfy] 修改的节点: {modified_nodes}")
        print(f"[Comfy] --- 任务数据准备就绪 ---\n")
        
        # 发送请求信号
        self.remote_gen_requested.emit(workflow)

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
