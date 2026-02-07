from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from src.ui.widgets.image_viewer import ImageViewer


class ComparisonView(QWidget):
    navigate_request = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(6)
        self.layout.addWidget(self.splitter, 0, Qt.AlignmentFlag.AlignCenter)

        self.viewer_left = ImageViewer()
        self.viewer_right = ImageViewer()
        self.splitter.addWidget(self.viewer_left)
        self.splitter.addWidget(self.viewer_right)

        self.viewer_left.view_changed.connect(self.viewer_right.sync_view)
        self.viewer_right.view_changed.connect(self.viewer_left.sync_view)
        self.viewer_left.navigate_request.connect(self.navigate_request.emit)
        self.viewer_right.navigate_request.connect(self.navigate_request.emit)

        # single image width/height ratio used by each compare panel
        self._reference_aspect_ratio = 1.0
        self._sync_retry_count = 0

    def set_reference_aspect_ratio(self, ratio: float | None):
        if ratio is None:
            return
        try:
            value = float(ratio)
        except Exception:
            return
        if value <= 0:
            return
        self._reference_aspect_ratio = max(0.1, min(value, 10.0))
        self._apply_target_ratio_geometry()
        self._fit_both_viewers()

    def _fit_both_viewers(self):
        self.viewer_left.fit_to_window()
        self.viewer_right.fit_to_window()

    def _apply_target_ratio_geometry(self):
        rect = self.contentsRect()
        avail_w = max(2, int(rect.width()))
        avail_h = max(2, int(rect.height()))
        ratio = max(0.1, float(self._reference_aspect_ratio))
        handle_w = max(0, int(self.splitter.handleWidth()))

        # total compare area width = left + handle + right = 2 * ratio * h + handle
        full_w_for_h = int(round(2.0 * ratio * avail_h + handle_w))
        if full_w_for_h <= avail_w:
            target_h = avail_h
            target_w = full_w_for_h
        else:
            target_w = avail_w
            target_h = int(round((target_w - handle_w) / (2.0 * ratio)))
            target_h = max(2, min(target_h, avail_h))
            target_w = max(2, int(round(2.0 * ratio * target_h + handle_w)))

        self.splitter.setFixedSize(target_w, target_h)

        each_w = max(1, int(round(ratio * target_h)))
        left_w = each_w
        right_w = max(1, target_w - handle_w - left_w)
        self.splitter.setSizes([left_w, right_w])

    def load_images(self, left_path, right_path):
        self._apply_target_ratio_geometry()

        self.viewer_left.auto_fit = True
        self.viewer_right.auto_fit = True
        self.viewer_left.resetTransform()
        self.viewer_right.resetTransform()
        self.viewer_left.horizontalScrollBar().setValue(0)
        self.viewer_left.verticalScrollBar().setValue(0)
        self.viewer_right.horizontalScrollBar().setValue(0)
        self.viewer_right.verticalScrollBar().setValue(0)

        self.viewer_left.load_image(left_path)
        self.viewer_right.load_image(right_path)

        self._sync_retry_count = 0
        QTimer.singleShot(80, self._sync_after_load)

    def _sync_after_load(self):
        left_ready = not self.viewer_left.pixmap_item.pixmap().isNull()
        right_ready = not self.viewer_right.pixmap_item.pixmap().isNull()

        if not (left_ready and right_ready):
            self._sync_retry_count += 1
            if self._sync_retry_count <= 12:
                QTimer.singleShot(80, self._sync_after_load)
            return

        self._fit_both_viewers()
        self.viewer_right.sync_view(
            self.viewer_left.transform(),
            (
                self.viewer_left.horizontalScrollBar().value(),
                self.viewer_left.verticalScrollBar().value(),
            ),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_target_ratio_geometry()
        if self.viewer_left.auto_fit and self.viewer_right.auto_fit:
            self._fit_both_viewers()

    def clear(self):
        self.viewer_left.clear_view()
        self.viewer_right.clear_view()
