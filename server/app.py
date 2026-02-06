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
from contextlib import asynccontextmanager
import uuid
import threading
import time
import requests as py_requests

# Removed sys.path hack. Expecting PYTHONPATH to be set correctly by launcher.

from src.core.database import DatabaseManager
from src.core.metadata import MetadataParser
from src.core.ai_prompt_optimizer import AIPromptOptimizer
from src.assets.default_workflows import DEFAULT_T2I_WORKFLOW
from src.core.scanner import ImageScanner

# Default; will be overwritten by main args
COMFY_ADDRESS = "127.0.0.1:8189"
CLIENT_ID = "aimg_web_" + str(uuid.uuid4())[:8] # Persistent ID for this session

# --- Global Progress Tracker ---
class ProgressTracker:
    def __init__(self):
        self.current_task_id = None
        self.value = 0
        self.max = 0
        self.node_id = None
        self.is_connected = False

    def reset(self):
        self.current_task_id = None
        self.value = 0
        self.max = 0
        self.node_id = None

    async def connect_ws(self):
        # Local import to avoid dependency issues if not installed
        try:
            import websockets
        except ImportError:
            print("[WS] 错误: 缺失 'websockets' 库，请运行 pip install websockets")
            return

        while True:
            try:
                uri = f"ws://{COMFY_ADDRESS}/ws?clientId={CLIENT_ID}"
                async with websockets.connect(uri) as websocket:
                    self.is_connected = True
                    print(f"[WS] 已连接到 ComfyUI (ID: {CLIENT_ID})")
                    while True:
                        message = await websocket.recv()
                        data = json.loads(message)
                        
                        msg_type = data.get('type')
                        if msg_type == 'executing':
                            self.node_id = data['data'].get('node')
                            self.current_task_id = data['data'].get('prompt_id')
                            if self.node_id is None: # Execution done
                                print(f"[WS] 任务执行完毕: {self.current_task_id}")
                                self.reset()
                                # 触发自动扫描，让新图立即出现
                                threading.Thread(target=scanner.scan_folders, daemon=True).start()
                        
                        elif msg_type == 'progress':
                            self.value = data['data'].get('value', 0)
                            self.max = data['data'].get('max', 0)
                            # print(f"[WS] 进度: {self.value}/{self.max}")
                            
                        elif msg_type == 'execution_error':
                            print("[WS] 采样报错，重置进度")
                            self.reset()
            except Exception as e:
                self.is_connected = False
                self.reset()
                # print(f"[WS] 连接中断，5秒后重试: {e}")
                await asyncio.sleep(5)

progress_tracker = ProgressTracker()

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
    seed: int = -1 
    denoise: float = 1.0
    batch_size: int = 1
    shift: float = 3.0

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(progress_tracker.connect_ws())
    yield
    task.cancel()

app = FastAPI(title="AI Image Viewer Mobile API", lifespan=lifespan)

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 强制不缓存静态文件和 API
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/image/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.url.path.startswith("/api/image/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

db = DatabaseManager()
ai_optimizer = AIPromptOptimizer()
scanner = ImageScanner(db)

# --- Core Logic ---

def validate_path_security(path: str):
    normalized_path = os.path.normpath(path).replace("\\", "/")
    info = db.get_image_info(normalized_path)
    if not info:
         raise HTTPException(status_code=403, detail="Access Denied: File not indexed.")
    return normalized_path

@app.get("/api/images")
async def get_images(
    keyword: str = "", folder: Optional[str] = None, 
    model: Optional[str] = None, lora: Optional[str] = None, 
    sort: str = "time_desc", page: int = 1, page_size: int = 30
):
    all_paths = db.search_images(keyword=keyword, folder_path=folder, model=model, lora=lora, order_by=sort)
    start_idx = (page - 1) * page_size
    valid_images = []
    current_idx = start_idx
    target_paths = []
    while len(target_paths) < page_size and current_idx < len(all_paths):
        path = all_paths[current_idx]
        if os.path.exists(path): target_paths.append(path)
        current_idx += 1
    batch_info = db.get_images_batch_info(target_paths)
    for path in target_paths:
        info = batch_info.get(path, {})
        valid_images.append({
            "file_path": path,
            "file_name": os.path.basename(path),
            "width": info.get('width', 0) or 0,
            "height": info.get('height', 0) or 0,
        })
    return {"total": len(all_paths), "page": page, "page_size": page_size, "images": valid_images, "has_more": current_idx < len(all_paths)}

@app.get("/api/image/raw")
async def get_raw_image(path: str):
    validate_path_security(path)
    normalized_path = os.path.normpath(path)
    if not os.path.exists(normalized_path): raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(normalized_path)

@app.get("/api/metadata")
async def get_metadata(path: str):
    normalized_path = os.path.normpath(path)
    db_path = normalized_path.replace("\\", "/")
    info = db.get_image_info(db_path)
    if info:
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
            },
            "tech_info": { "resolution": f"{info.get('width', 0)}x{info.get('height', 0)}" },
            "tool": "Database"
        }
    if not os.path.exists(normalized_path): raise HTTPException(status_code=404, detail="Image not found")
    res = MetadataParser.parse_image(normalized_path)
    threading.Thread(target=db.add_image, args=(normalized_path, res)).start()
    return res

