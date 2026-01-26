from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, 
                             QLabel, QWidget, QLineEdit, QPushButton, QScrollArea, QFrame,
                             QComboBox, QSplitter, QGraphicsDropShadowEffect, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QSettings
from PyQt6.QtGui import QIcon, QColor
import re
import os
from collections import defaultdict
from src.ui.utils.flow_layout import FlowLayout

class LoraVariant:
    def __init__(self, full_path):
        self.full_path = full_path
        self.filename = os.path.basename(full_path)
        self.clean_name, self.step_count, self.version = self._parse_info(self.filename)
        
    def _parse_info(self, filename):
        name_no_ext = os.path.splitext(filename)[0]
        
        # 1. 尝试提取步数
        step_count = None
        step_match = re.search(r'[-_](\d+)(?:steps?|k)?(?=\.|_|$)', name_no_ext, re.IGNORECASE)
        if step_match:
            try:
                raw_num = step_match.group(1)
                count = int(raw_num)
                # 简单启发式：如果是很小的数字可能是版本，大的可能是步数？不一定。
                # 假设通常 > 100 是步数
                if count >= 100:
                    step_count = count * 1000 if 'k' in step_match.group(0).lower() else count
            except: pass

        # 2. 尝试提取版本
        version = None
        ver_match = re.search(r'[-_]v?(\d+(?:\.\d+)?)', name_no_ext, re.IGNORECASE)
        if ver_match:
            version = ver_match.group(1)

        # 3. 清洗名称
        clean_name = name_no_ext
        # 如果有 step_match，移除它
        if step_match:
            clean_name = clean_name.replace(step_match.group(0), "")
        # 如果有 version_match，且它不是步数的一部分
        if ver_match and (not step_match or ver_match.group(0) not in step_match.group(0)):
             clean_name = clean_name.replace(ver_match.group(0), "")
             
        # 移除常见后缀和前缀
        clean_name = re.sub(r'[-_](fp16|bf16|safetensors|ckpt|pt)', '', clean_name, flags=re.IGNORECASE)
        clean_name = clean_name.strip(" -_")
        
        # 将剩余的下划线替换为空格，这是为了显示更友好
        # clean_name = clean_name.replace("_", " ") 
        
        return clean_name, step_count, version

class LoraGroup:
    def __init__(self, base_name):
        self.base_name = base_name
        self.variants = []
        self.is_pinned = False

    def add_variant(self, variant: LoraVariant):
        self.variants.append(variant)
        # 排序策略：优先按步数倒序，其次按版本倒序
        self.variants.sort(key=lambda x: (x.step_count or 0, float(x.version or 0)), reverse=True)

class NoScrollComboBox(QComboBox):
    def wheelEvent(self, event):
        # Ignore wheel events to prevent accidental value changes while scrolling the page
        event.ignore()

