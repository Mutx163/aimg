from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTextEdit, QScrollArea,
                             QFrame, QGridLayout, QHBoxLayout, QPushButton, QApplication, 
                             QSplitter, QGroupBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
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
        
        # 添加远程生成按钮
        self.btn_remote_gen = QPushButton("🔥 远程生成")
        self.btn_remote_gen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remote_gen.setMinimumWidth(90)
        self.btn_remote_gen.setObjectName("RemoteGenButton")
        # 保持远程生成的特殊颜色，但调整为 Fluent 风格
        self.btn_remote_gen.setStyleSheet("""
            QPushButton#RemoteGenButton {
                background-color: #ff4d00;
                color: white;
                border: none;
                font-weight: bold;
            }
            QPushButton#RemoteGenButton:hover { background-color: #ff6a00; }
            QPushButton#RemoteGenButton:pressed { background-color: #e64500; }
            QPushButton#RemoteGenButton:disabled { background-color: #444; color: #888; }
        """)
        self.btn_remote_gen.clicked.connect(self._on_remote_gen_click)
        title_row.addWidget(self.btn_remote_gen)
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
        
        # 定义一个简单的样式函数
        def apply_edit_style(edit):
            edit.setReadOnly(False)
            edit.setStyleSheet("""
                QTextEdit {
                    background-color: transparent;
                    border: none;
                    font-family: "Segoe UI", "Microsoft YaHei";
                    font-size: 11px;
                    line-height: 1.4;
                    padding: 8px;
                }
            """)
            
        # Prompt 区
        self.prompt_container = QWidget()
        prompt_layout = QVBoxLayout(self.prompt_container)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.setSpacing(4)
        
        prompt_header = self._create_compact_header("✨ Prompt", self._copy_prompt)
        prompt_layout.addLayout(prompt_header)
        
        # 外框
        self.prompt_frame = QFrame()
        self.prompt_frame.setObjectName("TextCard")
        self.prompt_frame.setStyleSheet("""
            QFrame#TextCard {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
        """)
        pf_layout = QVBoxLayout(self.prompt_frame)
        pf_layout.setContentsMargins(1, 1, 1, 1)
        
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("在这里修改提示词...")
        apply_edit_style(self.prompt_edit)
        
        pf_layout.addWidget(self.prompt_edit)
        prompt_layout.addWidget(self.prompt_frame)
        
        self.main_splitter.addWidget(self.prompt_container)
        
        # Negative Prompt 区
        self.neg_container = QWidget()
        neg_layout = QVBoxLayout(self.neg_container)
        neg_layout.setContentsMargins(0, 0, 0, 0)
        neg_layout.setSpacing(4)
        
        neg_header = self._create_compact_header("🚫 Negative Prompt", self._copy_neg_prompt)
        neg_layout.addLayout(neg_header)
        
        self.neg_frame = QFrame()
        self.neg_frame.setObjectName("TextCard")
        self.neg_frame.setStyleSheet("""
            QFrame#TextCard {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
        """)
        nf_layout = QVBoxLayout(self.neg_frame)
        nf_layout.setContentsMargins(1, 1, 1, 1)
        
        self.neg_prompt_edit = QTextEdit()
        self.neg_prompt_edit.setPlaceholderText("在这里修改反向提示词...")
        apply_edit_style(self.neg_prompt_edit)
        
        nf_layout.addWidget(self.neg_prompt_edit)
        neg_layout.addWidget(self.neg_frame)
        
        self.main_splitter.addWidget(self.neg_container)
        
        # 设置初始权重 - 更加均衡，减少单方面区域过大的空旷感
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 1)
        
        self.layout.addWidget(self.main_splitter)

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

    def _temp_notify(self, msg):
        main_win = self.window()
        if hasattr(main_win, 'statusBar'):
            main_win.statusBar().showMessage(msg, 2000)

    def update_info(self, meta_data):
        """更新UI - V4.0新版"""
        self.current_meta = meta_data # 保存当前元数据
        if not meta_data:
            self.clear_info()
            self.btn_remote_gen.setEnabled(False)
            return
            
        # 只有 ComfyUI 导出的图片才支持远程生成（因为需要工作流 JSON）
        has_workflow = 'workflow' in meta_data
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
            tag.setObjectName("LoraTag")
            tag.setMaximumHeight(24)
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
        
        # 2. 采样器识别与种子随机化 (V5.5 广谱识别)
        sampler_count = 0
        for node_id, node in workflow.items():
            class_type = node.get('class_type', '').lower()
            # 匹配 KSampler, KSamplerAdvanced 以及其他包含 sampler 的自定义节点
            if 'sampler' in class_type:
                inputs = node.get('inputs', {})
                for seed_key in ['seed', 'noise_seed', 'noise_seed_value']:
                    if seed_key in inputs:
                        new_seed = random.randint(1000000000000, 9999999999999) 
                        inputs[seed_key] = new_seed
                        print(f"[Comfy] -> 注入随机种子: 节点 {node_id} ({node.get('class_type')}) -> {new_seed}")
                        sampler_count += 1
        
        if sampler_count == 0:
            print("[Comfy] ! 未在工作流中发现标准采样器节点，将尝试对所有包含 seed 关键字的节点进行注入")
            for node_id, node in workflow.items():
                inputs = node.get('inputs', {})
                for k in inputs.keys():
                    if 'seed' in k.lower() and isinstance(inputs[k], (int, float)):
                        new_seed = random.randint(1000000000000, 9999999999999)
                        inputs[k] = new_seed
                        print(f"[Comfy] -> 兜底随机化: 节点 {node_id}.{k} -> {new_seed}")
                        sampler_count += 1
        
        if sampler_count == 0:
            print("[Comfy] ! 最终警告: 工作流中完全未发现任何种子参数，可能会触发服务端缓存")

        print(f"[Comfy] --- 任务数据准备就绪 ---\n")
        
        # 发送请求信号
        self.remote_gen_requested.emit(workflow)

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
        
        # 禁用操作按钮
        for btn in self.info_card.findChildren(QPushButton):
            if "复制" in btn.text():
                btn.setEnabled(False)
        self.resolution_label.setText("分辨率: -")
        self.steps_label.setText("Steps: -")
        self.cfg_label.setText("CFG: -")
        self.sampler_label.setText("Sampler: -")
        self._clear_lora_tags()
        self._clear_layout(self.details_layout)
        self.prompt_edit.clear()
        self.neg_prompt_edit.clear()
