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
        
        # 1. 图片主表
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
                loras TEXT, -- 保留 JSON 副本用于兼容
                tech_info TEXT,
                raw_metadata TEXT,
                file_mtime REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 2. LoRA 关联表 (优化统计和筛选)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS image_loras (
                image_id INTEGER,
                lora_name TEXT,
                weight REAL,
                FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_lora_name ON image_loras(lora_name)')

        # 3. FTS5 全文检索表
        # 注意：某些环境可能不支持 FTS5，这里做个兜底
        try:
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
                    prompt, 
                    file_name,
                    content='images',
                    content_rowid='id'
                )
            ''')
            # 建立触发器以保持同步
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS bu_images_fts AFTER UPDATE ON images BEGIN
                    INSERT INTO images_fts(images_fts, rowid, prompt, file_name) VALUES('delete', old.id, old.prompt, old.file_name);
                    INSERT INTO images_fts(rowid, prompt, file_name) VALUES (new.id, new.prompt, new.file_name);
                END;
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS bi_images_fts AFTER INSERT ON images BEGIN
                    INSERT INTO images_fts(rowid, prompt, file_name) VALUES (new.id, new.prompt, new.file_name);
                END;
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS bd_images_fts AFTER DELETE ON images BEGIN
                    INSERT INTO images_fts(images_fts, rowid, prompt, file_name) VALUES('delete', old.id, old.prompt, old.file_name);
                END;
            ''')
        except sqlite3.OperationalError:
            print("[Warning] SQLite FTS5 extension not available. Falling back to LIKE.")

        # 索引，优化基础搜索
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_path ON images(file_path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_name ON images(model_name)')
        
        conn.commit()
        
        # 属性迁移
        try:
            cursor.execute("SELECT file_mtime FROM images LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE images ADD COLUMN file_mtime REAL DEFAULT 0")
            conn.commit()
        
        conn.close()

    def add_image(self, file_path, meta):
        """插入或更新一张图片的元数据"""
        if not meta: return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        params = meta.get('params', {})
        tech_info = meta.get('tech_info', {})
        loras = meta.get('loras', [])
        
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
            
            # 获取 ID 以更新 LoRA 表
            img_id = cursor.lastrowid
            cursor.execute('DELETE FROM image_loras WHERE image_id = ?', (img_id,))
            for l in loras:
                # 尝试解析 "LoRA Name (Weight)"
                name = l.split('(')[0].strip()
                weight = 1.0
                if '(' in l:
                    try:
                        weight = float(l.split('(')[1].rstrip(')'))
                    except: pass
                cursor.execute('INSERT INTO image_loras (image_id, lora_name, weight) VALUES (?, ?, ?)',
                             (img_id, name, weight))
                             
            conn.commit()
        except Exception as e:
            print(f"Database insertion error: {e}")
        finally:
            conn.close()

    def search_images(self, keyword="", folder_path=None, model=None, lora=None, order_by="time_desc"):
        """搜索图片，支持关键字、模型、LoRA、文件夹过滤和排序"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 排序逻辑映射
        order_map = {
            "time_desc": "file_mtime DESC",
            "time_asc": "file_mtime ASC",
            "name_asc": "file_name ASC",
            "name_desc": "file_name DESC"
        }
        order_sql = order_map.get(order_by, 'file_mtime DESC')

        args = []
        
        # 构建主查询，如果使用 LoRA 过滤，则需要 JOIN
        if lora:
            query = "SELECT i.file_path FROM images i JOIN image_loras il ON i.id = il.image_id WHERE il.lora_name = ?"
            args.append(lora)
        else:
            query = "SELECT file_path FROM images WHERE 1=1"

        if keyword:
            # 尝试使用 FTS5
            try:
                # 检查 FTS5 表是否存在
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='images_fts'")
                if cursor.fetchone():
                    # 使用 FTS5 MATCH，结合子查询
                    query += f" AND id IN (SELECT rowid FROM images_fts WHERE images_fts MATCH ?)"
                    args.append(keyword)
                else:
                    query += " AND (prompt LIKE ? OR file_name LIKE ?)"
                    args.extend([f"%{keyword}%", f"%{keyword}%"])
            except:
                query += " AND (prompt LIKE ? OR file_name LIKE ?)"
                args.extend([f"%{keyword}%", f"%{keyword}%"])
            
        if folder_path:
            query += " AND file_path LIKE ?"
            args.append(f"{folder_path}%")

        if model and model != "ALL":
            query += " AND model_name = ?"
            args.append(model)
        
        query += f" ORDER BY {order_sql}"
        
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
        """获取已索引的所有 LoRA 网络及其计数 (极速版)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT il.lora_name, COUNT(*) as count FROM image_loras il"
        args = []
        
        if folder_path:
            query += " JOIN images i ON il.image_id = i.id WHERE i.file_path LIKE ?"
            args.append(f"{folder_path}%")
            
        query += " GROUP BY il.lora_name ORDER BY count DESC"
        
        cursor.execute(query, args)
        results = cursor.fetchall()
        conn.close()
        return results
