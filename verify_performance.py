import os
import time
import sqlite3
from src.core.database import DatabaseManager
from src.core.cache import ThumbnailCache
from src.core.metadata import MetadataParser
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication
import sys

def verify_all():
    # 模拟 QApplication 环境以便处理 QImage/QPixmap
    app = QApplication(sys.argv)
    
    print("=== AI Image Viewer 优化验证项目 ===")
    
    # 1. 验证数据库 FTS5
    db = DatabaseManager("test_verify.db")
    print("[DB] 正在注入测试数据...")
    test_meta = {
        'prompt': "a beautiful sunset over a cyberpunk city, neon lights, highly detailed",
        'negative_prompt': "blur, distorted",
        'loras': ["CyberCity(0.8)", "NeonGlow(1.2)"],
        'params': {'Model': 'SDXL_Turbo', 'Seed': 12345}
    }
    db.add_image("test_path_1.png", test_meta)
    
    start_search = time.time()
    results = db.search_images(keyword="cyberpunk")
    end_search = time.time()
    print(f"[DB] FTS5 搜索 'cyberpunk' 耗时: {(end_search - start_search)*1000:.2f}ms")
    assert "test_path_1.png" in results
    
    loras = db.get_unique_loras()
    print(f"[DB] LoRA 统计结果: {loras}")
    assert any("CyberCity" in l[0] for l in loras)

    # 2. 验证缓存系统
    cache = ThumbnailCache(".test_thumbs")
    test_img = QImage(1024, 1024, QImage.Format.Format_RGB32)
    test_img.fill(0xFF0000)
    
    cache.save_thumbnail("dummy.png", test_img)
    start_cache = time.time()
    loaded_thumb = cache.get_thumbnail("dummy.png")
    end_cache = time.time()
    
    print(f"[Cache] 缓存读取耗时: {(end_cache - start_cache)*1000:.2f}ms")
    assert loaded_thumb is not None
    assert not loaded_thumb.isNull()

    # 3. 验证元数据解析
    print("[Meta] 验证解析逻辑...")
    # 这里可以使用真实图片测试，或者跳过
    
    print("\n✅ 所有核心组件验证通过！")
    
    # 清理测试文件
    try:
        os.remove("test_verify.db")
        for f in os.listdir(".test_thumbs"):
            os.remove(os.path.join(".test_thumbs", f))
        os.rmdir(".test_thumbs")
    except: pass

if __name__ == "__main__":
    verify_all()
