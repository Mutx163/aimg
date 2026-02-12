import os
import concurrent.futures
import threading
from typing import List, Optional
from src.core.database import DatabaseManager
from src.core.metadata import MetadataParser
from PyQt6.QtCore import QSettings

class ImageScanner:
    """
    负责扫描文件夹并索引新图片的独立服务类。
    """
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._lock = threading.Lock()
        self._is_scanning = False

    def scan_folders(self) -> int:
        """
        高效扫描所有已配置的文件夹，发现新图片并索引。
        返回新增图片数量。
        """
        with self._lock:
            if self._is_scanning:
                # 避免重入扫描造成重复 IO 和锁竞争
                return 0
            self._is_scanning = True
            
        try:
            folders = self.db.get_unique_folders()
            if not folders:
                return 0

            known_paths = self.db.get_all_file_paths()
            settings = QSettings("ComfyUIImageManager", "Settings")
            recursive = settings.value("scan_recursive", False, type=bool)
            new_files = []
            
            # print(f"[Scanner] Checking {len(folders)} folders...")
            for folder in folders:
                if not os.path.exists(folder): continue
                try:
                    if recursive:
                        for root, _, files in os.walk(folder):
                            for name in files:
                                if not name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                    continue
                                path = os.path.join(root, name)
                                if path not in known_paths and path.replace("\\", "/") not in known_paths:
                                    new_files.append(path)
                    else:
                        with os.scandir(folder) as it:
                            for entry in it:
                                if entry.is_file() and entry.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                    if entry.path not in known_paths and entry.path.replace("\\", "/") not in known_paths:
                                        new_files.append(entry.path)
                except Exception as e:
                    print(f"[Scanner] Error accessing {folder}: {e}")

            # 清理数据库中已不存在的文件，保证 Web 端删除后自动消失
            missing_files = []
            for path in known_paths:
                p = str(path or "").replace("/", os.sep)
                if p and not os.path.exists(p):
                    missing_files.append(path)
            if missing_files:
                self.db.delete_images(missing_files)

            if not new_files:
                return 0

            print(f"[Scanner] Found {len(new_files)} new images. Parsing...")
            
            # 线程池并发解析
            BATCH_SIZE = 50
            current_batch = []
            count = 0
            
            # 限制并发数防止卡顿
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                future_to_path = {executor.submit(MetadataParser.parse_image, path): path for path in new_files}
                
                for future in concurrent.futures.as_completed(future_to_path):
                    path = future_to_path[future]
                    try:
                        meta = future.result()
                        if meta:
                            current_batch.append((path, meta))
                        
                        # 批量写入
                        if len(current_batch) >= BATCH_SIZE:
                            self._flush_batch(current_batch)
                            count += len(current_batch)
                            print(f"[Scanner] Indexed {count}/{len(new_files)}...")
                            current_batch = []
                                
                    except Exception as e:
                        print(f"[Scanner] Failed to parse {os.path.basename(path)}: {e}")

                # 最后一批
                if current_batch:
                    self._flush_batch(current_batch)
                    count += len(current_batch)

            return count
        finally:
            with self._lock:
                self._is_scanning = False

    def _flush_batch(self, batch):
        """将一批解析结果写入数据库"""
        # 使用数据库层实现的批量事务写入，极大提高效率并减少锁定时间
        self.db.add_images_batch(batch)
