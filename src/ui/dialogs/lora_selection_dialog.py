import json
import os
import re
import time
from collections import defaultdict

from PyQt6.QtCore import QSettings, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


def normalize_lora_key(path: str) -> str:
    return (path or "").replace("\\", "/").strip().lower()


class LoraVariant:
    def __init__(self, full_path):
        self.full_path = full_path
        self.normalized_key = normalize_lora_key(full_path)
        self.filename = os.path.basename(full_path)
        self.clean_name, self.step_count, self.version = self._parse_info(self.filename)

    def _parse_info(self, filename):
        name_no_ext = os.path.splitext(filename)[0]

        step_count = None
        step_match = re.search(r"[-_](\d+)(?:steps?|k)?(?=\.|_|$)", name_no_ext, re.IGNORECASE)
        if step_match:
            try:
                raw_num = step_match.group(1)
                count = int(raw_num)
                if count >= 100:
                    step_count = count * 1000 if "k" in step_match.group(0).lower() else count
            except Exception:
                pass

        version = None
        ver_match = re.search(r"[-_]v?(\d+(?:\.\d+)?)", name_no_ext, re.IGNORECASE)
        if ver_match:
            version = ver_match.group(1)

        clean_name = name_no_ext
        if step_match:
            clean_name = clean_name.replace(step_match.group(0), "")
        if ver_match and (not step_match or ver_match.group(0) not in step_match.group(0)):
            clean_name = clean_name.replace(ver_match.group(0), "")

        clean_name = re.sub(r"[-_](fp16|bf16|safetensors|ckpt|pt)", "", clean_name, flags=re.IGNORECASE)
        clean_name = clean_name.strip(" -_")
        return clean_name, step_count, version


class LoraGroup:
    def __init__(self, base_name):
        self.base_name = base_name
        self.variants = []
        self.is_pinned = False

    def add_variant(self, variant: LoraVariant):
        self.variants.append(variant)
        self.variants.sort(key=lambda x: (x.step_count or 0, float(x.version or 0)), reverse=True)


class NoScrollComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class LoraCard(QFrame):
    selected = pyqtSignal(str, dict)
    pinned_changed = pyqtSignal(bool)
    profile_changed = pyqtSignal(str, dict)

    def __init__(self, group: LoraGroup, profile_lookup, parent=None):
        super().__init__(parent)
        self.group = group
        self._profile_lookup = profile_lookup
        self._loading_profile = False

        self.setObjectName("LoraCard")
        self.setMinimumWidth(230)
        self.setMaximumWidth(480)
        self.setStyleSheet(
            """
            QFrame#LoraCard {
                background-color: palette(window);
                border: 1px solid palette(midlight);
                border-radius: 6px;
            }
            QFrame#LoraCard:hover {
                border: 1px solid palette(highlight);
                background-color: palette(base);
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)

        title = QLabel(group.base_name)
        title.setStyleSheet("font-weight: bold; color: palette(text);")
        font_metrics = title.fontMetrics()
        title.setText(font_metrics.elidedText(group.base_name, Qt.TextElideMode.ElideRight, 170))
        title.setToolTip(group.base_name)
        header_layout.addWidget(title, 1)

        self.pin_btn = QPushButton("置顶")
        self.pin_btn.setFixedSize(40, 20)
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(group.is_pinned)
        self.pin_btn.clicked.connect(self._on_pin_clicked)
        header_layout.addWidget(self.pin_btn)

        if len(group.variants) > 1:
            badge = QLabel(str(len(group.variants)))
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(20, 20)
            badge.setStyleSheet(
                "background-color: palette(mid); color: palette(window-text); border-radius: 10px; font-weight: bold;"
            )
            badge.setToolTip(f"包含 {len(group.variants)} 个版本")
            header_layout.addWidget(badge)

        layout.addLayout(header_layout)
        self._apply_pin_style()

        self.variant_combo = NoScrollComboBox()
        self.variant_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        if len(group.variants) > 1:
            for v in group.variants:
                parts = []
                if v.step_count:
                    parts.append(f"{v.step_count}步")
                if v.version:
                    parts.append(f"v{v.version}")
                label = " ".join(parts) if parts else "基础版"
                if label == "基础版":
                    label = v.filename[-15:]
                self.variant_combo.addItem(label, v.full_path)
                self.variant_combo.setItemData(self.variant_combo.count() - 1, v.filename, Qt.ItemDataRole.ToolTipRole)
            layout.addWidget(self.variant_combo)
        else:
            single = group.variants[0]
            self.variant_combo.addItem(single.filename, single.full_path)
            self.variant_combo.hide()
            lbl = QLabel(single.filename)
            lbl.setStyleSheet("color: palette(mid);")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)

        self.edit_btn = QPushButton("编辑")
        self.edit_btn.setCheckable(True)
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_btn.setFixedHeight(24)
        self.edit_btn.toggled.connect(self._on_toggle_editor)
        actions_layout.addWidget(self.edit_btn)

        actions_layout.addStretch()

        self.select_btn = QPushButton("使用")
        self.select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_btn.setFixedHeight(24)
        self.select_btn.clicked.connect(self._on_select_clicked)
        actions_layout.addWidget(self.select_btn)

        layout.addLayout(actions_layout)

        self.editor_frame = QFrame()
        self.editor_frame.setStyleSheet("QFrame { border-top: 1px solid palette(midlight); }")
        editor_layout = QVBoxLayout(self.editor_frame)
        editor_layout.setContentsMargins(0, 8, 0, 0)
        editor_layout.setSpacing(6)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("备注（用于管理与搜索）")
        editor_layout.addWidget(self.note_edit)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("LoRA 提示词（生成时可自动拼接）")
        self.prompt_edit.setFixedHeight(54)
        editor_layout.addWidget(self.prompt_edit)

        self.auto_prompt_check = QCheckBox("生成时自动使用此 LoRA 提示词")
        self.auto_prompt_check.setChecked(True)
        editor_layout.addWidget(self.auto_prompt_check)

        layout.addWidget(self.editor_frame)
        self.editor_frame.setVisible(False)

        self.note_edit.textChanged.connect(self._emit_profile_changed)
        self.prompt_edit.textChanged.connect(self._emit_profile_changed)
        self.auto_prompt_check.toggled.connect(self._emit_profile_changed)
        self.variant_combo.currentIndexChanged.connect(self._on_variant_changed)

        self._load_profile_to_editor()

    def _apply_pin_style(self):
        if self.group.is_pinned:
            self.pin_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: palette(highlight);
                    color: white;
                    border: 1px solid palette(highlight);
                    border-radius: 3px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: palette(midlight); }
                """
            )
            self.pin_btn.setToolTip("取消置顶")
        else:
            self.pin_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: transparent;
                    color: palette(mid);
                    border: 1px solid palette(mid);
                    border-radius: 3px;
                    font-size: 10px;
                }
                QPushButton:hover { border-color: palette(highlight); color: palette(highlight); }
                """
            )
            self.pin_btn.setToolTip("置顶此模型")

    def _current_path(self):
        return self.variant_combo.currentData() if self.variant_combo.count() else ""

    def _current_key(self):
        return normalize_lora_key(self._current_path())

    def _profile_defaults(self):
        return {
            "note": "",
            "prompt": "",
            "auto_use_prompt": True,
        }

    def _normalize_profile(self, profile):
        data = self._profile_defaults()
        if isinstance(profile, dict):
            data["note"] = str(profile.get("note", "") or "").strip()
            data["prompt"] = str(profile.get("prompt", "") or "").strip()
            data["auto_use_prompt"] = bool(profile.get("auto_use_prompt", True))
        return data

    def _load_profile_to_editor(self):
        self._loading_profile = True
        profile = self._normalize_profile(self._profile_lookup(self._current_key()))
        self.note_edit.setText(profile["note"])
        self.prompt_edit.setPlainText(profile["prompt"])
        self.auto_prompt_check.setChecked(profile["auto_use_prompt"])
        self._loading_profile = False

    def _collect_profile_from_editor(self):
        return self._normalize_profile(
            {
                "note": self.note_edit.text(),
                "prompt": self.prompt_edit.toPlainText(),
                "auto_use_prompt": self.auto_prompt_check.isChecked(),
            }
        )

    def _emit_profile_changed(self):
        if self._loading_profile:
            return
        key = self._current_key()
        if not key:
            return
        self.profile_changed.emit(key, self._collect_profile_from_editor())

    def _on_pin_clicked(self):
        self.group.is_pinned = self.pin_btn.isChecked()
        self._apply_pin_style()
        self.pinned_changed.emit(self.group.is_pinned)

    def _on_toggle_editor(self, checked):
        self.editor_frame.setVisible(checked)
        self.edit_btn.setText("收起" if checked else "编辑")

    def _on_variant_changed(self, _index):
        self._load_profile_to_editor()

    def _on_select_clicked(self):
        full_path = self._current_path()
        if full_path:
            self.selected.emit(full_path, self._collect_profile_from_editor())


class LoraSelectionDialog(QDialog):
    PROFILE_SETTINGS_KEY = "lora_profiles_v1"

    def __init__(self, all_loras, parent=None):
        super().__init__(parent)
        self.settings = QSettings("ComfyUIImageManager", "Settings")
        self.pinned_loras = self.settings.value("pinned_loras", [], type=list)
        self.lora_profiles = self._load_profiles()
        self.selected_lora = None
        self.selected_lora_profile = {}
        self.all_loras = all_loras

        self._profile_save_timer = QTimer(self)
        self._profile_save_timer.setSingleShot(True)
        self._profile_save_timer.timeout.connect(self._flush_profiles)

        self.setWindowTitle("选择 LoRA 模型")
        self.resize(920, 620)
        self._process_loras()
        self._init_ui()

    def _load_profiles(self):
        raw = self.settings.value(self.PROFILE_SETTINGS_KEY, "{}", type=str)
        data = {}
        try:
            if isinstance(raw, str):
                data = json.loads(raw) if raw.strip() else {}
            elif isinstance(raw, dict):
                data = raw
        except Exception:
            data = {}
        if not isinstance(data, dict):
            return {}
        cleaned = {}
        for k, v in data.items():
            key = normalize_lora_key(str(k))
            if not key or not isinstance(v, dict):
                continue
            cleaned[key] = v
        return cleaned

    def _get_profile(self, key: str):
        return self.lora_profiles.get(normalize_lora_key(key), {})

    def _queue_profile_update(self, key: str, profile: dict):
        norm_key = normalize_lora_key(key)
        if not norm_key:
            return
        data = {
            "note": str(profile.get("note", "") or "").strip(),
            "prompt": str(profile.get("prompt", "") or "").strip(),
            "auto_use_prompt": bool(profile.get("auto_use_prompt", True)),
            "updated_at": int(time.time()),
        }
        self.lora_profiles[norm_key] = data
        self._profile_save_timer.start(300)

    def _flush_profiles(self):
        try:
            self.settings.setValue(self.PROFILE_SETTINGS_KEY, json.dumps(self.lora_profiles, ensure_ascii=False))
            self.settings.sync()
        except Exception:
            pass

    def done(self, r):
        self._flush_profiles()
        super().done(r)

    def _process_loras(self):
        temp_structure = defaultdict(list)
        for path in self.all_loras:
            folder = os.path.dirname(path) or "根目录"
            temp_structure[folder].append(path)

        self.processed_data = {}
        for folder, paths in temp_structure.items():
            groups = {}
            for path in paths:
                variant = LoraVariant(path)
                base = variant.clean_name if len(variant.clean_name) >= 2 else variant.filename
                if base not in groups:
                    groups[base] = LoraGroup(base)
                    if base in self.pinned_loras:
                        groups[base].is_pinned = True
                groups[base].add_variant(variant)
            group_list = list(groups.values())
            group_list.sort(key=lambda x: x.base_name.lower())
            self.processed_data[folder] = group_list

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: palette(window); border-bottom: 1px solid palette(midlight);")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 0, 15, 0)
        header_layout.addWidget(QLabel("LoRA 模型库"))
        header_layout.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索名称/备注...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(240)
        self.search_input.textChanged.connect(self._on_search)
        header_layout.addWidget(self.search_input)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background-color: palette(midlight); }")

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(210)
        self.tree.setStyleSheet("QTreeWidget { border: none; }")
        self.tree.currentItemChanged.connect(self._on_folder_selected)
        splitter.addWidget(self.tree)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.flow_container = QWidget()
        self.content_layout = QGridLayout(self.flow_container)
        self.content_layout.setContentsMargins(15, 15, 15, 15)
        self.content_layout.setSpacing(15)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.flow_container)
        right_layout.addWidget(self.scroll)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        self.scroll.viewport().installEventFilter(self)
        self._populate_tree()

    def eventFilter(self, source, event):
        if source == self.scroll.viewport() and event.type() == event.Type.Resize:
            self._update_grid_layout()
        return super().eventFilter(source, event)

    def _update_grid_layout(self):
        width = self.scroll.viewport().width()
        if width < 100:
            return
        widgets = []
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if item and item.widget():
                widgets.append(item.widget())
        if not widgets:
            return
        card_min_width = 260
        spacing = self.content_layout.spacing()
        margin = self.content_layout.contentsMargins().left() + self.content_layout.contentsMargins().right()
        cols = max(1, (width - margin + spacing) // (card_min_width + spacing))
        for i, wid in enumerate(widgets):
            self.content_layout.addWidget(wid, i // cols, i % cols)

    def _populate_tree(self):
        self.tree.clear()
        root_icon = self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon)

        all_item = QTreeWidgetItem(self.tree)
        all_item.setText(0, "全部模型")
        all_item.setData(0, Qt.ItemDataRole.UserRole, "__all__")
        all_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DriveHDIcon))

        for folder in sorted(self.processed_data.keys()):
            item = QTreeWidgetItem(self.tree)
            display_name = "未分类" if folder == "根目录" else os.path.basename(folder.replace("\\", "/")) or folder
            item.setText(0, display_name)
            item.setToolTip(0, folder)
            item.setData(0, Qt.ItemDataRole.UserRole, folder)
            item.setIcon(0, root_icon)

        self.tree.expandAll()
        self.tree.setCurrentItem(all_item)

    def _group_matches_filter(self, group: LoraGroup, filter_text: str):
        if not filter_text:
            return True
        q = filter_text.lower().strip()
        if q in group.base_name.lower():
            return True
        for v in group.variants:
            if q in v.filename.lower():
                return True
            note = str(self._get_profile(v.normalized_key).get("note", "") or "").lower()
            if note and q in note:
                return True
        return False

    def _on_folder_selected(self, current, _previous):
        if not current:
            return
        self._display_groups(current.data(0, Qt.ItemDataRole.UserRole))

    def _display_groups(self, folder, filter_text=""):
        while self.content_layout.count():
            child = self.content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if folder == "__all__":
            seen = set()
            target_groups = []
            for groups in self.processed_data.values():
                for group in groups:
                    if group.base_name not in seen:
                        target_groups.append(group)
                        seen.add(group.base_name)
        else:
            target_groups = self.processed_data.get(folder, [])

        filtered_groups = [g for g in target_groups if self._group_matches_filter(g, filter_text)]
        filtered_groups.sort(key=lambda x: (not x.is_pinned, x.base_name.lower()))

        for group in filtered_groups:
            card = LoraCard(group, self._get_profile)
            card.selected.connect(self._on_lora_selected)
            card.pinned_changed.connect(lambda _, g=group: self._on_pin_changed(g))
            card.profile_changed.connect(self._queue_profile_update)
            self.content_layout.addWidget(card)

        self._update_grid_layout()
        self.flow_container.adjustSize()

    def _on_pin_changed(self, group):
        if group.is_pinned:
            if group.base_name not in self.pinned_loras:
                self.pinned_loras.append(group.base_name)
        else:
            if group.base_name in self.pinned_loras:
                self.pinned_loras.remove(group.base_name)
        self.settings.setValue("pinned_loras", self.pinned_loras)
        self.settings.sync()

        current_item = self.tree.currentItem()
        current_folder = current_item.data(0, Qt.ItemDataRole.UserRole) if current_item else "__all__"
        vbar = self.scroll.verticalScrollBar()
        old_val = vbar.value()
        self._display_groups(current_folder, self.search_input.text())
        QTimer.singleShot(10, lambda: vbar.setValue(old_val))

    def _on_search(self, text):
        current_item = self.tree.currentItem()
        folder = "__all__" if text else (current_item.data(0, Qt.ItemDataRole.UserRole) if current_item else "__all__")
        self._display_groups(folder, text)

    def _on_lora_selected(self, full_path, profile):
        self.selected_lora = full_path
        self.selected_lora_profile = {
            "note": str(profile.get("note", "") or "").strip(),
            "prompt": str(profile.get("prompt", "") or "").strip(),
            "auto_use_prompt": bool(profile.get("auto_use_prompt", True)),
        }
        self._queue_profile_update(normalize_lora_key(full_path), self.selected_lora_profile)
        self.accept()
