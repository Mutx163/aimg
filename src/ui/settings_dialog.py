from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QCheckBox, QPushButton, QGroupBox, QFormLayout)
from PyQt6.QtCore import Qt, QSettings

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(400, 300)
        self.settings = QSettings("Antigravity", "AIImageViewer")
        
        layout = QVBoxLayout(self)
        
        # 1. 操作设置组
        group_input = QGroupBox("输入与操作")
        form_layout = QFormLayout(group_input)
        
        # 滚轮行为
        self.combo_wheel = QComboBox()
        self.combo_wheel.addItems(["缩放图片 (默认)", "切换上一张/下一张"])
        # 读取当前设置
        current_wheel = self.settings.value("wheel_action", "zoom")
        self.combo_wheel.setCurrentIndex(0 if current_wheel == "zoom" else 1)
        form_layout.addRow("鼠标滚轮:", self.combo_wheel)
        
        # 界面主题
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["深色专业 (推荐)", "经典浅色"])
        current_theme = self.settings.value("theme", "dark")
        self.combo_theme.setCurrentIndex(0 if current_theme == "dark" else 1)
        form_layout.addRow("界面主题:", self.combo_theme)
        
        # 删除确认
        self.check_del_confirm = QCheckBox("删除文件时显示确认框")
        self.check_del_confirm.setChecked(self.settings.value("confirm_delete", True, type=bool))
        form_layout.addRow("", self.check_del_confirm)
        
        layout.addWidget(group_input)
        
        # 2. 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self.save_settings)
        btn_layout.addWidget(btn_save)
        
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        layout.addStretch()

    def save_settings(self):
        # 保存设置到 QSettings
        wheel_action = "zoom" if self.combo_wheel.currentIndex() == 0 else "navigate"
        theme = "dark" if self.combo_theme.currentIndex() == 0 else "light"
        self.settings.setValue("wheel_action", wheel_action)
        self.settings.setValue("theme", theme)
        self.settings.setValue("confirm_delete", self.check_del_confirm.isChecked())
        
        self.accept()
