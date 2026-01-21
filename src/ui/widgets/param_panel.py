from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTextEdit, QScrollArea,
                             QFrame, QGridLayout, QHBoxLayout, QPushButton, QApplication, 
                             QSplitter, QGroupBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

class ParameterPanel(QWidget):
    """
    重设计的参数信息面板 - V4.0
    采用卡片化、层次化设计，参考SD WebUI最佳实践
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(8)
        
        # ========== 1. 顶部核心信息卡片 ==========
        self.info_card = QFrame()
        self.info_card.setStyleSheet("""
            QFrame {
                background-color: palette(window);
                border: 1px solid palette(mid);
                border-radius: 8px;
            }
            QLabel { border: none; background: transparent; }
        """)
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
        btn_copy_all.setFixedWidth(90)
        btn_copy_all.setStyleSheet("""
            QPushButton {
                padding: 4px 8px;
                border: 1px solid palette(mid);
                border-radius: 4px;
                background-color: palette(button);
            }
            QPushButton:hover { background-color: palette(midlight); }
        """)
        btn_copy_all.clicked.connect(self._copy_all_params)
        title_row.addWidget(btn_copy_all)
        info_card_layout.addLayout(title_row)
        
        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: palette(mid); max-height: 1px;")
        info_card_layout.addWidget(line)
        
        # 参数网格展示区 (不再使用沉重的 GroupBox)
        self.stats_grid = QGridLayout()
        self.stats_grid.setVerticalSpacing(6)
        self.stats_grid.setHorizontalSpacing(20)
        
        # 预定义标签，统一样式
        label_style = "color: palette(mid); font-weight: bold; font-size: 11px;"
        value_style = "color: palette(text); font-size: 11px;"
        
        def add_stat(row, col, label_text, attr_name):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(label_style)
            val = QLabel("-")
            val.setStyleSheet(value_style)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            setattr(self, attr_name, val)
            self.stats_grid.addWidget(lbl, row, col)
            self.stats_grid.addWidget(val, row, col + 1)

        add_stat(0, 0, "SEED", "seed_label")
        add_stat(0, 2, "分辨率", "resolution_label")
        add_stat(1, 0, "STEPS", "steps_label")
        add_stat(1, 2, "CFG", "cfg_label")
        add_stat(2, 0, "采样器", "sampler_label")
        
        info_card_layout.addLayout(self.stats_grid)

        # 更多细节网格 (平铺展示)
        self.details_layout = QGridLayout()
        self.details_layout.setVerticalSpacing(4)
        info_card_layout.addLayout(self.details_layout)
        
        # LoRA 区域
        lora_box = QVBoxLayout()
        lora_title = QLabel("LORAS")
        lora_title.setStyleSheet(label_style)
        lora_box.addWidget(lora_title)
        
        self.lora_container = QWidget()
        self.lora_flow = QHBoxLayout(self.lora_container)
        self.lora_flow.setContentsMargins(0, 5, 0, 0)
        self.lora_flow.setSpacing(6)
        lora_box.addWidget(self.lora_container)
        info_card_layout.addLayout(lora_box)
        
        self.layout.addWidget(self.info_card)
        
        # ========== 2. Prompt/Negative/详细参数区 (可拉伸) ==========
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Prompt 区
        self.prompt_group = self._create_collapsible_group("✨ Prompt", self._copy_prompt)
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setReadOnly(True)
        self.prompt_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 2px;
                background-color: palette(base);
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
            }
        """)
        self.prompt_group.layout().addWidget(self.prompt_edit)
        self.main_splitter.addWidget(self.prompt_group)
        
        # Negative Prompt 区
        self.neg_group = self._create_collapsible_group("🚫 Negative Prompt", self._copy_neg_prompt)
        self.neg_prompt_edit = QTextEdit()
        self.neg_prompt_edit.setReadOnly(True)
        self.neg_prompt_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 2px;
                background-color: palette(base);
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
            }
        """)
        self.neg_group.layout().addWidget(self.neg_prompt_edit)
        self.main_splitter.addWidget(self.neg_group)
        
        # 设置初始权重 - 更加均衡，减少单方面区域过大的空旷感
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 1)
        
        self.layout.addWidget(self.main_splitter)

    def _create_collapsible_group(self, title, copy_func):
        """创建可折叠分组"""
        group = QGroupBox(title)
        group_layout = QVBoxLayout()
        group_layout.setContentsMargins(4, 15, 4, 4) # 减小内边距
        group_layout.setSpacing(2) # 极简间距
        
        # 标题栏+复制按钮
        header = QHBoxLayout()
        header.addStretch()
        btn_copy = QPushButton("📋")
        btn_copy.setFixedWidth(30)
        btn_copy.clicked.connect(copy_func)
        btn_copy.setToolTip("复制")
        header.addWidget(btn_copy)
        group_layout.addLayout(header)
        
        group.setLayout(group_layout)
        return group

    def _copy_prompt(self):
        text = self.prompt_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._temp_notify("✅ 提示词已复制")
            # 查找复制按钮并临时改变文字
            self._flash_button_feedback(self.prompt_group, "✓")

    def _copy_neg_prompt(self):
        text = self.neg_prompt_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._temp_notify("✅ 反向提示词已复制")
            self._flash_button_feedback(self.neg_group, "✓")

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

    def _temp_notify(self, msg):
        main_win = self.window()
        if hasattr(main_win, 'statusBar'):
            main_win.statusBar().showMessage(msg, 2000)

    def update_info(self, meta_data):
        """更新UI - V4.0新版"""
        if not meta_data:
            self.clear_info()
            return
            
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
        self.seed_label.setText(f"Seed: {seed}")
        
        resolution = tech_info.get('resolution', '-')
        self.resolution_label.setText(f"分辨率: {resolution}")
        
        steps = params.get('Steps', params.get('steps', '-'))
        self.steps_label.setText(f"Steps: {steps}")
        
        cfg = params.get('CFG scale', params.get('cfg', '-'))
        self.cfg_label.setText(f"CFG: {cfg}")
        
        sampler = params.get('Sampler', params.get('sampler_name', '-'))
        self.sampler_label.setText(f"Sampler: {sampler}")
        
        # 更新LoRA标签云
        self._clear_lora_tags()
        for lora in loras:
            tag = QLabel(f"{lora}")
            tag.setStyleSheet("""
                QLabel {
                    background-color: palette(midlight);
                    color: palette(text);
                    border: 1px solid palette(mid);
                    border-radius: 4px;
                    padding: 3px 8px;
                    font-size: 11px;
                }
            """)
            tag.setMaximumHeight(22)
            self.lora_flow.addWidget(tag)
        self.lora_flow.addStretch() # 靠左排列
        
        # 更新Prompt
        self.prompt_edit.setText(meta_data.get('prompt', ''))
        self.neg_prompt_edit.setText(meta_data.get('negative_prompt', ''))
        
        # 更新详细参数 (平铺展示)
        self._clear_layout(self.details_layout)
        row = 0
        # 其他生成参数
        detail_keys = ['Scheduler', 'Denoise', 'Model hash']
        for key in detail_keys:
            if key in params:
                self.details_layout.addWidget(QLabel(f"{key}:"), row, 0)
                self.details_layout.addWidget(QLabel(str(params[key])), row, 1)
                row += 1
        
        # 文件信息
        if tech_info:
            self.details_layout.addWidget(QLabel("文件大小:"), row, 0)
            self.details_layout.addWidget(QLabel(tech_info.get('file_size', '-')), row, 1)
            row += 1
            
            self.details_layout.addWidget(QLabel("格式:"), row, 0)
            self.details_layout.addWidget(QLabel(tech_info.get('format', '-')), row, 1)

    def _clear_lora_tags(self):
        """清空LoRA标签"""
        while self.lora_flow.count():
            child = self.lora_flow.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

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
        self.seed_label.setText("Seed: -")
        self.resolution_label.setText("分辨率: -")
        self.steps_label.setText("Steps: -")
        self.cfg_label.setText("CFG: -")
        self.sampler_label.setText("Sampler: -")
        self._clear_lora_tags()
        self._clear_layout(self.details_layout)
        self.prompt_edit.clear()
        self.neg_prompt_edit.clear()
