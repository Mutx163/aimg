import os
from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtWidgets import QMessageBox, QMainWindow

from send2trash import send2trash
from src.core.loader import ImageLoaderThread

class FileController(QObject):
    """
    负责处理文件操作：加载文件夹、删除图片、监控新文件
    """
    def __init__(self, main_window: QMainWindow):
        super().__init__()
        self.main = main_window
        self.loader_thread = None

    def load_folder(self, folder: str) -> None:
        """扫描文件夹并加载现有图片 (异步)"""
        self.main.thumbnail_list.clear_list()
        self.main.viewer.clear_view()
        self.main.param_panel.clear_info()
        self.main.statusBar().showMessage(f"正在加载: {folder}...")
        self.main._is_scanning = True # 开启扫描锁
        
        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.stop()
            self.loader_thread.wait()
            
        self.loader_thread = ImageLoaderThread(folder, self.main.db_manager, self.main.thumb_cache)
        self.loader_thread.image_thumb_ready.connect(self._on_loader_image_ready)
        self.loader_thread.image_found.connect(self._on_loader_image_found)
        self.loader_thread.finished_loading.connect(self._on_loader_finished)
        self.loader_thread.start()

    def _on_loader_image_ready(self, path, thumb):
        # 检查是否是第一张图片（即最新的一张）
        is_first = self.main.thumbnail_list.count() == 0
        
        # 线程回调：添加带缩略图的图片
        self.main.thumbnail_list.add_image(path, thumbnail=thumb)
        
        # 如果是第一张，自动选中并显示
        if is_first:
            self.main.thumbnail_list.setCurrentRow(0)
            self.main.on_image_selected(path)
            
        # 增量更新状态栏进度
        count = self.main.thumbnail_list.count()
        if count % 100 == 0:
            self.main.statusBar().showMessage(f"正在加载: {count} 张图片...")

    def _on_loader_image_found(self, path):
        # 线程回调：添加单张图片 (无缩略图)
        self.main.thumbnail_list.add_image(path)
        
    def _on_loader_finished(self):
        # 释放扫描锁
        self.main._is_scanning = False
        self.main.statusBar().showMessage(f"加载完成，共 {self.main.thumbnail_list.count()} 张图片", 5000)
        
        # 刷新模型浏览器数据
        self.refresh_model_explorer()
        # 刷新历史参数 (分辨率/采样器)
        self.main.refresh_historical_params()
        # 尝试自动选中已有的第一张（如果列表不为空）
        if self.main.thumbnail_list.count() > 0:
             pass

    def refresh_model_explorer(self):
        """从数据库读取最新的模型和 LoRA 统计信息"""
        if not self.main.current_folder: return
        models = self.main.db_manager.get_unique_models(self.main.current_folder)
        loras = self.main.db_manager.get_unique_loras(self.main.current_folder)
        self.main.model_explorer.update_models(models, loras)
        if hasattr(self.main, "param_panel"):
            self.main.param_panel.refresh_lora_options()

    def delete_current_image(self) -> None:
        """删除当前选中的图片"""
        idx = self.main.thumbnail_list.currentIndex()
        if not idx.isValid():
            return
            
        row = idx.row()
        path = self.main.thumbnail_list.image_model.get_path(row)
        
        # 确认对话框
        confirm = self.main.settings.value("confirm_delete", True, type=bool)
        if confirm:
            ret = QMessageBox.question(self.main, "确认删除", f"确定要将图片移至回收站吗？\n{os.path.basename(path)}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
        
        try:
            # FIX: Windows API (SHFileOperation) 对路径分隔符非常敏感
            safe_path = os.path.normpath(os.path.abspath(path))
            send2trash(safe_path)
            
            # 从模型中移除
            self.main.thumbnail_list.image_model.beginRemoveRows(idx.parent(), row, row)
            self.main.thumbnail_list.image_model.image_data.pop(row)
            self.main.thumbnail_list.image_model.endRemoveRows()
            
            self.main.statusBar().showMessage(f"已删除: {os.path.basename(path)}")
            
            # 自动选中下一张 (如果有)
            if self.main.thumbnail_list.count() > 0:
                next_row = min(row, self.main.thumbnail_list.count() - 1)
                self.main.thumbnail_list.setCurrentRow(next_row)
                
                # 重新加载新选中的图片
                next_path = self.main.thumbnail_list.image_model.get_path(next_row)
                self.main.on_image_selected(next_path)
            else:
                self.main.viewer.scene.clear()
                self.main.param_panel.clear_info()
                
        except Exception as e:
            QMessageBox.critical(self.main, "删除失败", str(e))

    def on_new_image_detected(self, path: str) -> None:
        """Watcher 信号回调：新图片生成"""
        print(f"[新图片] 检测到: {path}")
        self.main.statusBar().showMessage(f"新图片 detected: {os.path.basename(path)}")
        
        # 延迟加载，等待文件写入完成
        QTimer.singleShot(500, lambda: self._load_new_image_with_retry(path, retries=3))

    def _load_new_image_with_retry(self, path: str, retries: int = 3) -> None:
        """延迟重试加载新图片，处理文件未完全写入的情况"""
        try:
            from PyQt6.QtGui import QImage
            img = QImage(path)
            # print(f"[新图片] QImage 加载: isNull={img.isNull()}, size={img.size()}")
            
            if not img.isNull():
                thumb = img.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, 
                                  Qt.TransformationMode.FastTransformation)
                # print(f"[新图片] 缩略图生成成功: {thumb.size()}")
                # 立即将图片存入数据库，防止重置或搜索时由于未入库而消失
                from src.core.metadata import MetadataParser
                meta = MetadataParser.parse_image(path)
                if meta:
                    self.main.db_manager.add_image(path, meta)
                
                self.main.thumbnail_list.add_image(path, index=0, thumbnail=thumb)
                self.main.thumbnail_list.setCurrentRow(0) # 明确选中第一张图片，确保高亮同步
                
                # 刷新模型浏览器，确保新生成图片使用的 Model/LoRA 逻辑立即可用
                self.refresh_model_explorer()
                # 刷新历史参数，确保新分辨率/采样器立即可见
                self.main.refresh_historical_params()
                
                # 自动查看最新的
                self.main.on_image_selected(path)
            else:
                # 图片加载失败，可能文件还在写入中
                if retries > 0:
                    print(f"[新图片] 加载失败，{retries} 次重试剩余，等待 800ms...")
                    QTimer.singleShot(800, lambda: self._load_new_image_with_retry(path, retries - 1))
                else:
                    print(f"[新图片] 多次重试后仍失败，使用占位符")
                    self.main.thumbnail_list.add_image(path, index=0)
                    self.main.thumbnail_list.setCurrentRow(0)
                    self.main.on_image_selected(path)
        except Exception as e:
            print(f"[新图片] 缩略图生成失败: {e}")
            if retries > 0:
                QTimer.singleShot(800, lambda: self._load_new_image_with_retry(path, retries - 1))
            else:
                # import traceback
                # traceback.print_exc()
                self.main.thumbnail_list.add_image(path, index=0)
                self.main.thumbnail_list.setCurrentRow(0)
                self.main.on_image_selected(path)
