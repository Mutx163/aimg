from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QCheckBox, QPushButton, QGroupBox, QFormLayout, QLineEdit)
from PyQt6.QtCore import Qt, QSettings

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(400, 300)
        self.settings = QSettings("ComfyUIImageManager", "Settings")
        
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
        
        # AI提示词优化 - 配置
        self.edit_ai_base_url = QLineEdit()
        self.edit_ai_base_url.setPlaceholderText("例如: https://open.bigmodel.cn/api/paas/v4")
        self.edit_ai_base_url.setText(self.settings.value("ai_base_url", "https://open.bigmodel.cn/api/paas/v4"))
        form_layout.addRow("AI API地址:", self.edit_ai_base_url)

        self.edit_ai_model = QLineEdit()
        self.edit_ai_model.setPlaceholderText("例如: glm-4.7-flash")
        self.edit_ai_model.setText(self.settings.value("ai_model_name", "glm-4.7-flash"))
        form_layout.addRow("AI模型名称:", self.edit_ai_model)

        self.edit_glm_api_key = QLineEdit()
        self.edit_glm_api_key.setPlaceholderText("输入 API Key")

        self.edit_glm_api_key.setEchoMode(QLineEdit.EchoMode.Password)  # 密码模式
        self.edit_glm_api_key.setText(self.settings.value("glm_api_key", ""))
        
        # 添加说明标签
        glm_help_label = QLabel('<a href="https://open.bigmodel.cn">免费获取API Key</a>')
        glm_help_label.setOpenExternalLinks(True)
        glm_help_label.setStyleSheet("color: #8b5cf6; font-size: 10px;")
        
        form_layout.addRow("GLM API Key:", self.edit_glm_api_key)
        form_layout.addRow("", glm_help_label)
        
        # ComfyUI 设置
        self.edit_comfy_addr = QLineEdit()
        self.edit_comfy_addr.setPlaceholderText("例如: 127.0.0.1:8188")
        self.edit_comfy_addr.setText(self.settings.value("comfy_address", "127.0.0.1:8188"))
        form_layout.addRow("ComfyUI 地址:", self.edit_comfy_addr)
        
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
        self.settings.setValue("ai_base_url", self.edit_ai_base_url.text().strip())
        self.settings.setValue("ai_model_name", self.edit_ai_model.text().strip())
        self.settings.setValue("glm_api_key", self.edit_glm_api_key.text().strip())
        self.settings.setValue("comfy_address", self.edit_comfy_addr.text().strip())
        
        self.accept()
