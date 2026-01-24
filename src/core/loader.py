import os
import time
from PyQt6.QtGui import QImage
from PyQt6.QtCore import QThread, pyqtSignal, Qt

from src.core.metadata import MetadataParser
from src.core.cache import ThumbnailCache

class ImageLoaderThread(QThread):
    """
    后台线程：扫描文件夹并逐个返回图片路径。
    """
    image_found = pyqtSignal(str) # 仅发送路径
    image_thumb_ready = pyqtSignal(str, QImage) # 发送路径和预生成的缩略图
    finished_loading = pyqtSignal() # 全部扫描完成

    def __init__(self, folder_path, db_manager=None, thumb_cache=None):
        super().__init__()
        self.folder_path = folder_path
        self.db_manager = db_manager
        self.thumb_cache = thumb_cache or ThumbnailCache()
        self._is_running = True

    def run(self):
        start_time = time.time()
        print(f"[Loader] 开始扫描文件夹: {self.folder_path}")
        
        extensions = {'.png', '.jpg', '.jpeg', '.webp'}
        files = []
        
        try:
            with os.scandir(self.folder_path) as it:
                for entry in it:
                    if not self._is_running:
                        break
                    if entry.is_file():
                        _, ext = os.path.splitext(entry.name)
                        if ext.lower() in extensions:
                            files.append(entry.path)
            
            if self._is_running:
                files.sort(key=lambda x: (-os.path.getmtime(x), os.path.basename(x)))
                
            for i, f in enumerate(files):
                if not self._is_running:
                    break
                
                try:
                    # 1. 优先尝试从持久化缓存读取缩略图 (极速响应)
                    thumb = self.thumb_cache.get_thumbnail(f)
                    
                    if not thumb:
                        # 缓存缺失，需要加载并生成
                        img = QImage(f)
                        if not img.isNull():
                            # 生成 256px 的缩略图供显示
                            thumb = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, 
                                             Qt.TransformationMode.FastTransformation)
                            # 保存到持久化缓存
                            self.thumb_cache.save_thumbnail(f, thumb)
                        
                    # 2. 解析并记录到数据库
                    if self.db_manager:
                        # TODO: 这里可以优化为批量提交
                        meta = MetadataParser.parse_image(f)
                        if meta:
                            self.db_manager.add_image(f, meta)

                    if thumb:
                        self.image_thumb_ready.emit(f, thumb)
                    else:
                        self.image_found.emit(f)
                        
                except Exception as e:
                    print(f"[Loader] Error processing {f}: {e}")
                    self.image_found.emit(f)
                
        except Exception as e:
            print(f"[Loader] Scan error: {e}")
            
        print(f"[Loader] 完成，耗时: {time.time() - start_time:.3f} 秒")
        self.finished_loading.emit()

    def stop(self):
        self._is_running = False

class SearchThumbnailLoader(QThread):
    """专门为搜索结果异步加载缩略图的微型线程 - V4.2 竞态防护版"""
    # 增加 search_id 参数，防止快速切换筛选时旧线程的回调污染新列表
    thumbnail_ready = pyqtSignal(int, str, QImage, str) # index, path, thumb, search_id
    file_missing = pyqtSignal(str) # 发现文件丢失，请求清理 DB

    def __init__(self, paths, thumb_cache=None, search_id=None):
        super().__init__()
        self.paths = paths
        self.thumb_cache = thumb_cache or ThumbnailCache()
        self.search_id = search_id
        self._is_running = True

    def run(self):
        for i, path in enumerate(self.paths):
            if not self._is_running: break
            
            # V4.3 修复：恢复存在性检查
            # 如果文件被外部删除，必须在此拦截，否则会生成空缩略图占位
            if not os.path.exists(path): 
                print(f"[SearchLoader] File missing: {path}")
                self.file_missing.emit(path) # 通知主线程清理僵尸记录
                continue
            
            try:
                # 优先从缓存读取
                thumb = self.thumb_cache.get_thumbnail(path)
                if not thumb:
                    img = QImage(path)
                    if not img.isNull():
                        thumb = img.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, 
                                          Qt.TransformationMode.FastTransformation)
                        self.thumb_cache.save_thumbnail(path, thumb)
                
                if thumb and self._is_running:
                    self.thumbnail_ready.emit(i, path, thumb, self.search_id)
            except Exception as e:
                print(f"[SearchLoader] Thumb error for {path}: {e}")

    def stop(self):
        self._is_running = False
