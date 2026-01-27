import re
import json
from PIL import Image

class MetadataParser:
    @staticmethod
    def parse_image(file_path):
        """
        读取图片元数据并解析 A1111/Fooocus/ComfyUI 参数。
        """
        import os
        
        # 基础占位结果，确保即使解析失败也返回文件基本信息
        result = {
            'prompt': "",
            'negative_prompt': "",
            'loras': [], # LoRA 列表
            'params': {},
            'raw': "",
            'tool': "Unknown",
            'tech_info': {
                'file_size': f"{os.path.getsize(file_path) / 1024:.1f} KB",
            }
        }
        
        try:
            with Image.open(file_path) as img:
                info = img.info
                # 提取技术参数
                result['tech_info'].update({
                    'resolution': f"{img.width} x {img.height}",
                    'format': img.format,
                    'mode': img.mode,
                })
                
                # 1. 尝试读取 PNG 'parameters' (A1111 标准)
                if 'parameters' in info:
                    parsed = MetadataParser.parse_a1111(info['parameters'])
                    result.update(parsed)
                    return result
                
                # 2. 尝试读取 ComfyUI (PNG 'prompt')
                if 'prompt' in info:
                    parsed = MetadataParser.parse_comfyui(info['prompt'])
                    result.update(parsed)
                    return result

                # 3. 尝试读取 XMP (PNG/WebP 常见)
                # PIL 有时候会将 XMP 放在 'XML:com.adobe.xmp' 或 'xmp' 键中
                xmp_keys = [k for k in info.keys() if 'xmp' in k.lower()]
                for k in xmp_keys:
                    xmp_str = info[k]
                    if isinstance(xmp_str, bytes):
                        xmp_str = xmp_str.decode('utf-8', errors='ignore')
                    # XMP 中通常也有 parameters 字符串或者描述
                    if 'parameters' in xmp_str:
                        # 尝试从 XMP XML 中提取内容 (简单正则，XMP 通常包含 parameters 块)
                        found = re.search(r'parameters="([^"]+)"', xmp_str)
                        if found:
                            parsed = MetadataParser.parse_a1111(found.group(1))
                            result.update(parsed)
                            return result

                # 4. 尝试读取 Exif (常用 ID 探测)
                if hasattr(img, 'getexif'):
                    exif = img.getexif()
                    if exif:
                        for tag_id in [37510, 40092, 10]:
                            val = exif.get(tag_id)
                            if val:
                                text = MetadataParser._decode_exif(val)
                                if text and ("Steps:" in text or "Positive" in text):
                                    parsed = MetadataParser.parse_a1111(text)
                                    result.update(parsed)
                                    return result

                # 5. 兜底扫描其他 info 字段
                for key in ['comment', 'Description', 'Description-xmp']:
                    if key in info:
                        val = info[key]
                        if isinstance(val, bytes):
                            val = val.decode('utf-8', errors='ignore')
                        if val and len(val) > 20:
                            parsed = MetadataParser.parse_a1111(val)
                            result.update(parsed)
                            return result

        except Exception as e:
            print(f"Error parsing metadata for {file_path}: {e}")
            
        return result # 至少返回技术信息

    @staticmethod
    def _decode_exif(val):
        """解析 Exif 编码文本"""
        if isinstance(val, str):
            return val
        if isinstance(val, bytes):
            # 常见 ASCII\0\0\0 前缀
            if val.startswith(b'ASCII\0\0\0'):
                return val[8:].decode('utf-8', errors='ignore')
            # 或者是 UTF-16/Unicode 前缀
            if val.startswith(b'UNICODE\0'):
                return val[8:].decode('utf-16', errors='ignore')
            return val.decode('utf-8', errors='ignore')
        return str(val)

    @staticmethod
    def parse_comfyui(json_text):
        """
        解析 ComfyUI 的 JSON 工作流数据。
        尝试从 CLIPTextEncode 等节点中提取提示词。
        """
        result = {
            'prompt': "",
            'negative_prompt': "",
            'loras': [],
            'params': {},
            'raw': json_text,
            'tool': "ComfyUI"
        }
        
        try:
            data = json.loads(json_text)
            result['workflow'] = data 
            prompts = [] 
            
            # 1. 遍历节点寻找提示词和 LoRA
            for node_id, node in data.items():
                inputs = node.get('inputs', {})
                class_type = node.get('class_type', '').lower()
                
                # 寻找 LoRA 节点
                if 'loraloader' in class_type or 'lora' in class_type:
                    lora_name = inputs.get('lora_name') or inputs.get('model_name')
                    strength = inputs.get('strength_model') or inputs.get('strength') or 1.0
                    if lora_name:
                        result['loras'].append(f"{lora_name} ({strength})")

                # 提取 Checkpoint (模型)
                if 'checkpointloader' in class_type or 'checkpoint' in class_type:
                    ckpt = inputs.get('ckpt_name')
                    if ckpt:
                        # 移除扩展名，保持整洁
                        # result['params']['Model'] = ckpt # 这种方式可能不被 database 识别，因为它读的是 params.get('Model')
                        # 实际上 database.py 读取 parse_image 返回的 result['params']['Model']
                        # 让我们把 Model 放入 params
                        name_without_ext = ckpt.rsplit('.', 1)[0]
                        result['params']['Model'] = name_without_ext
                        result['params']['Model hash'] = "Unknown" # ComfyUI 通常不直接提供 hash

                # 提取核心参数 (KSampler)
                if class_type in ['ksampler', 'ksampleradvanced']:
                    for k in ['seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise']:
                        if k in inputs:
                            result['params'][k] = inputs[k]
                
                # 提取分辨率 (EmptyLatentImage 或 LoadImage)
                if class_type in ['emptylatentimage', 'latentupscalepython', 'latentupscale_videocf']:
                    if 'width' in inputs and 'height' in inputs:
                        result['params']['width'] = inputs['width']
                        result['params']['height'] = inputs['height']
                        result['params']['size'] = f"{inputs['width']}x{inputs['height']}"

                # 提取文本节点 (V5.5 增强：排查那些只有单个 word 的 'text'，通常它们是模型名)
                if class_type == 'cliptextencode':
                    if 'text' in inputs and isinstance(inputs['text'], str):
                        text = inputs['text'].strip()
                        # 如果文本包含逗号或空格，极大概率是提示词；如果只有一个单词且以 .sft/.ckpt 结尾，那一定是模型名
                        is_model_name = text.endswith(('.safetensors', '.ckpt', '.sft', '.pt'))
                        if len(text) > 0 and not is_model_name:
                            prompts.append((node_id, text))
                elif 'text_l' in inputs or 'text_g' in inputs: # SDXL
                    text = f"{inputs.get('text_l', '')} {inputs.get('text_g', '')}".strip()
                    if len(text) > 2:
                        prompts.append((node_id, text))

            # 2. 启发式：如果通过标准节点没找到模型，尝试遍历所有参数寻找 .safetensors/.ckpt
            if 'Model' not in result['params']:
                potential_models = []
                for node in data.values():
                    inputs = node.get('inputs', {})
                    for val in inputs.values():
                        if isinstance(val, str) and val.lower().endswith(('.safetensors', '.ckpt', '.pt')):
                            filename_lower = val.lower()
                            # 排除列表：LoRA, ControlNet, VAE, Upscaler, LLM, CLIP
                            # ComfyUI 的模型通常很乱，但主模型一般很大且名字独特
                            # 简单的黑名单过滤
                            ignore_keywords = ['lora', 'controlnet', 'vae', 'upscale', 'esrgan', 'llm', 'clip', 'bert', 't5', 'qwen', 'ae.']
                            if not any(k in filename_lower for k in ignore_keywords):
                                potential_models.append(val)
                
                if potential_models:
                    # 如果有多个候选，优先选择看起来像主模型的 (比如含 sd, xl, flux)
                    # 或者简单地取第一个
                    # 排序策略：含 'xl', 'sd', 'v1', 'real' 的优先
                    def model_score(name):
                        s = 0
                        n = name.lower()
                        if 'xl' in n: s += 2
                        if 'sd' in n: s += 2
                        if 'flux' in n: s += 3 # Flux 很火
                        if 'real' in n: s += 1
                        return s
                    
                    potential_models.sort(key=model_score, reverse=True)
                    
                    name_without_ext = potential_models[0].rsplit('.', 1)[0]
                    result['params']['Model'] = name_without_ext

            # 3. 启发式分配提示词并记录节点 ID (精准回传)
            if prompts:
                # 排序规则：倾向于认为第一个长文本是 Positive
                prompts.sort(key=lambda x: len(x[1]), reverse=True)
                result['prompt'] = prompts[0][1]
                result['prompt_node_id'] = prompts[0][0]
                if len(prompts) >= 2:
                    result['negative_prompt'] = prompts[1][1]
                    result['negative_prompt_node_id'] = prompts[1][0]
                    
        except Exception as e:
            print(f"Error parsing ComfyUI JSON: {e}")
            
        return result

    @staticmethod
    def parse_a1111(text):
        """
        解析 A1111 格式文本块
        格式通常为:
        Positive Prompt
        Negative prompt: ...
        Steps: 20, Sampler: ..., Seed: ...
        """
        result = {
            'prompt': "",
            'negative_prompt': "",
            'loras': [],
            'params': {},
            'raw': text,
            'tool': "A1111"
        }
        
        # 提取 Lora 列表
        lora_matches = re.findall(r'<lora:([^:]+):([^>]+)>', text)
        for name, weight in lora_matches:
            result['loras'].append(f"{name} ({weight})")
        
        lines = text.strip().split('\n')
        
        # 寻找包含 "Steps: " 的行作为参数行
        param_line_index = -1
        for i, line in enumerate(reversed(lines)):
            if "Steps: " in line and "Sampler: " in line:
                param_line_index = len(lines) - 1 - i
                break
        
        if param_line_index != -1:
            # 解析参数
            param_str = lines[param_line_index]
            # 简单的 split(',') 可能会被 prompt 中的逗号干扰，但 A1111 的 params 为了 key: value 格式
            # 暂时保持简单分割，完善的即使解析需要 parse_generation_parameters.js 的逻辑
            # 这里如果不包含 Negative prompt， 那么前面的都是 Positive
            
            # 解析 Key-Value 对
            # 使用正则提取 key: value 模式
            # 常见模式: Steps: 20, Sampler: DPM++ 2M Karras, CFG scale: 7, ...
            pairs = re.split(r',\s*(?=\w+:)', param_str)
            for pair in pairs:
                if ":" in pair:
                    k, v = pair.split(':', 1)
                    result['params'][k.strip()] = v.strip()
            
            # 如果参数里有 Lora hashes，也尝试记录
            if 'Lora hashes' in result['params']:
                hashes = result['params']['Lora hashes'].split(',')
                for h in hashes:
                    if ':' in h:
                        name = h.split(':')[0].strip()
                        if not any(name in L for L in result['loras']):
                            result['loras'].append(name)
            
            # Prompt 内容是参数行之前的所有内容
            content = '\n'.join(lines[:param_line_index])
        else:
            # 没有找到参数行，假设全是 Prompt
            content = text
            result['tool'] = "Unknown"

        # 分离 Prompt 和 Negative Prompt
        # A1111 使用 "Negative prompt: " 作为分隔符
        # 注意：Prompt 中可能包含换行
        
        split_token = "Negative prompt:"
        if split_token in content:
            parts = content.split(split_token)
            result['prompt'] = parts[0].strip()
            # Negative prompt 可能是剩余所有部分（如果存在多个 split_token，通常第一个是分隔符，但也可能是 prompt 内容里的）
            # A1111 中 Negative prompt 位于最后
            result['negative_prompt'] = parts[-1].strip()
            if len(parts) > 2:
                # 极其罕见情况：Prompt里写了 Negative prompt: ...
                # 我们假设最后一个分隔符才是真正的分隔符？不对，通常它是像 "Prompt\nNegative prompt: ..."
                # 让我们取第一个分隔后的后面所有内容作为 negative?
                # A1111 格式： Positive \n Negative prompt: Negative
                result['prompt'] = parts[0].strip() 
                result['negative_prompt'] = split_token.join(parts[1:]).strip()
        else:
            result['prompt'] = content.strip()
            
        return result
