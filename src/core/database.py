import sqlite3
import os
import json

class DatabaseManager:
    """
    管理本地 SQLite 数据库，存储图片元数据。
    """
    def __init__(self, db_path="aimg_metadata.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 图片主表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                file_name TEXT,
                prompt TEXT,
                negative_prompt TEXT,
                seed TEXT,
                steps INTEGER,
                sampler TEXT,
                cfg_scale REAL,
                model_name TEXT,
                model_hash TEXT,
                tool TEXT,
                loras TEXT,
                tech_info TEXT,
                raw_metadata TEXT,
                file_mtime REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 索引，优化搜索
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_prompt ON images(prompt)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_path ON images(file_path)')
        
        conn.commit()
        
        # 数据库迁移：添加 file_mtime 列（如果不存在）
        try:
            cursor.execute("SELECT file_mtime FROM images LIMIT 1")
        except sqlite3.OperationalError:
            # 列不存在，需要添加
            print("[DB Migration] Adding file_mtime column to existing database...")
            cursor.execute("ALTER TABLE images ADD COLUMN file_mtime REAL DEFAULT 0")
            conn.commit()
            print("[DB Migration] Migration complete.")
        
        conn.close()

    def add_image(self, file_path, meta):
        """插入或更新一张图片的元数据"""
        if not meta: return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        params = meta.get('params', {})
        tech_info = meta.get('tech_info', {})
        loras = meta.get('loras', [])
        
        # 获取文件修改时间
        file_mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO images (
                    file_path, file_name, prompt, negative_prompt, 
                    seed, steps, sampler, cfg_scale, 
                    model_name, model_hash, tool, loras, tech_info, raw_metadata, file_mtime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                file_path,
                os.path.basename(file_path),
                meta.get('prompt', ""),
                meta.get('negative_prompt', ""),
                str(params.get('Seed', params.get('seed', ""))),
                params.get('Steps', params.get('steps')),
                params.get('Sampler', params.get('sampler_name')),
                params.get('CFG scale', params.get('cfg')),
                params.get('Model', ""),
                params.get('Model hash', ""),
                meta.get('tool', "Unknown"),
                json.dumps(loras),
                json.dumps(tech_info),
                meta.get('raw', ""),
                file_mtime
            ))
            conn.commit()
        except Exception as e:
            print(f"Database insertion error: {e}")
        finally:
            conn.close()

    def search_images(self, keyword="", folder_path=None, model=None, lora=None, order_by="time_desc"):
        """搜索图片，支持关键字、模型、LoRA、文件夹过滤和排序"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT file_path FROM images WHERE 1=1"
        args = []
        
        if keyword:
            query += " AND (prompt LIKE ? OR file_name LIKE ?)"
            args.extend([f"%{keyword}%", f"%{keyword}%"])
            
        if folder_path:
            query += " AND file_path LIKE ?"
            args.append(f"{folder_path}%")

        if model:
            if model == "ALL":
                pass
            else:
                query += " AND model_name = ?"
                args.append(model)
        
        if lora:
            query += " AND loras LIKE ?"
            args.append(f'%"{lora}%')
        
        # 排序逻辑
        order_map = {
            "time_desc": "file_mtime DESC",
            "time_asc": "file_mtime ASC",
            "name_asc": "file_name ASC",
            "name_desc": "file_name DESC"
        }
        query += f" ORDER BY {order_map.get(order_by, 'file_mtime DESC')}"
        
        cursor.execute(query, args)
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results

    def get_unique_models(self, folder_path=None):
        """获取已索引的所有 Checkpoint 模型及其计数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = "SELECT model_name, COUNT(*) as count FROM images WHERE model_name != ''"
        args = []
        if folder_path:
            query += " AND file_path LIKE ?"
            args.append(f"{folder_path}%")
        query += " GROUP BY model_name ORDER BY count DESC"
        cursor.execute(query, args)
        results = cursor.fetchall()
        conn.close()
        return results

    def get_unique_loras(self, folder_path=None):
        """获取已索引的所有 LoRA 模型及其计数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = "SELECT loras FROM images WHERE loras != '[]'"
        args = []
        if folder_path:
            query += " AND file_path LIKE ?"
            args.append(f"{folder_path}%")
        cursor.execute(query, args)
        
        lora_counts = {}
        for row in cursor.fetchall():
            try:
                loras = json.loads(row[0])
                for l in loras:
                    name = l.split('(')[0].strip()
                    lora_counts[name] = lora_counts.get(name, 0) + 1
            except: pass
            
        conn.close()
        return sorted(lora_counts.items(), key=lambda x: x[1], reverse=True)
