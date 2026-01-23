import os
import hashlib
from PyQt6.QtGui import QImage

class ThumbnailCache:
    """
    持久化缩略图缓存，保存为 WebP 格式以平衡体积与速度。
    """
    def __init__(self, cache_dir=".thumbs"):
        # 默认放在文件夹下的 .thumbs 目录，也可以在主程序初始化时指定全局路径
        self.cache_dir = cache_dir
        if not os.path.exists(cache_dir):
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except:
                pass

    def _get_cache_path(self, file_path):
        """为文件生成唯一的缓存路径 (使用 MD5 避免路径冲突)"""
        file_hash = hashlib.md5(file_path.encode('utf-8')).hexdigest()
        # 记录 mtime 确保图片更新时缓存同步刷新
        try:
            mtime = int(os.path.getmtime(file_path))
        except:
            mtime = 0
            
        return os.path.join(self.cache_dir, f"{file_hash}_{mtime}.webp")

    def get_thumbnail(self, file_path):
        """尝试读取缓存"""
        cache_path = self._get_cache_path(file_path)
        if os.path.exists(cache_path):
            img = QImage(cache_path)
            if not img.isNull():
                return img
        return None

    def save_thumbnail(self, file_path, qimage):
        """保存缩略图到缓存 (128x128 限制)"""
        cache_path = self._get_cache_path(file_path)
        
        # 清理旧版本的同一文件的缓存 (可选，但推荐)
        self._cleanup_old_versions(file_path)
        
        # 保存为 WebP
        qimage.save(cache_path, "WEBP")

    def _cleanup_old_versions(self, file_path):
        """删除旧的缓存文件以节省空间"""
        file_hash = hashlib.md5(file_path.encode('utf-8')).hexdigest()
        try:
            for f in os.listdir(self.cache_dir):
                if f.startswith(file_hash):
                    os.remove(os.path.join(self.cache_dir, f))
        except:
            pass
