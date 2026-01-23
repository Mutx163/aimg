from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QListWidget, QListWidgetItem, 
                             QLabel, QLineEdit, QHBoxLayout, QPushButton, QComboBox)
from PyQt6.QtCore import pyqtSignal, Qt

class ModelExplorer(QWidget):
    """
    显示当前已索引的模型和 LoRA 列表，支持点击过滤。
    """
    filter_requested = pyqtSignal(str, str) # 类型 (Model/Lora), 名称

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        # 极度紧凑模式
        self.layout.setContentsMargins(0, 4, 0, 4)
        self.layout.setSpacing(4)
        
        # 1. 核心筛选：Checkpoint 下拉框
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("模型:"))
        self.combo_model = QComboBox()
        self.combo_model.setEditable(False)
        self.combo_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_model.currentIndexChanged.connect(self._on_model_selected)
        model_layout.addWidget(self.combo_model, 1)
        self.layout.addLayout(model_layout)
        
        # 2. 核心筛选：LoRA 下拉框
        lora_layout = QHBoxLayout()
        lora_layout.addWidget(QLabel("LoRA:"))
        self.combo_lora = QComboBox()
        self.combo_lora.setEditable(False)
        self.combo_lora.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_lora.currentIndexChanged.connect(self._on_lora_selected)
        lora_layout.addWidget(self.combo_lora, 1)
        self.layout.addLayout(lora_layout)
        
        # 筛选结果提示 - 紧凑样式
        self.filter_hint = QLabel("显示全部图片")
        self.filter_hint.setObjectName("FilterHint")
        self.filter_hint.setMaximumHeight(20)
        self.filter_hint.setWordWrap(False)
        self.layout.addWidget(self.filter_hint)
        
        # 缓存原始数据用于下拉框过滤
        self.raw_models = []
        self.raw_loras = []

    def _on_search_text_changed(self, text):
        """联动过滤下拉框内容 (可选增强)"""
        pass

    def update_models(self, models, loras):
        """更新下拉框内容"""
        self.raw_models = models
        self.raw_loras = loras
        
        # 这种更新方式可以保留当前选中（如果还在的话）
        curr_model = self.combo_model.currentText()
        curr_lora = self.combo_lora.currentText()
        
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self.combo_model.addItem("全部模型", "ALL")
        for name, count in models:
            self.combo_model.addItem(f"{name} ({count})", name)
        self.combo_model.blockSignals(False)
        
        self.combo_lora.blockSignals(True)
        self.combo_lora.clear()
        self.combo_lora.addItem("全部 LoRA", "ALL")
        for name, count in loras:
            self.combo_lora.addItem(f"{name} ({count})", name)
        self.combo_lora.blockSignals(False)

    def _on_model_selected(self, index):
        if index < 0: return
        name = self.combo_model.itemData(index)
        if name:
            self.combo_lora.blockSignals(True)
            self.combo_lora.setCurrentIndex(0) # 切换模型时通常重置 LoRA 筛选
            self.combo_lora.blockSignals(False)
            self.filter_requested.emit("Model", name)
            self._update_hint()

    def _on_lora_selected(self, index):
        if index < 0: return
        name = self.combo_lora.itemData(index) # 获取绑定的 UserRole 数据
        if name:
            self.filter_requested.emit("Lora", name)
            self._update_hint()

    def _clear_selection(self):
        """重置所有筛选"""
        self.blockSignals(True)
        self.combo_model.setCurrentIndex(0)
        self.combo_lora.setCurrentIndex(0)
        self.blockSignals(False)
        self.filter_requested.emit("Model", "ALL")
        self._update_hint()

    def _update_hint(self):
        m = self.combo_model.currentText()
        l = self.combo_lora.currentText()
        if self.combo_model.currentIndex() <= 0 and self.combo_lora.currentIndex() <= 0:
            self.filter_hint.setText("显示全部图片")
        else:
            self.filter_hint.setText(f"已过滤: {m} | {l}")
