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

你的任务是将用户的需求口语化转换为一段细节丰富、画面清晰、且完全使用中文自然语言书写的提示词。

要求:
1. 必须使用中文自然语言书写，不要出现英文单词
2. 必须严格遵循用户指令，用户提到的服饰、发型、场景、动作等必须明确写入
3. 如果用户指定“换成/改成/必须是”等强指令，必须把该元素放在句首强调，并删除任何与之冲突的描述
4. 输出为纯文本，不要使用Markdown格式，不要添加解释或前缀，不要使用星号或其他标记符号
5. 描述要具体可视化，包含材质、颜色、款式与穿着部位

示例:
用户输入: "一个女孩在公园，换成JK制服"
你的输出: "必须是日式高中女生的JK制服风格：白色衬衫搭配深色百褶短裙，领口系着整齐的领结或蝴蝶结，肩部有挺括的水手领或西式校服翻领，整体穿着干净利落，站立在清爽的公园小径上，晨光柔和，人物五官清晰，画面细节丰富。"
"""
    
    SYSTEM_PROMPT_OPTIMIZE = """你是一位专业的AI绘画提示词优化专家。

你的任务是根据用户的修改指令，直接重写并优化现有提示词，输出为中文自然语言。

要求:
1. 严格执行用户的修改指令，涉及服装、姿态、场景的要求必须明确写入
2. 对强指令必须替换掉原冲突内容，不允许保留矛盾服饰或场景
3. 用户指令中的关键元素必须放在句首强调
4. 输出为纯文本，不要使用Markdown格式，不要添加解释，不要使用星号或其他标记符号
5. 保留原提示词的主体风格，但以用户指令为最高优先级

示例:
原提示词: "一名女孩穿休闲连衣裙，街景"
用户指令: "换成JK制服"
你的输出: "必须是日式高中女生的JK制服风格：白色衬衫搭配深色百褶短裙，领口系着整齐的领结或蝴蝶结，校服线条利落清晰；人物依然在城市街景中，但服装已完全替换为JK制服，画面细节清楚，氛围明亮。"
"""

    SYSTEM_PROMPT_NEG_GENERATE = """你是一位专业的AI绘画负向提示词（Negative Prompt）处理专家。

你的任务是根据用户的反馈，输出“中文关键词列表”形式的反向提示词。

要求:
1. 必须使用中文关键词或短语，使用中文逗号分隔
2. 只输出关键词列表，不要使用长句，不要使用解释
3. 覆盖常见问题：模糊、重影、马赛克、噪点、崩坏肢体、比例失调、五官扭曲、皮肤塑料感、水印、文字、Logo、背景杂乱等
4. 如果用户特别强调某些不要项，必须优先放在列表前部
5. 输出为纯文本，不要使用Markdown格式
6. 最多输出30个关键词，优先保留最关键的问题

示例:
用户输入: "不要模糊，不要多余的手指"
你的输出: "模糊，重影，马赛克，多余手指，手指扭曲，肢体崩坏，比例失调，五官扭曲，低清晰度，噪点，水印，文字"
"""

    SYSTEM_PROMPT_NEG_OPTIMIZE = """你是一位专业的AI绘画负向提示词优化专家。

你的任务是根据用户的最新指令，对现有的反向提示词进行扩充，输出为“中文关键词列表”。

要求:
1. 保留原有核心避雷内容
2. 根据用户的额外要求，精准添加新的关键词
3. 必须使用中文关键词或短语，使用中文逗号分隔
4. 只输出关键词列表，不要使用长句或解释
5. 输出为纯文本，不要使用Markdown格式
6. 最多输出30个关键词，优先保留最关键的问题

示例:
原反向词: "画面模糊，肢体崩坏"
用户指令: "不要水印和文字"
你的输出: "画面模糊，重影，低清晰度，肢体崩坏，多余手指，五官扭曲，水印，文字，Logo"
"""

    SYSTEM_PROMPT_IMAGE_TO_PROMPT = """你是一位专业的AI绘画提示词分析专家。

你的任务是根据用户提供的图片，输出一段细节丰富、画面清晰、且完全使用中文自然语言书写的提示词。

要求:
1. 必须使用中文自然语言书写，不要出现英文单词
2. 必须准确描述人物、服饰、发型、场景、动作、光线与构图
3. 输出为纯文本，不要使用Markdown格式，不要添加解释或前缀，不要使用星号或其他标记符号
4. 描述要具体可视化，包含材质、颜色、款式与穿着部位
5. 画面元素尽量完整：主体外观、表情神态、姿态与肢体动作、镜头视角与景别、背景与环境细节、光源方向与质感、色彩与氛围
6. 不要臆造图片中不存在的元素
7. 用完整的一段话表达，不要分段
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
            if is_negative:
                result = self._trim_negative_keywords(result, max_items=30)
            else:
                result = self._strip_format_markers(result)
            return True, result
            
        except requests.exceptions.Timeout:
            return False, "API调用超时,请检查网络连接"
        except requests.exceptions.ConnectionError:
            return False, "网络连接失败,请检查网络"
        except Exception as e:
            return False, f"优化失败: {str(e)}"

    def _strip_format_markers(self, text: str) -> str:
        if not text:
            return text
        for marker in ["**", "*", "`", "__", "~~"]:
            text = text.replace(marker, "")
        return text.strip()

    def _trim_negative_keywords(self, text: str, max_items: int = 30) -> str:
        if not text:
            return text
        import re
        parts = re.split(r"[,\n，、;；]+", text)
        seen = set()
        cleaned = []
        for item in parts:
            kw = item.strip()
            if not kw:
                continue
            if kw in seen:
                continue
            seen.add(kw)
            cleaned.append(kw)
            if len(cleaned) >= max_items:
                break
        return "，".join(cleaned)
    
    def generate_prompt_from_image(self, image_b64: str, stream_callback: Optional[callable] = None) -> tuple[bool, str]:
        if not image_b64:
            return False, "未获取到有效图片"
        try:
            messages = self.construct_image_prompt_messages(image_b64)
            result = self._call_glm_api(messages, stream_callback)
            result = self._strip_format_markers(result)
            return True, result
        except requests.exceptions.Timeout:
            return False, "API调用超时,请检查网络连接"
        except requests.exceptions.ConnectionError:
            return False, "网络连接失败,请检查网络"
        except Exception as e:
            return False, f"图生文失败: {str(e)}"
    
    def construct_image_prompt_messages(self, image_b64: str) -> list:
        """构建图生文的消息列表"""
        system_prompt = self.SYSTEM_PROMPT_IMAGE_TO_PROMPT
        user_content = [
            {"type": "text", "text": "请根据图片内容生成中文提示词"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}}
        ]
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

    
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