@app.get("/api/filters")
async def get_filters():
    return {
        "folders": db.get_unique_folders(),
        "models": [row[0] for row in db.get_unique_models()],
        "loras": [row[0] for row in db.get_unique_loras()],
        "resolutions": [f"{r[0]}x{r[1]}" for r in db.get_unique_resolutions()],
        "samplers": db.get_unique_samplers(),
        "schedulers": db.get_unique_schedulers()
    }

@app.get("/api/comfy/samplers_schedulers")
async def get_comfy_samplers_schedulers():
    """Fetch real-time supported samplers and schedulers from ComfyUI, with DB fallback."""
    try:
        # Try to get from KSampler node info
        resp = py_requests.get(f"http://{COMFY_ADDRESS}/object_info/KSampler", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            input_req = data.get("KSampler", {}).get("input", {}).get("required", {})
            samplers = input_req.get("sampler_name", [[]])[0]
            schedulers = input_req.get("scheduler", [[]])[0]
            return {"samplers": samplers, "schedulers": schedulers}
    except Exception:
        pass
    
    # Fallback to DB
    return {
        "samplers": db.get_unique_samplers(),
        "schedulers": db.get_unique_schedulers()
    }

@app.get("/api/comfy/queue")
async def get_full_queue():
    try:
        queue_resp = py_requests.get(f"http://{COMFY_ADDRESS}/queue", timeout=2)
        queue_data = queue_resp.json()
        pending_tasks = []
        running_items = queue_data.get("queue_running", [])
        pending_items = queue_data.get("queue_pending", [])
        for i, item in enumerate(running_items + pending_items):
            prompt_id = item[1]
            task_info = {"id": prompt_id, "status": "running" if item in running_items else "pending", "prompt": "任务中...", "lora_info": "", "progress": 0, "progress_text": ""}
            if task_info["status"] == "running":
                task_info["progress"] = (progress_tracker.value / progress_tracker.max * 100) if progress_tracker.max > 0 else 0
                task_info["progress_text"] = f"{progress_tracker.value}/{progress_tracker.max}"
            if len(item) >= 3:
                prompt_data = item[2]
                if "6" in prompt_data:
                    text = prompt_data["6"].get("inputs", {}).get("text", "")
                    task_info["prompt"] = text[:30] + "..." if len(text) > 30 else text
                if "28" in prompt_data:
                    inputs = prompt_data["28"].get("inputs", {})
                    l_name = inputs.get("lora_name", "")
                    if l_name.endswith(".safetensors"): l_name = l_name[:-12]
                    if l_name: task_info["lora_info"] = f"{l_name} ({inputs.get('strength_model', 1.0)})"
            pending_tasks.append(task_info)
        return {"pending": pending_tasks, "queue_remaining": queue_data.get("exec_info", {}).get("queue_remaining", 0)}
    except Exception as e: return {"pending": [], "queue_remaining": 0}

@app.post("/api/comfy/interrupt")
async def interrupt_task():
    try:
        resp = py_requests.post(f"http://{COMFY_ADDRESS}/interrupt", timeout=5)
        return {"success": resp.status_code == 200}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/comfy/cancel_task")
async def cancel_task(data: Dict[str, Any] = Body(...)):
    prompt_id = data.get("prompt_id")
    try:
        payload = {"delete": [prompt_id]}
        resp = py_requests.post(f"http://{COMFY_ADDRESS}/queue", json=payload, timeout=5)
        return {"success": resp.status_code == 200}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

from src.core.comfy_client import ComfyClient

@app.post("/api/comfy/generate")
async def generate_image(req: GenerateRequest):
    try:
        wf = json.loads(json.dumps(DEFAULT_T2I_WORKFLOW))
        
        # 使用 Python 端的“轮子”进行工作流随机化处理
        # 如果 seed 为 -1，ComfyClient.randomize_workflow_seeds 会处理它
        if req.seed == -1:
            wf = ComfyClient.randomize_workflow_seeds(wf)
            # 提取随机化后的第一个 seed 供日志参考
            # (由于 randomize_workflow_seeds 处理了所有采样节点，我们只需注入其他参数)
        else:
            # 如果是固定种子，手动注入
            pass
            
        w, h = map(int, req.resolution.split('x'))
        
        # 注入其他参数
        if "3" in wf:
            wf["3"]["inputs"].update({
                "steps": req.steps, 
                "cfg": req.cfg, 
                "sampler_name": req.sampler, 
                "scheduler": req.scheduler, 
                "denoise": req.denoise
            })
            # 如果是固定种子，覆盖掉
            if req.seed != -1:
                wf["3"]["inputs"]["seed"] = req.seed
                
        if "5" in wf: wf["5"]["inputs"].update({"width": w, "height": h, "batch_size": req.batch_size})
        if "6" in wf: wf["6"]["inputs"]["text"] = req.prompt
        if "7" in wf: wf["7"]["inputs"]["text"] = req.negative_prompt
        
        if req.model:
            model_target = req.model if (req.model.endswith(".safetensors") or req.model.endswith(".ckpt")) else req.model + ".safetensors"
            if "16" in wf: wf["16"]["inputs"]["unet_name"] = model_target
            
        if req.lora:
            lora_target = req.lora if (req.lora.endswith(".safetensors") or req.lora.endswith(".ckpt")) else req.lora + ".safetensors"
            if "28" in wf:
                wf["28"]["inputs"].update({"lora_name": lora_target, "strength_model": req.lora_weight})
        elif "28" in wf:
            wf["28"]["inputs"]["strength_model"] = 0.0
        
        # 使用统一的 CLIENT_ID 提交
        p = {"prompt": wf, "client_id": CLIENT_ID}
        resp = py_requests.post(f"http://{COMFY_ADDRESS}/prompt", json=p, timeout=5)
        if resp.status_code == 200: return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except Exception as e: 
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@app.post("/api/ai/optimize")
async def ai_optimize(request: Request):
    try:
        data = await request.json()
        mode, user_input, existing_prompt, image_b64 = data.get("mode", "generate"), data.get("user_input", ""), data.get("existing_prompt", ""), data.get("image_b64", "")
        custom_system_prompt = data.get("system_prompt")
        from src.core.ai_prompt_optimizer import AIPromptOptimizer
        optimizer = AIPromptOptimizer()
        messages = []
        if mode == "image":
            messages = optimizer.construct_image_prompt_messages(image_b64)
        else:
            if mode == "generate": default_sys = optimizer.SYSTEM_PROMPT_GENERATE
            elif mode == "optimize": default_sys = optimizer.SYSTEM_PROMPT_OPTIMIZE
            elif mode == "negative": default_sys = optimizer.SYSTEM_PROMPT_NEG_OPTIMIZE if existing_prompt else optimizer.SYSTEM_PROMPT_NEG_GENERATE
            else: default_sys = ""
            system_prompt = custom_system_prompt or default_sys
            if mode == "generate": messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
            elif mode == "optimize": messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"原提示词: {existing_prompt}\n\n指令: {user_input}"}]
            elif mode == "negative": messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"原反向词: {existing_prompt}\n\n指令: {user_input}" if existing_prompt else user_input}]

        async def generate():
            try:
                import httpx
                payload = {"model": optimizer.model_name, "messages": messages, "temperature": 0.4, "stream": True}
                if "thinking" not in optimizer.model_name.lower(): payload["max_tokens"] = 4096
                if "glm" in optimizer.model_name.lower(): payload["thinking"] = {"type": "enabled"}
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream("POST", optimizer.api_endpoint, headers={"Authorization": f"Bearer {optimizer.api_key}"}, json=payload) as response:
                        if response.status_code != 200:
                            yield f"data: {json.dumps({'error': f'API Error {response.status_code}'})}\n\n"; return
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]": break
                                try:
                                    chunk_json = json.loads(data_str)
                                    if "choices" in chunk_json:
                                        chunk = chunk_json["choices"][0]["delta"].get("content", "")
                                        if chunk: yield f"data: {json.dumps({'chunk': chunk.replace('**','').replace('*','').replace('`','')})}\n\n"
                                except: continue
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e: yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e: return {"error": str(e)}

