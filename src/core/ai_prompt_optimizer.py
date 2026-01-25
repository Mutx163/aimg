"""
AI提示词优化器 - 使用智谱AI GLM 4.7 Flash模型
"""
import requests
import json
from typing import Optional
from PyQt6.QtCore import QSettings


class AIPromptOptimizer:
    """
    使用智谱GLM等高级模型优化ComfyUI提示词
    """
    
    API_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    MODEL = "glm-4.7-flash"
    TIMEOUT = 300  # 大幅增加到300秒，以支持 Reasoning/Thinking 模型的超长推理时间
    
    # System Prompts
    SYSTEM_PROMPT_GENERATE = """你是一位专业的AI绘画提示词高级专家。

你的任务是将用户的需求口语化转换为一段极具画面感、细节极其丰富、且完全使用中文自然语言书写的提示词。

要求:
1. 必须使用中文自然语言书写,像是在给一位画家描述一个生动的梦境或电影场景
2. 描述要极端详细：包含光影的细微变化、材质的触感、空气的流动感、人物的情绪神态、甚至微小的环境细节
3. 不要使用简单的词堆砌,要使用流畅的、富有艺术性的长难句
4. 输出为纯文本,不要使用Markdown格式
5. 直接输出这段详细的中文描述,不要添加任何解释或前缀

示例:
用户输入: "一个女孩在公园"
你的输出: "一位约二十岁的温婉少女静谧地漫步在初秋午后的城市公园领地，她身上那件淡粉色的真丝连衣裙随着微风泛起轻柔的褶皱，细碎的阳光穿过层叠的法桐叶片，在她清秀的脸庞和白皙的肩膀上洒下斑驳跳动的高质感光影。背景中远处的绿色草坪被薄雾般的日光虚化，空气中仿佛能闻到青草与泥土的清香，构图运用了电影级的黄金比例，焦点精准锁定在少女充满期待的明亮眼眸上。"
"""
    
    SYSTEM_PROMPT_OPTIMIZE = """你是一位专业的AI绘画提示词优化专家。

你的任务是根据用户的修改指令，将现有的提示词进一步丰富和美化，确保最终输出是一段极其详细、画质感极强、且完全使用中文自然语言书写的描述。

要求:
1. 保留原提示词的核心灵魂
2. 根据用户的针对性指令进行大幅度的画面增强和细节扩充
3. 必须使用流畅的高级中文自然语言书写，禁止使用简单的英文单词堆砌
4. 输出为纯文本,不要使用Markdown格式
5. 直接输出优化后的中文详细描述,不要添加任何解释或前缀

示例:
原提示词: "一名女性，户外场景"
用户指令: "让她穿商务装，在办公楼前"
你的输出: "一名气质干练的三十岁职场女性，正自信地伫立在尖端科技感十足的现代化玻璃幕墙大厦前，她笔挺的深灰色羊毛西装在冷色调的建筑背景下显得格外精致。清晨明亮的自然光打在她的侧脸上，勾勒出分明的轮廓，周围是穿梭的商务精英背景，画面充满了高级的商业摄影质感与清晰的微观细节，镜头捕捉到了大厦倒映出的云层与她胸前精致的胸针。"
"""

    SYSTEM_PROMPT_NEG_GENERATE = """你是一位专业的AI绘画负向提示词（Negative Prompt）处理专家。

你的任务是根据用户的反馈，以**中文自然语言**的形式详细描述出绝对不希望在画面中出现的元素。

要求:
1. 必须使用中文自然语言描述，描述出不想要的低质量特征或错误构图
2. 涵盖通用的避雷细节：如崩坏的肢体、模糊的纹理、比例失调的五官、廉价的塑料感、凌乱的背景、违和的水印等
3. 描述要具体，不要只说“不要模糊”，要说“避免出现那种由于对焦失败导致的奶油状模糊和边缘重影”
4. 输出为纯文本,不要使用Markdown格式
5. 直接输出这段反向描述文字，不要添加任何解释或前缀

示例:
用户输入: "不要模糊，不要多余的手指"
你的输出: "坚决杜绝画面中出现任何形式的重影、对焦模糊或低分辨率产生的马赛克质感；严禁出现扭曲变形的手指、多余的肢体关节或逻辑混乱的肌肉走向；画面中不应包含任何生硬的文字水印、签名标识或违和的后期加工痕迹，确保没有任何因构图不当导致的肢体残损或比例失调的现象。"
"""

    SYSTEM_PROMPT_NEG_OPTIMIZE = """你是一位专业的AI绘画负向提示词优化专家。

你的任务是根据用户的最新指令，对现有的反向提示词进行进一步的精细化扩充，确保生成的文字是一段逻辑清晰、详尽周全的中文自然语言描述。

要求:
1. 保留原有的核心避雷内容
2. 根据用户的额外要求，精准添加新的规避细节
3. 必须使用中文自然语言，保持描述的专业性和画面针对性
4. 输出为纯文本,不要使用Markdown格式
5. 直接输出优化后的中文详细反向描述,不要添加任何解释或前缀

示例:
原反向词: "画面模糊，肢体崩坏"
用户指令: "不要水印和文字"
你的输出: "画面应彻底隔离所有因技术瑕疵导致的结构崩坏和纹理模糊，特别要规避由于光线反射不自然产生的眩光干扰；此外，严格排除任何出现在画面角落或中央的数字水印、品牌Logo及非法文字标注，确保纯净的原创视觉呈现，不含有任何带有标签感或签名感的后期遮盖物。"
"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化优化器
        """
        settings = QSettings("ComfyUIImageManager", "Settings")
        
        # 优先使用传入的 api_key,否则从配置读取
        self.api_key = api_key if api_key else settings.value("glm_api_key", "")
        
        # 动态加载 API 地址和模型名
        # 注意: 智谱官方地址需要带 /chat/completions, 但很多服务商可能只提供到 v1 层级
        base_url = settings.value("ai_base_url", "https://open.bigmodel.cn/api/paas/v4")
        if not base_url.endswith("/chat/completions"):
            self.api_endpoint = base_url.rstrip("/") + "/chat/completions"
        else:
            self.api_endpoint = base_url
            
        self.model_name = settings.value("ai_model_name", "glm-4.7-flash")
    
    def optimize_prompt(self, user_input: str, existing_prompt: str = "", is_negative: bool = False, stream_callback: Optional[callable] = None) -> tuple[bool, str]:
        """
        优化提示词
        
        Args:
            user_input: 用户输入的需求或修改指令
            existing_prompt: 现有提示词(空则从零生成)
            is_negative: 是否为反向提示词
            stream_callback: 可选的回调函数，接收流式输出的增量内容 callback(chunk: str)
        
        Returns:
            (success, result): 成功标志和结果(成功时为优化后的提示词,失败时为错误信息)
        """
        if not user_input.strip():
            return False, "请输入需求描述"
        
        try:
            # 构建messages
            if existing_prompt.strip():
                # 优化模式
                system_prompt = self.SYSTEM_PROMPT_NEG_OPTIMIZE if is_negative else self.SYSTEM_PROMPT_OPTIMIZE
                user_message = f"原提示词: {existing_prompt}\n\n用户修改指令: {user_input}"
            else:
                # 从零生成模式
                system_prompt = self.SYSTEM_PROMPT_NEG_GENERATE if is_negative else self.SYSTEM_PROMPT_GENERATE
                user_message = user_input
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
            
            # 调用API
            result = self._call_glm_api(messages, stream_callback)
            return True, result
            
        except requests.exceptions.Timeout:
            return False, "API调用超时,请检查网络连接"
        except requests.exceptions.ConnectionError:
            return False, "网络连接失败,请检查网络"
        except Exception as e:
            return False, f"优化失败: {str(e)}"
    
    def _call_glm_api(self, messages: list, stream_callback: Optional[callable] = None) -> str:
        """
        调用 OpenAI 兼容 API
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Connection": "close"  # 显式告知服务器处理完即关闭连接，规避因连接池复用已断开连接导致的 RemoteDisconnected
        }
        
        import time
        start_time = time.time()
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.4, # 略微降低随机性，使输出更稳定
        }
        
        # 启用流式传输
        if stream_callback:
            payload["stream"] = True
        
        # 不同厂商对 max_tokens 的处理不同，有些模型（如推理型）可能需要更大的上下文或不支持显式限制
        if "thinking" not in self.model_name.lower():
             payload["max_tokens"] = 4096
        
        # 仅当使用智谱模型且显式支持时启用 thinking (避免非智谱模型报错)
        if "glm" in self.model_name.lower():
             payload["thinking"] = {"type": "enabled"}
        
        print(f"[AIOptimizer] 发起请求: {self.api_endpoint} (模型: {self.model_name}, 流式: {bool(stream_callback)})")
        
        # 使用 Session 和重试机制来增强稳定性
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        session = requests.Session()
        # 定义重试策略: 针对连接错误或特定的HTTP状态码进行重试
        # 注意: 默认情况下 Retry 不会对 POST 进行重试,因为 POST 被认为是非幂等的。
        # 在提示词优化场景下,我们可以安全地对 POST 进行重试。
        retries = Retry(
            total=3,              # 增加到3次重试
            backoff_factor=1,     # 指数回退因子 (1s, 2s, 4s...)
            status_forcelist=[500, 502, 503, 504], # 针对这些错误重试
            allowed_methods=["POST", "GET"], # 显式允许重试 POST 方法
            raise_on_status=False
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.mount("http://", HTTPAdapter(max_retries=retries))
        
        try:
            response = session.post(
                self.api_endpoint,
                headers=headers,
                json=payload,
                timeout=self.TIMEOUT,
                stream=bool(stream_callback) # 启用流式响应
            )
            # 流式模式下不直接打印状态码，等到流处理时检查
            if not stream_callback:
                print(f"[AIOptimizer] 收到响应, 状态码: {response.status_code}")

        except Exception as e:
            # 如果重试后依然失败,由于此时异常已被打印多次,这里做一个汇总输出
            print(f"[AIOptimizer] ❌ 历经重试后请求最终失败: {type(e).__name__}: {e}")
            raise
        
        # 检查HTTP状态码
        if response.status_code != 200:
            error_msg = f"API返回错误 {response.status_code}"
            
            # 特殊处理 500 错误，通常是由于模型由于生成内容过大或超时
            if response.status_code == 500:
                error_msg = "API服务器内部错误(500)。可能是由于模型生成超时或负载过高，请尝试换一个模型或稍后再试。"
            elif response.status_code == 404:
                error_msg = f"API 返回 404: 找不到接口。请检查 'API地址' 和 '模型名称' 是否配套。(当前模型: {self.model_name})"
            
            try:
                # 尝试读取部分内容来获取错误信息，注意流式模式下也要小心读取
                content = response.content
                error_data = json.loads(content)
                print(f"[AIOptimizer] 详细错误记录: {error_data}")
                if "error" in error_data:
                    # 尝试拼接更详细的服务器报错信息
                    server_detail = error_data['error'].get('message') or error_data['error'].get('err_msg') or ""
                    if server_detail:
                        error_msg += f"\n详情: {server_detail}"
            except:
                # 无法解析为 JSON，打印原始文本前部
                print(f"[AIOptimizer] 响应文本(前500字): {response.text[:500]}")
            
            raise Exception(error_msg)
        
        # === 流式处理逻辑 ===
        if stream_callback:
            full_content = ""
            try:
                for line in response.iter_lines():
                    if not line:
                        continue
                        
                    decoded_line = line.decode('utf-8').strip()
                    if decoded_line.startswith("data: "):
                        data_str = decoded_line[6:]
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk_data = json.loads(data_str)
                            if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                                delta = chunk_data["choices"][0].get("delta", {})
                                chunk_content = delta.get("content", "")
                                
                                # 忽略 reasoning_content (思考过程)
                                # 如果需要显示思考过程，可以在这里处理 reasoning_content
                                
                                if chunk_content:
                                    full_content += chunk_content
                                    stream_callback(chunk_content)
                        except json.JSONDecodeError:
                            continue
                            
                print(f"[AIOptimizer] 流式生成结束, 总长: {len(full_content)}")
                return full_content.strip()
                
            except Exception as e:
                print(f"[AIOptimizer] 流式处理中断: {e}")
                raise Exception(f"流式处理失败: {e}")

        # === 普通处理逻辑 ===
        # 解析响应
        try:
            data = response.json()
            print(f"[AIOptimizer] 响应解析成功")
            # 调试输出: 在返回空结果时打印完整数据
            if "choices" not in data or len(data["choices"]) == 0:
                raise Exception("API返回格式错误: 'choices'字段缺失或为空")
            
            msg_obj = data["choices"][0].get("message", {})
            content = msg_obj.get("content") or ""
            content = content.strip()
            
            if not content:
                print(f"[AIOptimizer] 警告: content为空! 完整响应数据: {json.dumps(data, ensure_ascii=False)}")
                # 尝试从 reasoning_content 获取 (某些 Thinking 模型可能在特定情况下只返回推理)
                reasoning = msg_obj.get("reasoning_content") or ""
                reasoning = reasoning.strip()
                if reasoning:
                    print(f"[AIOptimizer] 发现 reasoning_content，但正文 content 为空")
                    # 如果正文为空但有推理，检查是否有 <think> 标签包裹。如果没有，有时模型会误把结果放这里
                    if not content and reasoning:
                        # 尝试启发式提取：如果推理内容很长且没看到明显的思考过程，或者为了容错暂时借用
                        # 但对于提示词优化，如果确定 content 为空，直接反馈失败可能更安全
                        pass
            
            # 清理推理标签 (如 <think>...</think>)
            import re
            result = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            
            # 如果清理后为空，且原 content 有内容，说明内容全是思考
            if not result and content:
                 print(f"[AIOptimizer] ⚠️ 响应内容经清理后为空（仅包含思考过程）")
                 
            print(f"[AIOptimizer] 优化成功,生成{len(result)}字符")
            return result
        except Exception as e:
            print(f"[AIOptimizer] ❌ JSON解析或数据提取失败: {e}")
            print(f"[AIOptimizer] 响应文本: {response.text[:500]}")
            raise Exception(f"API返回格式错误或数据提取失败: {e}")
