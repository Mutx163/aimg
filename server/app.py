import os
import sys
import json
import socket
import asyncio
import urllib.parse
from typing import Optional, List, Dict, Any, AsyncGenerator
from fastapi import FastAPI, HTTPException, Query, Body, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 将项目根目录添加到路径，以便导入 src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database import DatabaseManager
from src.core.metadata import MetadataParser
from src.core.ai_prompt_optimizer import AIPromptOptimizer
from src.core.ai_prompt_optimizer import AIPromptOptimizer
from src.assets.default_workflows import DEFAULT_T2I_WORKFLOW
import concurrent.futures

# --- Background Scanner Logic ---
def scan_folders(db_manager):
    """
    高效扫描所有已配置的文件夹，发现新图片并索引。
    """
    folders = db_manager.get_unique_folders()
    if not folders:
        # Default fallback if no folders in DB yet
        return 0

    known_paths = db_manager.get_all_file_paths()
    new_files = []
    
    print(f"[Scanner] Checking {len(folders)} folders...")
    for folder in folders:
        if not os.path.exists(folder): continue
        try:
            # Recursive scan could be added here if needed, currently blocking for speed
            with os.scandir(folder) as it:
                for entry in it:
                    if entry.is_file() and entry.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        if entry.path not in known_paths:
                            new_files.append(entry.path)
        except Exception as e:
            print(f"[Scanner] Error accessing {folder}: {e}")

    if not new_files:
        return 0

    print(f"[Scanner] Found {len(new_files)} new images. Parsing...")
    
    # Batch processing with ThreadPool
    BATCH_SIZE = 50
    current_batch = []
    count = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_path = {executor.submit(MetadataParser.parse_image, path): path for path in new_files}
        
        for future in concurrent.futures.as_completed(future_to_path):
            path = future_to_path[future]
            try:
                meta = future.result()
                if meta:
                    current_batch.append((path, meta))
                
                # Commit batch
                if len(current_batch) >= BATCH_SIZE:
                    try:
                        # Transactional batch insert would be better in DatabaseManager, 
                        # but for now loop-insert is strictly safely serialied by SQLite driver if configured right,
                        # or we manually call add_image sequentially here which is fast.
                        # Ideally: db_manager.add_images_batch(current_batch)
                        # Fallback to sequential for safety but grouped
                        for p, m in current_batch:
                            db_manager.add_image(p, m)
                        count += len(current_batch)
                        print(f"[Scanner] Indexed {count}/{len(new_files)}...")
                        current_batch = []
                    except Exception as e:
                        print(f"[Scanner] Batch write error: {e}")
                        
            except Exception as e:
                print(f"[Scanner] Failed to parse {os.path.basename(path)}: {e}")

        # Final batch
        if current_batch:
            for p, m in current_batch:
                db_manager.add_image(p, m)
            count += len(current_batch)

    return count


app = FastAPI(title="AI Image Viewer Mobile API")

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 强制不缓存静态文件和 API，解决用户反映的“没有变化”问题
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    # 排除 /api/image/ 开头的路径（如 raw, thumb），让浏览器正常缓存图片
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/image/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.url.path.startswith("/api/image/"):
        # Aggressive caching for images (Year long) - Immutable by path
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    return response

db = DatabaseManager()
ai_optimizer = AIPromptOptimizer()

# --- 图片浏览 API ---

@app.get("/api/images")
async def get_images(
    keyword: str = "",
    folder: Optional[str] = None,
    model: Optional[str] = None,
    lora: Optional[str] = None,
    sort: str = "time_desc",
    page: int = 1,
    page_size: int = 30
):
    """获取图片列表，支持搜索、多维筛选和内部分页过滤"""
    all_paths = db.search_images(
        keyword=keyword, 
        folder_path=folder, 
        model=model, 
        lora=lora, 
        order_by=sort
    )
    
    start_idx = (page - 1) * page_size
    valid_images = []
    current_idx = start_idx
    
    # 1. 收集当前页的所有路径
    target_paths = []
    # 增加 os.path.exists 检查以过滤掉已被删除依然在缓存中的文件
    # 虽然这会增加一点 IO，但能避免前端显示"幽灵"空图
    while len(target_paths) < page_size and current_idx < len(all_paths):
        path = all_paths[current_idx]
        if os.path.exists(path):
            target_paths.append(path)
        current_idx += 1
    
    # 2. 批量获取元数据
    batch_info = db.get_images_batch_info(target_paths)
    
    # 3. 组装结果
    for path in target_paths:
        info = batch_info.get(path, {})
        valid_images.append({
            "file_path": path,
            "file_name": os.path.basename(path), # Add file_name for frontend logs
            "width": info.get('width', 0) or 0,
            "height": info.get('height', 0) or 0,
            # 未来可以在这里添加 tiny_hash 或 color
        })
    
    return {
        "total": len(all_paths),
        "page": page,
        "page_size": page_size,
        "images": valid_images,
        "has_more": current_idx < len(all_paths)
    }

