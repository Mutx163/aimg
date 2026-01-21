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

                # 提取核心参数 (KSampler)
                if class_type in ['ksampler', 'ksampleradvanced']:
                    for k in ['seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise']:
                        if k in inputs:
                            result['params'][k] = inputs[k]

                # 提取文本
                if 'text' in inputs and isinstance(inputs['text'], str):
                    text = inputs['text'].strip()
                    if len(text) > 2:
                        prompts.append(text)
                elif 'text_l' in inputs or 'text_g' in inputs: # SDXL
                    text = f"{inputs.get('text_l', '')} {inputs.get('text_g', '')}".strip()
                    if len(text) > 2:
                        prompts.append(text)

            # 2. 启发式分配提示词
            # ComfyUI 中通常第一个加载的文本是 Positive，第二个是 Negative
            if prompts:
                result['prompt'] = prompts[0]
                if len(prompts) >= 2:
                    result['negative_prompt'] = prompts[1]
                    
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
