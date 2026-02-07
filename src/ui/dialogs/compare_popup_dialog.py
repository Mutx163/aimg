import os
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.ui.widgets.comparison_view import ComparisonView


class ComparePopupDialog(QDialog):
    """统一对比弹窗：左侧网格，右侧双栏对比。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("对比视图")
        self.resize(1240, 780)

        self._session_meta: Dict[str, Any] = {}
        self._items_by_variant: Dict[str, Dict[str, Any]] = {}
        self._grid_only = False
        self._is_auto_selecting = False
        self._active_pair_variant_ids: List[str] = []
        self._preferred_aspect_ratio: Optional[float] = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.title_label = QLabel("对比会话")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        top.addWidget(self.title_label)
        top.addStretch()

        self.progress_label = QLabel("0/0")
        self.progress_label.setStyleSheet("color: palette(mid);")
        top.addWidget(self.progress_label)

        self.btn_reload = QPushButton("重新加载")
        self.btn_reload.clicked.connect(self._reload_all_icons)
        top.addWidget(self.btn_reload)

        self.btn_export = QPushButton("导出")
        self.btn_export.setEnabled(False)
        self.btn_export.setToolTip("预留导出功能")
        top.addWidget(self.btn_export)
        layout.addLayout(top)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.splitter, 1)

        left_wrap = QWidget()
        left_layout = QVBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.grid_list = QListWidget()
        self.grid_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid_list.setMovement(QListWidget.Movement.Static)
        self.grid_list.setSpacing(8)
        self.grid_list.setIconSize(QSize(132, 132))
        self.grid_list.setGridSize(QSize(160, 196))
        self.grid_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.grid_list.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.grid_list, 1)
        self.splitter.addWidget(left_wrap)

        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.comparison_view = ComparisonView()
        self.comparison_view.viewer_left.viewport().installEventFilter(self)
        self.comparison_view.viewer_right.viewport().installEventFilter(self)
        right_layout.addWidget(self.comparison_view, 1)

        self.caption_widget = QWidget()
        caption_row = QHBoxLayout(self.caption_widget)
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.setSpacing(6)

        self.left_caption_label = QLabel("-")
        self.left_caption_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        self.left_caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_caption_label.setWordWrap(True)
        caption_row.addWidget(self.left_caption_label, 1)

        self.right_caption_label = QLabel("-")
        self.right_caption_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        self.right_caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_caption_label.setWordWrap(True)
        caption_row.addWidget(self.right_caption_label, 1)
        right_layout.addWidget(self.caption_widget)

        self.splitter.addWidget(right_wrap)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([420, 820])

        bottom = QHBoxLayout()
        self.btn_grid_only = QPushButton("仅看网格")
        self.btn_grid_only.clicked.connect(self._toggle_grid_only)
        bottom.addWidget(self.btn_grid_only)

        self.btn_compare_selected = QPushButton("对比选中两张")
        self.btn_compare_selected.clicked.connect(self._compare_selected_two)
        bottom.addWidget(self.btn_compare_selected)

        bottom.addStretch()
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.close)
        bottom.addWidget(self.btn_close)
        layout.addLayout(bottom)

    def set_session(self, session_meta: Dict[str, Any]) -> None:
        self._session_meta = dict(session_meta or {})
        name = self._session_meta.get("name") or "对比会话"
        completed = int(self._session_meta.get("completed_count", 0))
        expected = int(self._session_meta.get("expected_count", 0))
        self.title_label.setText(name)
        self.progress_label.setText(f"{completed}/{expected}")

    def set_preferred_aspect_ratio(self, ratio: Optional[float]) -> None:
        if ratio is None:
            self._preferred_aspect_ratio = None
            return
        try:
            ratio_val = float(ratio)
        except Exception:
            return
        if ratio_val <= 0:
            return
        self._preferred_aspect_ratio = ratio_val
        self.comparison_view.set_reference_aspect_ratio(ratio_val)

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        self.grid_list.clear()
        self._items_by_variant.clear()
        self._active_pair_variant_ids = []
        self._update_captions()
        for item in items or []:
            variant_id = str(item.get("variant_id", ""))
            self.upsert_item(
                variant_id=variant_id,
                status=item.get("status", "queued"),
                path=item.get("path"),
                label=item.get("label"),
                meta=item.get("meta"),
            )
        self._auto_preview_ready_items()

    def upsert_item(
        self,
        variant_id: str,
        status: str,
        path: Optional[str] = None,
        label: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        variant_id = str(variant_id or "")
        if not variant_id:
            return

        record = self._items_by_variant.get(variant_id)
        if record is None:
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, variant_id)
            self.grid_list.addItem(list_item)
            record = {"item": list_item, "variant_id": variant_id}
            self._items_by_variant[variant_id] = record

        if label is not None:
            record["label"] = label
        if path is not None:
            record["path"] = path
        if meta is not None:
            record["meta"] = dict(meta)
        record["status"] = status

        list_item = record["item"]
        display_label = self._display_variant_text(record, variant_id)
        list_item.setText(f"{self._status_prefix(status)} {display_label}")
        list_item.setToolTip(str(record.get("path") or display_label))
        list_item.setIcon(self._icon_for_record(record))

        self._refresh_progress_from_items()
        self._auto_preview_ready_items()

    def open_with_paths(self, paths: List[str], title: str = "手动对比") -> None:
        self.set_session(
            {
                "name": title,
                "expected_count": len(paths or []),
                "completed_count": len(paths or []),
                "mode": "manual",
            }
        )
        self.grid_list.clear()
        self._items_by_variant.clear()
        self._active_pair_variant_ids = []
        self._update_captions()

        for idx, path in enumerate(paths or []):
            self.upsert_item(
                variant_id=f"manual_{idx}",
                status="done",
                path=path,
                label=os.path.basename(path) if path else f"图{idx + 1}",
                meta={"manual": True},
            )

        self._compare_selected_two(auto_select=True, silent=True)
        self.show()
        self.raise_()
        self.activateWindow()

    def _status_prefix(self, status: str) -> str:
        normalized = (status or "").lower()
        if normalized == "done":
            return "[完成]"
        if normalized == "submitted":
            return "[提交]"
        if normalized == "failed":
            return "[失败]"
        return "[排队]"

    def _icon_for_record(self, record: Dict[str, Any]) -> QIcon:
        path = str(record.get("path") or "")
        if path and os.path.exists(path):
            img = QImage(path)
            if not img.isNull():
                pix = QPixmap.fromImage(
                    img.scaled(
                        132,
                        132,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return QIcon(pix)

        placeholder = QPixmap(132, 132)
        placeholder.fill(Qt.GlobalColor.lightGray)
        return QIcon(placeholder)

    def _reload_all_icons(self) -> None:
        for record in self._items_by_variant.values():
            record["item"].setIcon(self._icon_for_record(record))

    def _refresh_progress_from_items(self) -> None:
        expected = max(0, len(self._items_by_variant))
        completed = sum(
            1 for rec in self._items_by_variant.values() if str(rec.get("status")) == "done"
        )
        self.progress_label.setText(f"{completed}/{expected}")
        self._session_meta["expected_count"] = expected
        self._session_meta["completed_count"] = completed

    def _on_selection_changed(self) -> None:
        if self._is_auto_selecting:
            return
        self._compare_selected_two(auto_select=False, silent=True)

    def _selected_variant_ids(self) -> List[str]:
        selected: List[str] = []
        for i in range(self.grid_list.count()):
            item = self.grid_list.item(i)
            if not item.isSelected():
                continue
            variant_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if variant_id:
                selected.append(variant_id)
        return selected

    def _selected_paths(self) -> List[str]:
        paths: List[str] = []
        for variant_id in self._selected_variant_ids():
            rec = self._items_by_variant.get(variant_id, {})
            path = str(rec.get("path") or "")
            if path and os.path.exists(path):
                paths.append(path)
        return paths

    def _display_variant_text(self, record: Dict[str, Any], fallback_variant_id: str) -> str:
        meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
        label = str(record.get("label") or fallback_variant_id)
        if not isinstance(meta, dict):
            return label
        if bool(meta.get("is_baseline", False)):
            return "基线(无LoRA)"

        lora_name = str(meta.get("lora_name") or "")
        lora_weight = meta.get("lora_weight")
        if lora_name and lora_weight not in (None, ""):
            name = os.path.basename(lora_name)
            try:
                weight_txt = f"{float(lora_weight):g}"
            except Exception:
                weight_txt = str(lora_weight)
            return f"{weight_txt} | {name}"
        if lora_name:
            return os.path.basename(lora_name)
        return label

    def _caption_text_for_variant(self, variant_id: str) -> str:
        rec = self._items_by_variant.get(variant_id, {})
        if not rec:
            return "-"
        text = self._display_variant_text(rec, variant_id)
        return text if text else "-"

    def _update_captions(self) -> None:
        if len(self._active_pair_variant_ids) >= 1:
            self.left_caption_label.setText(
                self._caption_text_for_variant(self._active_pair_variant_ids[0])
            )
        else:
            self.left_caption_label.setText("-")
        if len(self._active_pair_variant_ids) >= 2:
            self.right_caption_label.setText(
                self._caption_text_for_variant(self._active_pair_variant_ids[1])
            )
        else:
            self.right_caption_label.setText("-")

    def _path_for_variant(self, variant_id: str) -> str:
        rec = self._items_by_variant.get(variant_id, {})
        return str(rec.get("path") or "")

    def _path_aspect_ratio(self, path: str) -> Optional[float]:
        if not path or not os.path.exists(path):
            return None
        image = QImage(path)
        if image.isNull() or image.height() <= 0:
            return None
        return float(image.width()) / float(image.height())

    def _load_pair_by_variant_ids(self, pair_ids: List[str], silent: bool = False) -> None:
        if len(pair_ids) < 2:
            if not silent:
                QMessageBox.information(self, "提示", "请先选择至少 2 张图片。")
            return
        p1 = self._path_for_variant(pair_ids[0])
        p2 = self._path_for_variant(pair_ids[1])
        if not p1 or not p2:
            if not silent:
                QMessageBox.information(self, "提示", "选中的图片还没有可用路径。")
            return

        if self._preferred_aspect_ratio:
            self.comparison_view.set_reference_aspect_ratio(self._preferred_aspect_ratio)
        else:
            ratio = self._path_aspect_ratio(p1) or self._path_aspect_ratio(p2)
            if ratio:
                self.comparison_view.set_reference_aspect_ratio(ratio)

        self._active_pair_variant_ids = [pair_ids[0], pair_ids[1]]
        self._update_captions()
        self.comparison_view.load_images(p1, p2)

    def _compare_selected_two(self, auto_select: bool = False, silent: bool = False) -> None:
        if auto_select and self.grid_list.count() >= 2 and len(self.grid_list.selectedItems()) < 2:
            self.grid_list.item(0).setSelected(True)
            self.grid_list.item(1).setSelected(True)
        selected_ids = self._selected_variant_ids()
        self._load_pair_by_variant_ids(selected_ids[:2], silent=silent)

    def _toggle_grid_only(self) -> None:
        self._grid_only = not self._grid_only
        self.comparison_view.setVisible(not self._grid_only)
        self.caption_widget.setVisible(not self._grid_only)
        self.btn_grid_only.setText("恢复对比" if self._grid_only else "仅看网格")

    def _ready_variant_ids(self) -> List[str]:
        ready_ids: List[str] = []
        for variant_id, record in self._items_by_variant.items():
            path = str(record.get("path") or "")
            if str(record.get("status")) == "done" and path and os.path.exists(path):
                ready_ids.append(variant_id)
        return ready_ids

    def _set_selected_variant_ids(self, variant_ids: List[str]) -> None:
        target_set = set(variant_ids)
        self._is_auto_selecting = True
        try:
            self.grid_list.blockSignals(True)
            self.grid_list.clearSelection()
            for i in range(self.grid_list.count()):
                item = self.grid_list.item(i)
                item_vid = str(item.data(Qt.ItemDataRole.UserRole) or "")
                if item_vid in target_set:
                    item.setSelected(True)
        finally:
            self.grid_list.blockSignals(False)
            self._is_auto_selecting = False

    def _auto_preview_ready_items(self) -> None:
        selected_paths = self._selected_paths()
        if len(selected_paths) >= 2:
            return

        ready_ids = self._ready_variant_ids()
        if not ready_ids:
            return

        if len(ready_ids) == 1:
            variant_id = ready_ids[0]
            rec = self._items_by_variant.get(variant_id, {})
            path = str(rec.get("path") or "")
            if path and os.path.exists(path):
                self._set_selected_variant_ids([variant_id])
                if self._preferred_aspect_ratio:
                    self.comparison_view.set_reference_aspect_ratio(self._preferred_aspect_ratio)
                else:
                    ratio = self._path_aspect_ratio(path)
                    if ratio:
                        self.comparison_view.set_reference_aspect_ratio(ratio)
                self._active_pair_variant_ids = [variant_id, variant_id]
                self._update_captions()
                self.comparison_view.load_images(path, path)
            return

        first_two = ready_ids[:2]
        self._set_selected_variant_ids(first_two)
        self._load_pair_by_variant_ids(first_two, silent=True)

    def eventFilter(self, source, event):
        if event.type() == QEvent.Type.Wheel:
            left_vp = self.comparison_view.viewer_left.viewport()
            right_vp = self.comparison_view.viewer_right.viewport()
            if source is left_vp or source is right_vp:
                selected_ids = self._selected_variant_ids()
                if len(selected_ids) < 2:
                    return False

                slot = 0 if source is left_vp else 1
                if len(self._active_pair_variant_ids) == 2:
                    active = list(self._active_pair_variant_ids)
                else:
                    active = selected_ids[:2]

                if len(active) < 2:
                    return False
                current_id = active[slot]
                if current_id not in selected_ids:
                    current_id = selected_ids[min(slot, len(selected_ids) - 1)]
                    active[slot] = current_id

                delta = event.angleDelta().y()
                if delta == 0:
                    return True
                step = -1 if delta > 0 else 1

                curr_idx = selected_ids.index(current_id)
                next_idx = (curr_idx + step) % len(selected_ids)
                next_id = selected_ids[next_idx]
                other_id = active[1 - slot]

                if len(selected_ids) == 2 and next_id == other_id:
                    active = [active[1], active[0]]
                else:
                    if next_id == other_id and len(selected_ids) > 2:
                        next_idx = (next_idx + step) % len(selected_ids)
                        next_id = selected_ids[next_idx]
                    active[slot] = next_id

                self._load_pair_by_variant_ids(active[:2], silent=True)
                return True
        return super().eventFilter(source, event)