@app.get("/api/image/raw")
async def get_raw_image(path: str):
    """流式返回原始图片文件"""
    normalized_path = os.path.normpath(path)
    if not os.path.exists(normalized_path):
        print(f"[404] File not found: {normalized_path}")
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(normalized_path)

@app.get("/api/metadata")
async def get_metadata(path: str):
    """解析单张图片的元数据 (优先查库，避免重复IO)"""
    normalized_path = os.path.normpath(path)
    # 数据库中存储的路径通常为正斜杠，确保查询匹配
    db_path = normalized_path.replace("\\", "/")
    
    # 1. 尝试从数据库获取 (极速)
    info = db.get_image_info(db_path)
    if info:
        print(f"[Metadata] Cache Hit: {os.path.basename(path)}")
        # 构造兼容 MetadataParser.parse_image 输出的格式
        return {
            "prompt": info.get('prompt', ""),
            "negative_prompt": info.get('negative_prompt', ""),
            "loras": info.get('loras', []),
            "params": {
                "Model": info.get('model_name', ""),
                "Seed": info.get('seed', ""),
                "Steps": info.get('steps', 0),
                "Sampler": info.get('sampler', ""),
                "Scheduler": info.get('scheduler', ""),
                "CFG scale": info.get('cfg_scale', 0),
                "width": info.get('width', 0),
                "height": info.get('height', 0),
                "size": f"{info.get('width', 0)}x{info.get('height', 0)}"
            },
            "tech_info": {
                "resolution": f"{info.get('width', 0)}x{info.get('height', 0)}"
            },
            "tool": "Database (Cached)"
        }

    # 2. 数据库无记录，回退到实时解析 (较慢)
    print(f"[Metadata] Cache MISS: {os.path.basename(path)} (Parsing file...)")
    if not os.path.exists(normalized_path):
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        t0 = time.time()
        res = MetadataParser.parse_image(normalized_path)
        print(f"[Metadata] Parsed in {time.time()-t0:.2f}s")
        
        # 自动补全数据库 (Self-Correction)
        # 如果是因为没扫描到，这里解析完顺便存进去，下次就快了
        threading.Thread(target=db.add_image, args=(normalized_path, res)).start()
        
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 筛选统计 API ---

@app.get("/api/filters")
async def get_filters():
    """获取所有可用的筛选选项（模型、LoRA、文件夹、采样器、调度器）"""
    return {
        "folders": db.get_unique_folders(),
        "models": [row[0] for row in db.get_unique_models()],
        "loras": [row[0] for row in db.get_unique_loras()],
        "resolutions": [f"{r[0]}x{r[1]}" for r in db.get_unique_resolutions()],
        "samplers": db.get_unique_samplers(),
        "schedulers": db.get_unique_schedulers()
    }

# --- AI 提示词优化 API ---

# --- 生图控制 API (ComfyUI 适配) ---

import requests as py_requests

COMFY_ADDRESS = "127.0.0.1:8189" # 匹配用户实际运行的端口

@app.get("/api/comfy/status")
async def get_comfy_status():
    """检查 ComfyUI 连接状态"""
    try:
        resp = py_requests.get(f"http://{COMFY_ADDRESS}/system_stats", timeout=2)
        return resp.json()
    except:
        return {"connected": False}

@app.get("/api/comfy/models")
async def get_comfy_models():
    """获取 ComfyUI 可用模型列表"""
    try:
        # 尝试从不同的 Loader 获取模型列表
        resp = py_requests.get(f"http://{COMFY_ADDRESS}/object_info/CheckpointLoaderSimple", timeout=5)
        data = resp.json()
        models = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
        return models
    except:
        return []

@app.get("/api/comfy/samplers_schedulers")
async def get_comfy_samplers_schedulers():
    """获取 ComfyUI 支持的采样器和调度器列表"""
    try:
        resp = py_requests.get(f"http://{COMFY_ADDRESS}/object_info/KSampler", timeout=5)
        data = resp.json()
        required = data.get("KSampler", {}).get("input", {}).get("required", {})
        
        samplers = required.get("sampler_name", [[]])[0]
        schedulers = required.get("scheduler", [[]])[0]
        
        return {
            "samplers": samplers,
            "schedulers": schedulers
        }
    except Exception as e:
        print(f"[API] Failed to fetch ComfyUI samplers: {e}")
        return {"samplers": [], "schedulers": []}

