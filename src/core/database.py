import sqlite3
import os
import json
from typing import List, Dict, Any, Optional

class DatabaseManager:
    """
    管理本地 SQLite 数据库，存储图片元数据。
    """
    def __init__(self, db_path: str = "aimg_metadata.db") -> None:
        self.db_path = db_path
        self._init_db()
        # 保持一个长连接，防止 WAL 文件在无操作时被频繁删除/重建导致的文件闪烁
        self._keep_alive_conn = self._get_connection()

    def _get_connection(self):
        """获取数据库连接（带超时和优化配置）"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys=ON")
        # 启用 WAL 模式，显著提高并发性能（读写不互斥）
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
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
                scheduler TEXT,
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
        
        try:
            cursor.execute("SELECT scheduler FROM images LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE images ADD COLUMN scheduler TEXT")
            conn.commit()
        
        # 属性迁移
        try:
            cursor.execute("SELECT file_mtime FROM images LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE images ADD COLUMN file_mtime REAL DEFAULT 0")
            conn.commit()
        
        # 添加 width 和 height 字段
        try:
            cursor.execute("SELECT width FROM images LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE images ADD COLUMN width INTEGER")
            cursor.execute("ALTER TABLE images ADD COLUMN height INTEGER")
            conn.commit()
        
        conn.close()

    def add_images_batch(self, batch: List[tuple]) -> None:
        """批量插入图片元数据（高性能事务模式）"""
        if not batch: return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # 开启事务
            cursor.execute("BEGIN TRANSACTION")

            upsert_sql = '''
                INSERT INTO images (
                    file_path, file_name, prompt, negative_prompt, 
                    seed, steps, sampler, scheduler, cfg_scale, 
                    model_name, model_hash, tool, loras, tech_info, raw_metadata, file_mtime,
                    width, height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    file_name=excluded.file_name,
                    prompt=excluded.prompt,
                    negative_prompt=excluded.negative_prompt,
                    seed=excluded.seed,
                    steps=excluded.steps,
                    sampler=excluded.sampler,
                    scheduler=excluded.scheduler,
                    cfg_scale=excluded.cfg_scale,
                    model_name=excluded.model_name,
                    model_hash=excluded.model_hash,
                    tool=excluded.tool,
                    loras=excluded.loras,
                    tech_info=excluded.tech_info,
                    raw_metadata=excluded.raw_metadata,
                    file_mtime=excluded.file_mtime,
                    width=excluded.width,
                    height=excluded.height
            '''

            for file_path, meta in batch:
                file_path = file_path.replace("\\", "/")
                params = meta.get('params', {})
                tech_info = meta.get('tech_info', {})
                loras = meta.get('loras', [])
                file_mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0
                
                cursor.execute(upsert_sql, (
                    file_path,
                    os.path.basename(file_path),
                    meta.get('prompt', ""),
                    meta.get('negative_prompt', ""),
                    str(params.get('Seed', params.get('seed', ""))),
                    params.get('Steps', params.get('steps')),
                    params.get('Sampler', params.get('sampler_name')),
                    params.get('Scheduler', params.get('scheduler')),
                    params.get('CFG scale', params.get('cfg')),
                    params.get('Model', ""),
                    params.get('Model hash', ""),
                    meta.get('tool', "Unknown"),
                    json.dumps(loras),
                    json.dumps(tech_info),
                    meta.get('raw', ""),
                    file_mtime,
                    params.get('width') or tech_info.get('width') or meta.get('width') or 0,
                    params.get('height') or tech_info.get('height') or meta.get('height') or 0
                ))
                
                # 更新 LoRA 关联表 (此处仍需处理关联，但保持在同一事务内)
                cursor.execute("SELECT id FROM images WHERE file_path = ?", (file_path,))
                row = cursor.fetchone()
                if not row:
                    continue
                img_id = row[0]
                cursor.execute('DELETE FROM image_loras WHERE image_id = ?', (img_id,))
                for l in loras:
                    name = l.split('(')[0].strip()
                    weight = 1.0
                    if '(' in l:
                        try: weight = float(l.split('(')[1].rstrip(')'))
                        except: pass
                    cursor.execute('INSERT INTO image_loras (image_id, lora_name, weight) VALUES (?, ?, ?)',
                                 (img_id, name, weight))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[DB] Batch insertion failed: {e}")
        finally:
            conn.close()

    def add_image(self, file_path: str, meta: Dict[str, Any]) -> None:
        """插入或更新一张图片的元数据"""
        if not meta: return
        
        # 统一路径分隔符，防止 F:\... 和 F:/... 重复
        file_path = file_path.replace("\\", "/")
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        params = meta.get('params', {})
        tech_info = meta.get('tech_info', {})
        loras = meta.get('loras', [])
        
        file_mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0
        
        try:
            cursor.execute('''
                INSERT INTO images (
                    file_path, file_name, prompt, negative_prompt, 
                    seed, steps, sampler, scheduler, cfg_scale, 
                    model_name, model_hash, tool, loras, tech_info, raw_metadata, file_mtime,
                    width, height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    file_name=excluded.file_name,
                    prompt=excluded.prompt,
                    negative_prompt=excluded.negative_prompt,
                    seed=excluded.seed,
                    steps=excluded.steps,
                    sampler=excluded.sampler,
                    scheduler=excluded.scheduler,
                    cfg_scale=excluded.cfg_scale,
                    model_name=excluded.model_name,
                    model_hash=excluded.model_hash,
                    tool=excluded.tool,
                    loras=excluded.loras,
                    tech_info=excluded.tech_info,
                    raw_metadata=excluded.raw_metadata,
                    file_mtime=excluded.file_mtime,
                    width=excluded.width,
                    height=excluded.height
            ''', (
                file_path,
                os.path.basename(file_path),
                meta.get('prompt', ""),
                meta.get('negative_prompt', ""),
                str(params.get('Seed', params.get('seed', ""))),
                params.get('Steps', params.get('steps')),
                params.get('Sampler', params.get('sampler_name')),
                params.get('Scheduler', params.get('scheduler')),
                params.get('CFG scale', params.get('cfg')),
                params.get('Model', ""),
                params.get('Model hash', ""),
                meta.get('tool', "Unknown"),
                json.dumps(loras),
                json.dumps(tech_info),
                meta.get('raw', ""),
                file_mtime,
                params.get('width') or tech_info.get('width') or meta.get('width') or 0,
                params.get('height') or tech_info.get('height') or meta.get('height') or 0
            ))
            
            # 获取 ID 以更新 LoRA 表
            cursor.execute("SELECT id FROM images WHERE file_path = ?", (file_path,))
            row = cursor.fetchone()
            if not row:
                return
            img_id = row[0]
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

    def search_images(self, keyword: str = "", folder_path: Optional[str] = None, 
                     model: Optional[str] = None, lora: Optional[str] = None, 
                     order_by: str = "time_desc") -> List[str]:
        """搜索图片，支持关键字、模型、LoRA、文件夹过滤和排序"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 排序逻辑映射 (使用 file_path 作为最终稳定键)
        order_map = {
            "time_desc": "i.file_mtime DESC, i.file_path ASC",
            "time_asc": "i.file_mtime ASC, i.file_path ASC",
            "name_asc": "i.file_name ASC, i.file_path ASC",
            "name_desc": "i.file_name DESC, i.file_path DESC"
        }
        order_sql = order_map.get(order_by, 'i.file_mtime DESC, i.file_path DESC')

        query, args = self._build_search_base_query(cursor, keyword, folder_path, model, lora)
        query += f" ORDER BY {order_sql}"
        
        try:
            # DEBUG: 打印查询语句，方便排查 0 结果问题
            # print(f"[DB] Executing SQL: {query} | Args: {args}")
            cursor.execute(query, args)
            results = [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"[DB] Search Error: {e}\nQuery: {query}\nArgs: {args}")
            results = []
            
        conn.close()
        return results

    def search_images_page(self, keyword: str = "", folder_path: Optional[str] = None,
                           model: Optional[str] = None, lora: Optional[str] = None,
                           order_by: str = "time_desc", offset: int = 0, limit: int = 30) -> List[str]:
        """分页搜索图片，避免一次性加载全部路径"""
        conn = self._get_connection()
        cursor = conn.cursor()

        order_map = {
            "time_desc": "i.file_mtime DESC, i.file_path ASC",
            "time_asc": "i.file_mtime ASC, i.file_path ASC",
            "name_asc": "i.file_name ASC, i.file_path ASC",
            "name_desc": "i.file_name DESC, i.file_path DESC"
        }
        order_sql = order_map.get(order_by, 'i.file_mtime DESC, i.file_path DESC')

        query, args = self._build_search_base_query(cursor, keyword, folder_path, model, lora)
        query += f" ORDER BY {order_sql} LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        try:
            cursor.execute(query, args)
            results = [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"[DB] Search Page Error: {e}\nQuery: {query}\nArgs: {args}")
            results = []
        finally:
            conn.close()
        return results

    def count_images(self, keyword: str = "", folder_path: Optional[str] = None,
                     model: Optional[str] = None, lora: Optional[str] = None) -> int:
        """统计搜索结果总数（用于分页）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        query, args = self._build_search_base_query(cursor, keyword, folder_path, model, lora)
        count_query = f"SELECT COUNT(*) FROM ({query}) AS sub"
        try:
            cursor.execute(count_query, args)
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        except Exception as e:
            print(f"[DB] Count Error: {e}\nQuery: {count_query}\nArgs: {args}")
            return 0
        finally:
            conn.close()

    def delete_images(self, file_paths: List[str]) -> None:
        """批量删除图片记录（含级联 LoRA）"""
        if not file_paths:
            return
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            placeholders = ",".join(["?"] * len(file_paths))
            cursor.execute(f"DELETE FROM images WHERE file_path IN ({placeholders})", file_paths)
            conn.commit()
        except Exception as e:
            print(f"[DB] Batch delete failed: {e}")
            conn.rollback()
        finally:
            conn.close()

    def _build_search_base_query(self, cursor, keyword: str, folder_path: Optional[str],
                                 model: Optional[str], lora: Optional[str]) -> tuple[str, list]:
        args = []

        if lora and lora != "ALL":
            query = "SELECT DISTINCT i.file_path FROM images i JOIN image_loras il ON i.id = il.image_id WHERE il.lora_name = ?"
            args.append(lora)
        else:
            query = "SELECT i.file_path FROM images i WHERE 1=1"

        if keyword:
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='images_fts'")
                if cursor.fetchone():
                    query += " AND i.id IN (SELECT rowid FROM images_fts WHERE images_fts MATCH ?)"
                    args.append(f'"{keyword}"')
                else:
                    query += " AND (i.prompt LIKE ? OR i.file_name LIKE ?)"
                    args.extend([f"%{keyword}%", f"%{keyword}%"])
            except:
                query += " AND (i.prompt LIKE ? OR i.file_name LIKE ?)"
                args.extend([f"%{keyword}%", f"%{keyword}%"])

        if folder_path:
            norm_folder = folder_path.replace("\\", "/")
            query += " AND i.file_path LIKE ?"
            args.append(f"{norm_folder}%")

        if model and model != "ALL":
            query += " AND i.model_name = ?"
            args.append(model)

        return query, args

    def get_unique_folders(self) -> List[str]:
        """获取所有已索引图片所属的根目录列表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        # 提取路径中最后一个斜杠前的部分作为文件夹
        # 在 SQLite 中处理路径字符串较复杂，这里简单使用 DISTINCT folder_path 的逻辑
        # 如果数据库没存 folder_path 列，我们需要从 file_path 提取
        cursor.execute("SELECT DISTINCT file_path FROM images")
        paths = [row[0] for row in cursor.fetchall()]
        folders = set()
        for p in paths:
            folders.add(os.path.dirname(p).replace("\\", "/"))
        conn.close()
        return sorted(list(folders))

    def get_unique_models(self, folder_path: Optional[str] = None) -> List[tuple]:
        """获取已索引的所有 Checkpoint 模型及其计数"""
        conn = self._get_connection()
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

    def get_unique_loras(self, folder_path: Optional[str] = None, model_filter: Optional[str] = None) -> List[tuple]:
        """
        获取已索引的所有 LoRA 网络及其计数。
        如果指定了 model_filter，则只返回在该模型生成的图片中使用过的 LoRA。
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        args = []
        # 使用 JOIN 来关联 images 表，以便检查 model_name 和 folder_path
        query = """
            SELECT il.lora_name, COUNT(*) as count 
            FROM image_loras il
            JOIN images i ON il.image_id = i.id
            WHERE 1=1
        """
        
        if folder_path:
            norm_folder = folder_path.replace("\\", "/")
            query += " AND i.file_path LIKE ?"
            args.append(f"{norm_folder}%")
            
        if model_filter and model_filter != "ALL":
            query += " AND i.model_name = ?"
            args.append(model_filter)
            
        query += " GROUP BY il.lora_name ORDER BY count DESC"
        
        try:
            cursor.execute(query, args)
            results = cursor.fetchall()
        except Exception as e:
            print(f"[DB] get_unique_loras error: {e}")
            results = []
            
        conn.close()
        return results
    
    def get_unique_resolutions(self, folder_path: Optional[str] = None) -> List[tuple]:
        """获取所有使用过的分辨率"""
        conn = self._get_connection()
        cursor = conn.cursor()
        args = []
        
        # 从tech_info JSON中提取分辨率
        query = """
            SELECT DISTINCT json_extract(tech_info, '$.resolution') as resolution
            FROM images
            WHERE json_extract(tech_info, '$.resolution') IS NOT NULL
        """
        
        if folder_path:
            norm_folder = folder_path.replace("\\", "/")
            query += " AND file_path LIKE ?"
            args.append(f"{norm_folder}%")
        
        cursor.execute(query, args)
        
        # 解析分辨率字符串"512x768"为(512, 768)元组
        resolutions = set()
        for row in cursor.fetchall():
            res_str = row[0]
            if res_str and 'x' in res_str:
                try:
                    w, h = res_str.split('x')
                    resolutions.add((int(w.strip()), int(h.strip())))
                except:
                    pass
        
        conn.close()
        return sorted(list(resolutions), key=lambda x: (x[0], x[1]))
    
    def get_unique_samplers(self, folder_path: Optional[str] = None) -> List[str]:
        """获取所有使用过的采样器名称"""
        conn = self._get_connection()
        cursor = conn.cursor()
        args = []
        
        # 直接从sampler列读取
        query = """
            SELECT DISTINCT sampler
            FROM images
            WHERE sampler IS NOT NULL AND sampler != ''
        """
        
        if folder_path:
            norm_folder = folder_path.replace("\\", "/")
            query += " AND file_path LIKE ?"
            args.append(f"{norm_folder}%")
        
        cursor.execute(query, args)
        
        # 提取采样器名称并排序
        samplers = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return sorted(list(set(samplers)))

    def get_unique_schedulers(self, folder_path: Optional[str] = None) -> List[str]:
        """获取所有使用过的调度器名称"""
        conn = self._get_connection()
        cursor = conn.cursor()
        args = []
        
        # 直接从scheduler列读取
        query = """
            SELECT DISTINCT scheduler
            FROM images
            WHERE scheduler IS NOT NULL AND scheduler != ''
        """
        
        if folder_path:
            norm_folder = folder_path.replace("\\", "/")
            query += " AND file_path LIKE ?"
            args.append(f"{norm_folder}%")
        
        cursor.execute(query, args)
        
        # 提取调度器名称并排序
        schedulers = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return sorted(list(set(schedulers)))

    def get_image_info(self, file_path: str) -> Dict[str, Any]:
        """获取单张图片的详细信息"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT width, height, model_name, seed, steps, sampler, scheduler, cfg_scale, prompt, negative_prompt, loras, tech_info
            FROM images WHERE file_path = ?
        ''', (file_path,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            width = row[0]
            height = row[1]
            
            # 如果数据库没有 width/height，尝试从 tech_info 解析
            if (not width or not height) and row[11]:
                try:
                    tech_info = json.loads(row[11])
                    if 'resolution' in tech_info:
                        res = tech_info['resolution']
                        if 'x' in res:
                            parts = res.split('x')
                            width = int(parts[0]) if parts[0].isdigit() else 0
                            height = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                except:
                    pass
            
            return {
                'width': width or 0,
                'height': height or 0,
                'model_name': row[2] or '',
                'seed': row[3] or '',
                'steps': row[4] or 0,
                'sampler': row[5] or '',
                'scheduler': row[6] or '',
                'cfg_scale': row[7] or 0,
                'prompt': row[8] or '',
                'negative_prompt': row[9] or '',
                'loras': json.loads(row[10]) if row[10] else []
            }
        return {}
    def get_images_batch_info(self, file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取图片信息，优化列表加载性能"""
        if not file_paths:
            return {}
            
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 动态构建 SQL，使用 parameters preventing injection
        placeholders = ','.join(['?'] * len(file_paths))
        query = f'''
            SELECT file_path, width, height, model_name, seed, steps, sampler, scheduler, cfg_scale, prompt, negative_prompt, loras, tech_info
            FROM images WHERE file_path IN ({placeholders})
        '''
        
        try:
            cursor.execute(query, file_paths)
            results = {}
            for row in cursor.fetchall():
                path = row[0]
                
                # Width/Height fallback logic
                width, height = row[1], row[2]
                if (not width or not height) and row[12]:
                    try:
                        tech_info = json.loads(row[12])
                        if 'resolution' in tech_info:
                            res = tech_info['resolution']
                            if 'x' in res:
                                parts = res.split('x')
                                width = int(parts[0]) if parts[0].isdigit() else width
                                height = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else height
                    except: pass
                
                results[path] = {
                    'width': width or 0,
                    'height': height or 0,
                    'model_name': row[3] or '',
                    'seed': row[4] or '',
                    'steps': row[5] or 0,
                    'sampler': row[6] or '',
                    'scheduler': row[7] or '',
                    'cfg_scale': row[8] or 0,
                    'prompt': row[9] or '',
                    'negative_prompt': row[10] or '',
                    'loras': json.loads(row[11]) if row[11] else []
                }
            return results
        except Exception as e:
            print(f"[DB] Batch info error: {e}")
            return {}
        finally:
            conn.close()

    def get_all_file_paths(self):
        """获取数据库中所有已索引的文件路径集合"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT file_path FROM images")
            return {row[0] for row in cursor.fetchall()}

    def get_file_mtime_map(self, folder_path: Optional[str] = None) -> Dict[str, float]:
        """获取文件路径到 mtime 的映射，用于快速判断是否需要重新解析"""
        conn = self._get_connection()
        cursor = conn.cursor()
        args = []
        query = "SELECT file_path, file_mtime FROM images WHERE 1=1"
        if folder_path:
            norm_folder = folder_path.replace("\\", "/")
            query += " AND file_path LIKE ?"
            args.append(f"{norm_folder}%")
        try:
            cursor.execute(query, args)
            return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception as e:
            print(f"[DB] mtime map error: {e}")
            return {}
        finally:
            conn.close()
