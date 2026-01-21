import os
import time
from PyQt6.QtGui import QImage
from PyQt6.QtCore import QThread, pyqtSignal, Qt

from src.core.metadata import MetadataParser

class ImageLoaderThread(QThread):
    """
    后台线程：扫描文件夹并逐个返回图片路径。
    """
    image_found = pyqtSignal(str) # 仅发送路径 (旧)
    image_thumb_ready = pyqtSignal(str, QImage) # 发送路径和预生成的缩略图
    finished_loading = pyqtSignal() # 全部扫描完成

    def __init__(self, folder_path, db_manager=None):
        super().__init__()
        self.folder_path = folder_path
        self.db_manager = db_manager
        self._is_running = True

    def run(self):
        start_time = time.time()
        print(f"[Loader] 开始扫描文件夹: {self.folder_path}")
        
        extensions = {'.png', '.jpg', '.jpeg', '.webp'}
        files = []
        
        try:
            # 第一阶段：快速获取所有文件列表
            with os.scandir(self.folder_path) as it:
                for entry in it:
                    if not self._is_running:
                        break
                    if entry.is_file():
                        _, ext = os.path.splitext(entry.name)
                        if ext.lower() in extensions:
                            files.append(entry.path)
            
            scan_time = time.time()
            print(f"[Loader] 文件扫描完成，找到 {len(files)} 张图片，耗时: {scan_time - start_time:.3f} 秒")

            # 按时间排序 (最新在前)，时间相同时按文件名排序确保稳定性
            if self._is_running:
                files.sort(key=lambda x: (-os.path.getmtime(x), os.path.basename(x)))
                
            sort_time = time.time()
            print(f"[Loader] 排序完成，耗时: {sort_time - scan_time:.3f} 秒")
                
            # 第二阶段：逐个发送并生成缩略图
            for i, f in enumerate(files):
                if not self._is_running:
                    break
                
                try:
                    # 1. 解析并记录到数据库 (可选，如果数据库里已经有了可以跳过以提速，但先实现基本逻辑)
                    if self.db_manager:
                        meta = MetadataParser.parse_image(f)
                        if meta:
                            self.db_manager.add_image(f, meta)

                    # 2. 在后台线程加载并缩放图片
                    img = QImage(f)
                    if not img.isNull():
                        thumb = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.image_thumb_ready.emit(f, thumb)
                    else:
                        self.image_found.emit(f)
                except Exception as e:
                    print(f"[Loader] Thumb gen error for {f}: {e}")
                    self.image_found.emit(f)
                
        except Exception as e:
            print(f"[Loader] Error: {e}")
            
        total_time = time.time() - start_time
        print(f"[Loader] 全部加载完成，总耗时: {total_time:.3f} 秒")
        self.finished_loading.emit()

    def stop(self):
        self._is_running = False