@app.get("/api/comfy/queue")
async def get_full_queue():
    """获取 ComfyUI 的详细任务队列（包括待执行和执行记录）"""
    try:
        # 获取待执行队列
        queue_resp = py_requests.get(f"http://{COMFY_ADDRESS}/queue", timeout=2)
        queue_data = queue_resp.json()
        
        # 获取执行历史
        history_resp = py_requests.get(f"http://{COMFY_ADDRESS}/history", timeout=2)
        history_data = history_resp.json()
        
        # 简化历史记录，只取最近 10 条
        history_list = []
        for task_id, info in list(history_data.items())[::-1][:10]:
            prompt = info.get("prompt", [None, None, {}])[2]
            # 尝试从输入提示词中提取简短描述
            desc = "未知任务"
            if "6" in prompt: # Positive prompt node
                desc = prompt["6"]["inputs"].get("text", "")[:30] + "..."
            
            history_list.append({
                "id": task_id,
                "status": "completed",
                "description": desc,
                "timestamp": info.get("status", {}).get("completed", True)
            })

        # 解析队列详情 (Move logic before return)
        pending_tasks = []
        queue_items = queue_data.get("queue_running", []) + queue_data.get("queue_pending", [])
        
        for i, item in enumerate(queue_items):
            # item structure: [number, prompt_id, prompt_data, extra_data, ...]
            task_info = {
                "id": item[1], # prompt_id
                "status": "running" if item in queue_data.get("queue_running", []) else "pending",
                "prompt": "任务中...",
                "lora_info": ""
            }
            
            # 尝试解析 prompt_data
            if len(item) >= 3:
                    prompt_data = item[2]
                    # 1. 提取正向提示词 (Node 6)
                    if "6" in prompt_data:
                        text = prompt_data["6"]["inputs"].get("text", "")
                        task_info["prompt"] = text[:15] + "..." if len(text) > 15 else text
                    
                    # 2. 提取 LoRA 信息 (Node 28)
                    if "28" in prompt_data:
                        inputs = prompt_data["28"]["inputs"]
                        l_name = inputs.get("lora_name", "")
                        l_weight = inputs.get("strength_model", 1.0)
                        # 去掉 .safetensors 后缀
                        if l_name.endswith(".safetensors"):
                            l_name = l_name[:-12]
                        if l_name:
                            task_info["lora_info"] = f"{l_name} ({l_weight})"
            
            pending_tasks.append(task_info)

        return {
            "pending": pending_tasks,
            "history": history_list,
            "queue_remaining": queue_data.get("exec_info", {}).get("queue_remaining", 0)
        }
    except Exception as e:
        print(f"[API] Queue fetch error: {e}")
        return {"pending": [], "history": []}

class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    model: str = ""
    lora: str = ""
    lora_weight: float = 1.0
    resolution: str = "512x768"
    steps: int = 20
    cfg: float = 7.0
    sampler: str = "euler"
    scheduler: str = "normal"
    seed: int = -1  # -1 means random
    denoise: float = 1.0
    batch_size: int = 1
    shift: float = 3.0

@app.post("/api/comfy/generate")
async def generate_image(req: GenerateRequest):
    """提交生图任务到 ComfyUI"""
    try:
        # 基于 DEFAULT_T2I_WORKFLOW 构造工作流
        wf = json.loads(json.dumps(DEFAULT_T2I_WORKFLOW))
        
        # Seed Handling
        import random
        seed = req.seed if req.seed != -1 else random.randint(1, 10**15)
        
        w, h = map(int, req.resolution.split('x'))
        
        # 常见节点映射
        if "3" in wf:
            wf["3"]["inputs"]["steps"] = req.steps
            wf["3"]["inputs"]["cfg"] = req.cfg
            wf["3"]["inputs"]["seed"] = seed
            wf["3"]["inputs"]["sampler_name"] = req.sampler
            wf["3"]["inputs"]["scheduler"] = req.scheduler
            wf["3"]["inputs"]["denoise"] = req.denoise
        
        if "5" in wf:
            wf["5"]["inputs"]["width"] = w
            wf["5"]["inputs"]["height"] = h
            wf["5"]["inputs"]["batch_size"] = req.batch_size
        
        if "11" in wf:
            wf["11"]["inputs"]["shift"] = req.shift
            
        if "6" in wf:
            wf["6"]["inputs"]["text"] = req.prompt
            
        if "7" in wf:
            wf["7"]["inputs"]["text"] = req.negative_prompt
            
        # 如果提供了模型名称且存在 Loader 节点
        if req.model:
            model_target = req.model
            # 兼容性处理：如果用户选中的模型没有后缀而工作流需要后缀
            if not model_target.endswith(".safetensors") and not model_target.endswith(".ckpt"):
                # 这种情况常见于从解析出的元数据中直接复刻模型名
                model_target += ".safetensors"
            
            # 模板中使用的是 UNETLoader (16)
            if "16" in wf:
                wf["16"]["inputs"]["unet_name"] = model_target

        # 处理 LoRA (节点 28)
        if req.lora:
            lora_target = req.lora
            if not lora_target.endswith(".safetensors") and not lora_target.endswith(".ckpt"):
                lora_target += ".safetensors"
            
            if "28" in wf:
                wf["28"]["inputs"]["lora_name"] = lora_target
                wf["28"]["inputs"]["strength_model"] = req.lora_weight
        elif "28" in wf:
            # 如果没传 LoRA，将强度设为 0
            wf["28"]["inputs"]["strength_model"] = 0.0
        
        # 提交任务
        p = {"prompt": wf, "client_id": "mobile_client"}
        resp = py_requests.post(f"http://{COMFY_ADDRESS}/prompt", json=p, timeout=5)
        
        if resp.status_code == 200:
            return resp.json()
        else:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@app.post("/api/ai/optimize")
