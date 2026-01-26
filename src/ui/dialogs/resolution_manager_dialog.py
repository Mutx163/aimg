from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QPushButton, QLabel, QSpinBox, QFrame, QMessageBox, QListWidgetItem)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor

class ResolutionManagerDialog(QDialog):
    """自定义分辨率管理对话框"""
    
    def __init__(self, preset_res=None, history_res=None, parent=None):
        super().__init__(parent)
        self.settings = QSettings("ComfyUIImageManager", "Settings")
        self.preset_res = preset_res or []
        self.history_res = history_res or []
        
        self.setWindowTitle("分辨率管理中心")
        self.resize(420, 520)
        
        self.setup_ui()
        self._load_all_resolutions()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        layout.addWidget(QLabel("当前库中所有分辨率 (自定义项可删除):"))
        
        self.res_list = QListWidget()
        self.res_list.setStyleSheet("""
            QListWidget {
                border: 1px solid palette(mid);
                border-radius: 4px;
                background-color: palette(base);
                outline: none;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid palette(alternate-base);
            }
        """)
        self.res_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.res_list)
        
        # 添加区域
        add_group = QFrame()
        add_group.setStyleSheet("QFrame { background-color: palette(alternate-base); border-radius: 6px; }")
        add_layout = QVBoxLayout(add_group)
        add_layout.setContentsMargins(10, 10, 10, 10)
        
        lbl_add = QLabel("添加新分辨率:")
        lbl_add.setStyleSheet("font-weight: bold;")
        add_layout.addWidget(lbl_add)
        
        input_row = QHBoxLayout()
        self.width_input = QSpinBox()
        self.width_input.setRange(64, 8192)
        self.width_input.setValue(1024)
        self.width_input.setSuffix(" px")
        
        self.height_input = QSpinBox()
        self.height_input.setRange(64, 8192)
        self.height_input.setValue(1024)
        self.height_input.setSuffix(" px")
        
        input_row.addWidget(QLabel("宽:"))
        input_row.addWidget(self.width_input)
        input_row.addWidget(QLabel(" 高:"))
        input_row.addWidget(self.height_input)
        
        add_layout.addLayout(input_row)
        
        self.add_btn = QPushButton("保存为自定义分辨率")
        self.add_btn.setFixedHeight(30)
        self.add_btn.clicked.connect(self._on_add_clicked)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: palette(highlight);
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: palette(midlight); }
        """)
        add_layout.addWidget(self.add_btn)
        
        layout.addWidget(add_group)
        
        # 操作按钮
        btn_row = QHBoxLayout()
        self.del_btn = QPushButton("🗑️ 删除选中的自定义项")
        self.del_btn.clicked.connect(self._on_delete_clicked)
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.del_btn)
        
        btn_row.addStretch()
        
        self.close_btn = QPushButton("完成")
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)
        
        layout.addLayout(btn_row)

    def _load_all_resolutions(self):
        self.res_list.clear()
        
        # 1. 自定义列表 (QSettings 存储格式为 "widthxheight" 字符串列表)
        custom = self.settings.value("custom_resolutions", [], type=list)
        
        # 2. 准备所有数据用于显示
        # 预设
        for w, h in sorted(self.preset_res, key=lambda x: (x[0], x[1])):
            item = QListWidgetItem(f"⭐ {w} x {h} [系统预设]")
            item.setData(Qt.ItemDataRole.UserRole, ("preset", w, h))
            item.setForeground(Qt.GlobalColor.gray)
            self.res_list.addItem(item)
            
        # 历史
        for w, h in sorted(self.history_res, key=lambda x: (x[0], x[1])):
            item = QListWidgetItem(f"🕒 {w} x {h} [历史记录]")
            item.setData(Qt.ItemDataRole.UserRole, ("history", w, h))
            self.res_list.addItem(item)

        # 自定义
        for res_str in sorted(custom):
            try:
                w, h = map(int, res_str.split('x'))
                item = QListWidgetItem(f"📌 {w} x {h} [用户自定义]")
                item.setData(Qt.ItemDataRole.UserRole, ("custom", w, h))
                item.setForeground(QColor("#60cdff"))
                self.res_list.addItem(item)
            except: continue

    def _on_item_double_clicked(self, item):
        role, w, h = item.data(Qt.ItemDataRole.UserRole)
        self.width_input.setValue(w)
        self.height_input.setValue(h)

    def _on_add_clicked(self):
        w = self.width_input.value()
        h = self.height_input.value()
        res_str = f"{w}x{h}"
        
        custom = self.settings.value("custom_resolutions", [], type=list)
        if res_str in custom:
            return
            
        custom.append(res_str)
        self.settings.setValue("custom_resolutions", custom)
        self.settings.sync()
        self._load_all_resolutions()

    def _on_delete_clicked(self):
        selected = self.res_list.currentItem()
        if not selected: return
            
        role, w, h = selected.data(Qt.ItemDataRole.UserRole)
        if role != "custom":
            QMessageBox.warning(self, "提示", "只能删除用户自定义的分辨率。")
            return
            
        res_str = f"{w}x{h}"
        custom = self.settings.value("custom_resolutions", [], type=list)
        if res_str in custom:
            custom.remove(res_str)
            self.settings.setValue("custom_resolutions", custom)
            self.settings.sync()
            self._load_all_resolutions()
