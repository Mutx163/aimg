import os
import concurrent.futures
import threading
from typing import List, Optional
from src.core.database import DatabaseManager
from src.core.metadata import MetadataParser

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
            new_files = []
            
            # print(f"[Scanner] Checking {len(folders)} folders...")
            for folder in folders:
                if not os.path.exists(folder): continue
                try:
                    with os.scandir(folder) as it:
                        for entry in it:
                            if entry.is_file() and entry.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                # 规范化路径以进行比对
                                norm_path = os.path.normpath(entry.path)
                                # 简单处理：数据库里的路径可能是 / 或 \ 混合，但在 Windows 上 file_path 存储时建议统一
                                # 这里我们依赖 DatabaseManager 的一致性，或者在此处做标准化
                                if entry.path not in known_paths and entry.path.replace("\\", "/") not in known_paths:
                                    new_files.append(entry.path)
                except Exception as e:
                    print(f"[Scanner] Error accessing {folder}: {e}")

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