async def ai_optimize(request: Request):
    """
    AI 提示词优化/生成 (流式)
    支持从前端传递 system_prompt 以保持同步
    """
    try:
        data = await request.json()
        mode = data.get("mode", "generate")
        user_input = data.get("user_input", "")
        existing_prompt = data.get("existing_prompt", "")
        image_b64 = data.get("image_b64", "")
        custom_system_prompt = data.get("system_prompt", None)

        from src.core.ai_prompt_optimizer import AIPromptOptimizer
        optimizer = AIPromptOptimizer()
        
        # 获取默认系统提示词
        if mode == "generate":
            default_sys = optimizer.SYSTEM_PROMPT_GENERATE
        elif mode == "optimize":
            default_sys = optimizer.SYSTEM_PROMPT_OPTIMIZE
        elif mode == "negative":
            default_sys = optimizer.SYSTEM_PROMPT_NEG_OPTIMIZE if existing_prompt else optimizer.SYSTEM_PROMPT_NEG_GENERATE
        else:
            default_sys = ""

        # 如果前端提供了 custom_system_prompt，则优先使用
        system_prompt = custom_system_prompt if custom_system_prompt else default_sys

        async def generate():
            if mode == "image":
                # 图生文目前暂不支持流式系统提示词自定义，按默认处理
                success, result = optimizer.generate_prompt_from_image(image_b64)
                yield f"data: {json.dumps({'chunk': result, 'done': True})}\n\n"
            else:
                # 提示词优化/生成
                messages = []
                if mode == "generate":
                    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
                elif mode == "optimize":
                    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"原提示词: {existing_prompt}\n\n指令: {user_input}"}]
                elif mode == "negative":
                    if existing_prompt:
                        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"原反向词: {existing_prompt}\n\n指令: {user_input}"}]
                    else:
                        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]

                # 为了响应用户对“同步提示词”的要求，我们直接调用底层 API 以支持流式
                # 为了响应用户对“同步提示词”的要求，我们直接调用底层 API 以支持流式
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        async with client.stream(
                            "POST",
                            optimizer.api_endpoint,
                            headers={"Authorization": f"Bearer {optimizer.api_key}"},
                            json={
                                "model": optimizer.model_name,
                                "messages": messages,
                                "temperature": 0.4,
                                "stream": True
                            }
                        ) as response:
                            async for line in response.aiter_lines():
                                if line:
                                    print(".", end="", flush=True) # Debug: Visualizer activity
                                    if line.startswith("data: "):
                                        data_str = line[6:].strip()
                                        if data_str == "[DONE]": break
                                        try:
                                            chunk_json = json.loads(data_str)
                                            # 兼容 OpenAI 格式
                                            if "choices" in chunk_json:
                                                chunk = chunk_json["choices"][0]["delta"].get("content", "")
                                                if chunk:
                                                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                                        except: continue
                            print(" [Done]") # Debug: End of stream
                    yield f"data: {json.dumps({'done': True})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        return {"error": str(e)}

# --- 增量扫描 API ---

# Duplicate scan_folders removed
# The active scan_folders is defined at the top of the file with ThreadPool optimization