class LoraCard(QFrame):
    selected = pyqtSignal(str) 
    pinned_changed = pyqtSignal(bool) # 发送置顶状态

    def __init__(self, group: LoraGroup, parent=None):
        super().__init__(parent)
        self.group = group
        self.setObjectName("LoraCard")
        # 移除固定宽度，允许自适应
        self.setMinimumWidth(220)
        self.setMaximumWidth(450)
        
        # 移除阴影效果，回归扁平简洁
        
        self.setStyleSheet("""
            QFrame#LoraCard {
                background-color: palette(window);
                border: 1px solid palette(midlight);
                border-radius: 4px;
            }
            QFrame#LoraCard:hover {
                border: 1px solid palette(highlight);
                background-color: palette(base);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        
        # 头部：标题 + 徽章
        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)
        
        title = QLabel(group.base_name)
        title.setStyleSheet("font-weight: bold; color: palette(text);")
        # 标题省略号
        font_metrics = title.fontMetrics()
        elided_text = font_metrics.elidedText(group.base_name, Qt.TextElideMode.ElideRight, 130) # 留出位置给置顶按钮
        title.setText(elided_text)
        title.setToolTip(group.base_name)
        header_layout.addWidget(title)
        
        # 置顶按钮 - 统一风格，使用文字按钮
        self.pin_btn = QPushButton("置顶")
        if group.is_pinned:
            self.pin_btn.setStyleSheet("""
                QPushButton {
                    background-color: palette(highlight);
                    color: white;
                    border: 1px solid palette(highlight);
                    border-radius: 3px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: palette(midlight); }
            """)
        else:
            self.pin_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: palette(mid);
                    border: 1px solid palette(mid);
                    border-radius: 3px;
                    font-size: 10px;
                }
                QPushButton:hover { 
                    border-color: palette(highlight); 
                    color: palette(highlight); 
                }
            """)
            
        self.pin_btn.setFixedSize(40, 20)
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(group.is_pinned)
        self.pin_btn.setToolTip("置顶此模型" if not group.is_pinned else "取消置顶")
        
        self.pin_btn.clicked.connect(self._on_pin_clicked)
        header_layout.addWidget(self.pin_btn)
        
        header_layout.addStretch()
        
        if len(group.variants) > 1:
            badge = QLabel(f"{len(group.variants)}")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(20, 20)
            badge.setStyleSheet("""
                background-color: palette(mid); 
                color: palette(window-text); 
                border-radius: 10px; 
                font-weight: bold;
            """)
            badge.setToolTip(f"包含 {len(group.variants)} 个版本")
            header_layout.addWidget(badge)
            
        layout.addLayout(header_layout)
        
        # 变体选择器 (如果有多个)
        self.current_variant = group.variants[0]
        self.variant_combo = NoScrollComboBox()
        self.variant_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        # 移除自定义 padding/font-size
        
        has_multiple = len(group.variants) > 1
        
        if has_multiple:
            for v in group.variants:
                parts = []
                if v.step_count: parts.append(f"{v.step_count}步")
                if v.version: parts.append(f"v{v.version}")
                
                label = " ".join(parts) if parts else "基础版"
                if label == "基础版" and len(group.variants) > 1:
                     label = v.filename[-15:]
                
                self.variant_combo.addItem(label, v.full_path)
                self.variant_combo.setItemData(self.variant_combo.count()-1, v.filename, Qt.ItemDataRole.ToolTipRole)
                
            layout.addWidget(self.variant_combo)
        else:
            lbl = QLabel(self.current_variant.filename)
            lbl.setStyleSheet("color: palette(mid);")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            self.variant_combo.hide()
            
        # 底部按钮区
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.select_btn = QPushButton("选择")
        self.select_btn.setCursor(Qt.CursorShape.PointingHandCursor)  
        self.select_btn.setFixedSize(50, 24)
        # 移除复杂的 QSS，使用基本样式
        self.select_btn.setStyleSheet("") 
        self.select_btn.clicked.connect(self._on_select_clicked)
        btn_layout.addWidget(self.select_btn)
        
        layout.addLayout(btn_layout)

    def _on_pin_clicked(self):
        is_pinned = self.pin_btn.isChecked()
        self.group.is_pinned = is_pinned
        if is_pinned:
            self.pin_btn.setStyleSheet("""
                QPushButton {
                    background-color: palette(highlight);
                    color: white;
                    border: 1px solid palette(highlight);
                    border-radius: 3px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: palette(midlight); }
            """)
        else:
            self.pin_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: palette(mid);
                    border: 1px solid palette(mid);
                    border-radius: 3px;
                    font-size: 10px;
                }
                QPushButton:hover { 
                    border-color: palette(highlight); 
                    color: palette(highlight); 
                }
            """)
        self.pin_btn.setToolTip("置顶此模型" if not is_pinned else "取消置顶")
        self.pinned_changed.emit(is_pinned)

    def _on_select_clicked(self):
        if self.variant_combo.isVisible():
            full_path = self.variant_combo.currentData()
            self.selected.emit(full_path)
        else:
            self.selected.emit(self.group.variants[0].full_path)

class LoraSelectionDialog(QDialog):
    def __init__(self, all_loras, parent=None):
        super().__init__(parent)
        self.settings = QSettings("ComfyUIImageManager", "Settings")
        self.pinned_loras = self.settings.value("pinned_loras", [], type=list)
        
        self.setWindowTitle("选择 LoRA 模型")
        self.resize(900, 600)
        self.all_loras = all_loras
        selected = getattr(parent, "get_current_lora", lambda: None)() if parent else None
        self.initial_select = selected
        self.selected_lora = None
        
        # 数据结构
        self.folder_structure = defaultdict(dict) 
        self._process_loras()
        
        self._init_ui()
        
    def _process_loras(self):
        temp_structure = defaultdict(list)
        for path in self.all_loras:
            folder = os.path.dirname(path)
            if not folder: folder = "根目录"
            temp_structure[folder].append(path)
            
        self.processed_data = {} 
        for folder, paths in temp_structure.items():
            groups = {} 
            for path in paths:
                variant = LoraVariant(path)
                base = variant.clean_name
                if len(base) < 2: 
                    base = variant.filename
                    
                if base not in groups:
                    groups[base] = LoraGroup(base)
                    # 检查是否已置顶
                    if base in self.pinned_loras:
                        groups[base].is_pinned = True
                groups[base].add_variant(variant)
            
            group_list = list(groups.values())
            group_list.sort(key=lambda x: x.base_name.lower())
            self.processed_data[folder] = group_list

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        
        # Top Header - 极简风格
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: palette(window); border-bottom: 1px solid palette(midlight);")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 0, 15, 0)
        
        title_box = QHBoxLayout()
        # 移除大图标
        title = QLabel("LoRA 模型库")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: palette(text);")
        title_box.addWidget(title)
        
        header_layout.addLayout(title_box)
        header_layout.addStretch()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(200)
        # 移除圆角等强设计感样式
        self.search_input.setStyleSheet("background-color: palette(base);")
        self.search_input.textChanged.connect(self._on_search)
        header_layout.addWidget(self.search_input)
        
        layout.addWidget(header)
        
        # Main Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background-color: palette(midlight); }")
        
        # Left: Sidebar (Tree)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(200)
        # 移除自定义 Tree 样式，使用默认
        self.tree.setStyleSheet("QTreeWidget { border: none; }")
        self.tree.currentItemChanged.connect(self._on_folder_selected)
        splitter.addWidget(self.tree)
        
        # Right: Content (Scroll -> FlowLayout)
        right_panel = QWidget()
        # 移除自定义背景色
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0,0,0,0)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff) 
        
        self.flow_container = QWidget()
        # 移除 FlowLayout，改用标准的网格布局逻辑
        self.content_layout = QGridLayout(self.flow_container)
        self.content_layout.setContentsMargins(15, 15, 15, 15)
        self.content_layout.setSpacing(15)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        self.scroll.setWidget(self.flow_container)
        right_layout.addWidget(self.scroll)
        
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
        
        self.scroll.viewport().installEventFilter(self) # 监听尺寸变化以重新排版
        self._populate_tree()

    def eventFilter(self, source, event):
        if source == self.scroll.viewport() and event.type() == event.Type.Resize:
            self._update_grid_layout()
        return super().eventFilter(source, event)

    def _update_grid_layout(self):
        """响应式更新网格布局"""
        width = self.scroll.viewport().width()
        if width < 100: return
        
        # 统计有效组件
        widgets = []
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if item and item.widget():
                widgets.append(item.widget())
        
        if not widgets: return

        card_min_width = 240
        spacing = self.content_layout.spacing()
        margin = self.content_layout.contentsMargins().left() + self.content_layout.contentsMargins().right()
        
        # 计算每行能放多少个
        cols = max(1, (width - margin + spacing) // (card_min_width + spacing))
        
        # 重新分布现有卡片 (不用 remove，直接 add 会移动位置)
        for i, wid in enumerate(widgets):
            row = i // cols
            col = i % cols
            self.content_layout.addWidget(wid, row, col)
        
    def _populate_tree(self):
        self.tree.clear()
        
        root_icon = self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon)
        
        all_item = QTreeWidgetItem(self.tree)
        all_item.setText(0, "全部模型")
        all_item.setData(0, Qt.ItemDataRole.UserRole, "__all__")
        all_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DriveHDIcon))
        
        sorted_folders = sorted(self.processed_data.keys())
        
        for folder in sorted_folders:
            item = QTreeWidgetItem(self.tree)
            display_name = folder
            if folder == "根目录": display_name = "未分类"
            if "/" in display_name or "\\" in display_name:
                display_name = os.path.basename(display_name)
            
            item.setText(0, display_name)
            item.setToolTip(0, folder)
            item.setData(0, Qt.ItemDataRole.UserRole, folder)
            item.setIcon(0, root_icon)
            
        self.tree.expandAll()
        self.tree.setCurrentItem(all_item)
        
    def _on_folder_selected(self, current, previous):
        if not current: return
        folder = current.data(0, Qt.ItemDataRole.UserRole)
        self._display_groups(folder)
        
    def _display_groups(self, folder, filter_text=""):
        # 清空网格布局
        while self.content_layout.count():
            child = self.content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            
        target_groups = []
        if folder == "__all__":
            # 使用 set 去重（防止同一 LoRA 出现在多个文件夹时重复显示）
            seen_base_names = set()
            for groups in self.processed_data.values():
                for g in groups:
                    if g.base_name not in seen_base_names:
                        target_groups.append(g)
                        seen_base_names.add(g.base_name)
        else:
            target_groups = self.processed_data.get(folder, [])
            
        filtered_groups = []
        for g in target_groups:
            if not filter_text or filter_text.lower() in g.base_name.lower():
                filtered_groups.append(g)
                
        # 排序：优先置顶，然后按字母顺序
        filtered_groups.sort(key=lambda x: (not x.is_pinned, x.base_name.lower()))
                
        # 渲染
        for group in filtered_groups:
            card = LoraCard(group)
            if card:
                card.selected.connect(self._on_lora_selected)
                card.pinned_changed.connect(lambda _, g=group: self._on_pin_changed(g))
                self.content_layout.addWidget(card)
         
        self._update_grid_layout()
        # 触发重绘
        self.flow_container.adjustSize()

    def _on_pin_changed(self, group):
        """处理置顶状态改变"""
        if group.is_pinned:
            if group.base_name not in self.pinned_loras:
                self.pinned_loras.append(group.base_name)
        else:
            if group.base_name in self.pinned_loras:
                self.pinned_loras.remove(group.base_name)
        
        # 保存设置
        self.settings.setValue("pinned_loras", self.pinned_loras)
        self.settings.sync()
        
        # 重新刷新当前视图以更新位置
        current_folder = "__all__"
        current_item = self.tree.currentItem()
        if current_item:
            current_folder = current_item.data(0, Qt.ItemDataRole.UserRole)
        
        # 记录滚动条位置
        vbar = self.scroll.verticalScrollBar()
        old_val = vbar.value()
        
        self._display_groups(current_folder, self.search_input.text())
        
        # 恢复滚动位置 (稍微延迟一下等待布局更新)
        QTimer.singleShot(10, lambda: vbar.setValue(old_val))

    def _on_search(self, text):
        current_item = self.tree.currentItem()
        # 搜索时全库搜索还是当前文件夹？用户习惯全库搜索
        # 如果搜索框有文字，暂时切换到 "__all__" 模式显示，或者保持当前文件夹？
        # 全库搜索更符合直觉
        folder = "__all__" if text else (current_item.data(0, Qt.ItemDataRole.UserRole) if current_item else "__all__")
        self._display_groups(folder, text)
        
    def _on_lora_selected(self, full_path):
        self.selected_lora = full_path
        self.accept()