@app.post("/api/scan")
async def trigger_scan():
    try:
        count = scanner.scan_folders()
        return {"success": True, "new_images": count}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/image/thumb")
def get_thumbnail(path: str, size: int = 768):
    validate_path_security(path)
    normalized_path = os.path.normpath(path)
    if not os.path.exists(normalized_path): raise HTTPException(status_code=404, detail="Original image not found")
    import hashlib
    from PIL import Image
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cache_dir = os.path.join(base_dir, ".thumbs")
    os.makedirs(cache_dir, exist_ok=True)
    file_hash = hashlib.md5(path.replace("\\", "/").encode('utf-8')).hexdigest()
    mtime = int(os.path.getmtime(normalized_path))
    thumb_path = os.path.join(cache_dir, f"{file_hash}_{mtime}_w{size}.webp")
    if os.path.exists(thumb_path): return FileResponse(thumb_path)
    try:
        with Image.open(normalized_path) as img:
            img.thumbnail((min(size, 2560), min(size, 2560)), resample=getattr(Image, 'Resampling', Image).LANCZOS)
            img.save(thumb_path, "WEBP", quality=85)
        return FileResponse(thumb_path)
    except: return FileResponse(normalized_path)

@app.delete("/api/image")
async def delete_image(path: str):
    try:
        from send2trash import send2trash
        safe_path = os.path.normpath(os.path.abspath(path))
        if os.path.exists(safe_path): send2trash(safe_path)
        db_path = safe_path.replace("\\", "/")
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        conn.cursor().execute("DELETE FROM images WHERE file_path = ?", (db_path,))
        conn.commit(); conn.close()
        return {"success": True}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

web_dist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")
if os.path.exists(web_dist_path):
    app.mount("/", StaticFiles(directory=web_dist_path, html=True), name="web")

if __name__ == "__main__":
    import uvicorn
    from src.utils.network import get_local_ip
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-scan", action="store_true", help="Disable initial folder scan on startup")
    parser.add_argument("--comfy-host", type=str, default="127.0.0.1", help="ComfyUI host")
    parser.add_argument("--comfy-port", type=str, default="8189", help="ComfyUI port")
    args = parser.parse_args()
    
    # Update global config
    COMFY_ADDRESS = f"{args.comfy_host}:{args.comfy_port}"
    print(f"[API] Configured ComfyUI Address: {COMFY_ADDRESS}")
    
    # only start initial scan if not disabled (Desktop app handles scanning usually)
    if not args.no_scan:
        threading.Thread(target=lambda: (time.sleep(2), scanner.scan_folders()), daemon=True).start()
    
    uvicorn.run(app, host="0.0.0.0", port=args.port)