@app.post("/api/scan")
async def trigger_scan():
    """手动触发全量/增量扫描"""
    try:
        count = scan_folders(db)
        return {"success": True, "new_images": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/image/thumb")
def get_thumbnail(path: str, size: int = 768):
    """获取缩略图，支持指定尺寸 (默认 768px, 可选 1600px 用于预览)"""
    normalized_path = os.path.normpath(path)
    if not os.path.exists(normalized_path):
        raise HTTPException(status_code=404, detail="Original image not found")
        
    import hashlib
    from PIL import Image
    
    # Ensure cache dir uses absolute path to avoid CWD issues
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cache_dir = os.path.join(base_dir, ".thumbs")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
        
    # Standardize path for hashing to avoid duplication (always use /)
    hash_key = path.replace("\\", "/")
    file_hash = hashlib.md5(hash_key.encode('utf-8')).hexdigest()
    try:
        mtime = int(os.path.getmtime(normalized_path))
    except:
        mtime = 0
    
    # 标识 (_w{size})
    thumb_path = os.path.join(cache_dir, f"{file_hash}_{mtime}_w{size}.webp")
    
    if os.path.exists(thumb_path):
        return FileResponse(thumb_path)
        
    try:
        # 清理该文件的旧缓存 (只清理同一尺寸的旧版本?)
        # 为了简单且避免无限增长，可以清理该文件hash下的所有旧版本，但这会删掉不同尺寸的缓存
        # 改进策略：只删除 file_hash 开头 且不等于当前 thumb_path 的？
        # 或者暂时不激进清理，保留不同尺寸（因为 768 和 1600 都会被用到）
        # 仅当 mtime 变化时（即上面的 filename check 失败），我们需要清理旧 mtime 的文件
        
        # 扫描清理：删除同 hash 但 mtime 不同的旧缓存 (同尺寸或所有尺寸?)
        # 简单起见，我们假设 immutable，文件名包含 mtime。
        # 如果文件更新了，mtime 变了，hash 还是对 path 的 hash...
        # 真正的问题是：如果文件内容变了，mtime 变。
        # 此时应该删除该 path 对应的旧 mtime 缓存。
        
        for f in os.listdir(cache_dir):
            if f.startswith(file_hash + "_") and f != os.path.basename(thumb_path):
                # 检查是否是不同尺寸的同版本？
                # f 格式: {hash}_{mtime}_w{size}.webp
                parts = f.split('_')
                if len(parts) >= 3:
                    f_mtime = parts[1]
                    f_size = parts[2].split('.')[0] # w768
                    
                    # 如果 mtime 不同，即原图已更新，则删除旧图
                    if str(mtime) != f_mtime:
                        try: os.remove(os.path.join(cache_dir, f))
                        except: pass
        
        with Image.open(normalized_path) as img:
            # 限制最大尺寸，防止恶意消耗服务器资源
            target_size = min(size, 2560) 
            
            resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
            img.thumbnail((target_size, target_size), resample=resample_filter)
            img.save(thumb_path, "WEBP", quality=85)
        return FileResponse(thumb_path)
    except Exception as e:
        print(f"[Thumb] HQ Gen Failed: {e}")
        return FileResponse(normalized_path)

@app.delete("/api/image")
async def delete_image(path: str):
    """删除图片文件并从数据库移除"""
    if not path:
        raise HTTPException(status_code=400, detail="Path is required")
    
    try:
        from send2trash import send2trash
        import sqlite3
        
        # 兼容性处理：规范化路径
        safe_path = os.path.normpath(os.path.abspath(path))
        
        # 1. 移至回收站
        if os.path.exists(safe_path):
            send2trash(safe_path)
        
        # 2. 从数据库删除
        # 注意：规范化数据库中的路径
        db_path = safe_path.replace("\\", "/")
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM images WHERE file_path = ?", (db_path,))
        conn.commit()
        conn.close()
        
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 挂载前端静态文件
web_dist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")
if os.path.exists(web_dist_path):
    app.mount("/", StaticFiles(directory=web_dist_path, html=True), name="web")
elif os.path.exists("mobile"):
    app.mount("/", StaticFiles(directory="mobile", html=True), name="mobile")

if __name__ == "__main__":
    import uvicorn
    import threading
    import time
    
    # 启动后台扫描线程，自动索引新图片元数据
    def background_scan():
        time.sleep(2) # 等待启动
        print("[System] Background scan started...")
        try:
            count = scan_folders(db)
            if count > 0:
                print(f"[System] Indexed {count} new images.")
        except Exception as e:
            print(f"[System] Background scan failed: {e}")

    threading.Thread(target=background_scan, daemon=True).start()

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"\n[Mobile Server] 局域网访问地址: http://{local_ip}:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
