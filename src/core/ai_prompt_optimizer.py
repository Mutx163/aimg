"""
AI prompt optimizer with optional LoRA trigger guidance.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import requests
from PyQt6.QtCore import QSettings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class AIPromptOptimizer:
    API_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    MODEL = "glm-4.7-flash"
    TIMEOUT = 300

    SYSTEM_PROMPT_GENERATE = (
        "你是专业的AI绘图提示词专家。"
        "请把用户需求改写为一段自然中文提示词。"
        "如果给了LoRA触发词，优先把触发词贴在人物主体前，写成“触发词+的+人物主体”。"
        "不要把触发词改写成“某某风格”。"
        "只输出最终提示词，不要解释。"
    )

    SYSTEM_PROMPT_OPTIMIZE = (
        "你是专业的AI绘图提示词优化专家。"
        "请根据用户新需求改写已有提示词。"
        "如果冲突，以用户新需求为最高优先级。"
        "默认必须保留原提示词中的主体、人数、背景场景、服饰、姿态和构图。"
        "只有当用户明确要求“替换/改成/换成/删除/去掉”时，才允许改这些核心元素。"
        "如果有LoRA触发词，触发词必须贴在人物主体描述前，不要写成“触发词风格”。"
        "只输出最终提示词，不要解释。"
    )

    SYSTEM_PROMPT_NEG_GENERATE = (
        "你是专业的AI绘图反向提示词专家。"
        "请输出中文关键词列表，用中文逗号分隔，只输出结果。"
    )

    SYSTEM_PROMPT_NEG_OPTIMIZE = (
        "你是专业的AI绘图反向提示词优化专家。"
        "请基于已有反向提示词按用户要求增删关键词。"
        "输出中文关键词列表，用中文逗号分隔，只输出结果。"
    )

    SYSTEM_PROMPT_IMAGE_TO_PROMPT = (
        "你是专业的AI绘图提示词分析专家。"
        "请根据图片内容输出一段细节丰富的中文提示词。"
        "必须覆盖：主体外观、服饰材质与颜色、姿态动作、背景环境、光线氛围、镜头景别/构图、人物朝向、道具摆放与相对位置。"
        "输出一整段自然中文，不要分点，不要解释，不要英文标签。"
        "必须明确人物朝向（面向左/右/镜头）以及手部与道具的相对位置。"
        "不要使用问号或列表符号，统一使用中文逗号连接短语。"
        "长度尽量在120~220字。"
    )

    _STYLE_HINTS = (
        "style",
        "lighting",
        "camera",
        "cinematic",
        "quality",
        "masterpiece",
        "风格",
        "镜头",
        "光线",
        "质感",
        "构图",
        "氛围",
    )

    _LIGHT_OPT_TOKENS = (
        "一键优化",
        "优化一下",
        "优化",
        "增强细节",
        "提升清晰",
        "提高清晰",
        "润色",
        "polish",
        "enhance",
        "refine",
    )

    def __init__(self, api_key: Optional[str] = None):
        settings = QSettings("ComfyUIImageManager", "Settings")
        self.api_key = api_key if api_key else settings.value("glm_api_key", "")

        base_url = settings.value("ai_base_url", "https://open.bigmodel.cn/api/paas/v4")
        base_url = str(base_url or "").strip()
        if not base_url.endswith("/chat/completions"):
            self.api_endpoint = base_url.rstrip("/") + "/chat/completions"
        else:
            self.api_endpoint = base_url

        self.model_name = str(settings.value("ai_model_name", self.MODEL))

    def optimize_prompt(
        self,
        user_input: str,
        existing_prompt: str = "",
        is_negative: bool = False,
        stream_callback: Optional[callable] = None,
        lora_guidance: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        if not (user_input or "").strip():
            return False, "请输入需求描述"

        try:
            if (existing_prompt or "").strip():
                system_prompt = self.SYSTEM_PROMPT_NEG_OPTIMIZE if is_negative else self.SYSTEM_PROMPT_OPTIMIZE
                user_message = f"原提示词：{existing_prompt}\n\n用户修改指令：{user_input}"
            else:
                system_prompt = self.SYSTEM_PROMPT_NEG_GENERATE if is_negative else self.SYSTEM_PROMPT_GENERATE
                user_message = user_input

            # One-click optimize should not rewrite scene/character/clothes.
            if (not is_negative) and (existing_prompt or "").strip() and self._is_light_optimize_request(user_input):
                result = self._light_optimize_preserve(existing_prompt, lora_guidance)
                return True, result

            if (not is_negative) and (existing_prompt or "").strip():
                user_message += (
                    "\n\n保留规则："
                    "默认锁定人物主体、背景场景、服饰、姿态、镜头构图；"
                    "除非用户明确说要替换，否则只允许润色和补细节；"
                    "用户已经写明的人物、背景、服饰和动作短语尽量原词保留，不要改成同义词。"
                )

            if not is_negative:
                lora_instruction = self._build_lora_instruction(lora_guidance)
                if lora_instruction:
                    system_prompt = (
                        f"{system_prompt}\n\n"
                        "LoRA constraints:\n"
                        "1. 必须保留指定触发词原文，不可改写。\n"
                        "2. 不允许输出LoRA文件名、模型名、版本号。\n"
                        "3. 不要把触发词替换成近义词或派生词。\n"
                        "4. 除非用户明确要求，不要强行加“某某风格”。\n"
                        "5. 输出一段自然中文。"
                    )
                    user_message = f"{user_message}\n\n{lora_instruction}"

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            result = self._call_glm_api(messages, stream_callback)
            if is_negative:
                return True, self._trim_negative_keywords(result, max_items=30)

            result = self._strip_format_markers(result)
            result = self._sanitize_prompt_punctuation(result)
            result = self._replace_lora_aliases_with_triggers(result, lora_guidance)
            result = self._remove_non_trigger_lora_aliases(result, lora_guidance)
            result = self._dedupe_prompt(result)
            result = self._ensure_lora_extras_present(result, lora_guidance)
            result = self._enforce_trigger_subject_phrase(result, lora_guidance)
            result = self._sanitize_prompt_punctuation(result)
            return True, result

        except requests.exceptions.Timeout:
            return False, "AI请求超时，请检查网络后重试"
        except requests.exceptions.ConnectionError:
            return False, "AI网络连接失败，请检查网络后重试"
        except Exception as exc:
            return False, f"优化失败: {exc}"

    def generate_prompt_from_image(
        self,
        image_b64: str,
        stream_callback: Optional[callable] = None,
        lora_guidance: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        if not image_b64:
            return False, "未获取到有效图片"
        try:
            messages = self.construct_image_prompt_messages(image_b64, lora_guidance=lora_guidance)
            result = self._call_glm_api(messages, stream_callback)
            result = self._strip_format_markers(result)
            result = self._sanitize_prompt_punctuation(result)
            result = self._enrich_image_prompt_if_too_short(result)
            result = self._ensure_spatial_layout_clauses(result)
            result = self._replace_lora_aliases_with_triggers(result, lora_guidance)
            result = self._remove_non_trigger_lora_aliases(result, lora_guidance)
            result = self._dedupe_prompt(result)
            result = self._ensure_lora_extras_present(result, lora_guidance)
            result = self._enforce_trigger_subject_phrase(result, lora_guidance)
            result = self._sanitize_prompt_punctuation(result)
            return True, result
        except requests.exceptions.Timeout:
            return False, "AI请求超时，请检查网络后重试"
        except requests.exceptions.ConnectionError:
            return False, "AI网络连接失败，请检查网络后重试"
        except Exception as exc:
            return False, f"图生文失败: {exc}"

    def construct_image_prompt_messages(
        self,
        image_b64: str,
        lora_guidance: Optional[Dict[str, Any]] = None,
    ) -> list:
        user_text = (
            "请根据图片生成可直接用于文生图的一段中文提示词。"
            "要求细节充分、信息完整，至少覆盖：人物/主体、服装、动作、场景、光线、镜头构图、人物朝向（面向左/右/镜头）、道具与人体和环境的相对位置。"
            "请明确写出人物面向方向、左右手动作、道具在人物左侧/右侧/前方/后方的位置关系。"
            "不要输出问号，统一使用中文逗号。"
            "输出一段完整中文，不要分点。"
        )
        lora_instruction = self._build_lora_instruction(lora_guidance)
        if lora_instruction:
            user_text += f"\n\n{lora_instruction}"
        return [
            {"role": "system", "content": self.SYSTEM_PROMPT_IMAGE_TO_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}},
                ],
            },
        ]

    def _call_glm_api(self, messages: list, stream_callback: Optional[callable] = None) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Connection": "close",
        }

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.4,
        }
        if stream_callback:
            payload["stream"] = True
        if "thinking" not in self.model_name.lower():
            payload["max_tokens"] = 4096
        if "glm" in self.model_name.lower():
            payload["thinking"] = {"type": "enabled"}

        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["POST", "GET"],
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.mount("http://", HTTPAdapter(max_retries=retries))

        response = session.post(
            self.api_endpoint,
            headers=headers,
            json=payload,
            timeout=self.TIMEOUT,
            stream=bool(stream_callback),
        )

        if response.status_code != 200:
            msg = f"API返回错误 {response.status_code}"
            try:
                err = response.json()
                if isinstance(err, dict):
                    eobj = err.get("error", err)
                    detail = ""
                    if isinstance(eobj, dict):
                        detail = str(eobj.get("message") or eobj.get("err_msg") or "")
                    if detail:
                        msg += f": {detail}"
            except Exception:
                pass
            raise RuntimeError(msg)

        if stream_callback:
            return self._consume_stream_response(response, stream_callback)

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("API响应缺少 choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            chunks: List[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if text:
                        chunks.append(str(text))
            content = "".join(chunks)
        return str(content).strip()

    def _consume_stream_response(self, response: requests.Response, stream_callback: callable) -> str:
        full_text = ""
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = str(raw_line).strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except Exception:
                continue
            choices = data.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            chunk = delta.get("content", "")
            if not chunk:
                continue
            if isinstance(chunk, list):
                texts: List[str] = []
                for part in chunk:
                    if isinstance(part, dict) and part.get("text"):
                        texts.append(str(part["text"]))
                chunk = "".join(texts)
            chunk = str(chunk)
            full_text += chunk
            stream_callback(chunk)
        return full_text.strip()

    def _strip_format_markers(self, text: str) -> str:
        text = text or ""
        for marker in ("**", "*", "`", "__", "~~"):
            text = text.replace(marker, "")
        return text.strip()

    def _sanitize_prompt_punctuation(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return cleaned
        cleaned = cleaned.replace("？", "，").replace("?", "，")
        cleaned = cleaned.replace("；", "，").replace(";", "，")
        cleaned = cleaned.replace("、", "，")
        cleaned = re.sub(r"[，,\s]*[。\.]+[，,\s]*", "，", cleaned)
        cleaned = re.sub(r"[，,\s]{2,}", "，", cleaned)
        cleaned = cleaned.strip("，, ")
        parts = self._split_prompt_pieces(cleaned)
        return "，".join(parts) if parts else cleaned

    def _trim_negative_keywords(self, text: str, max_items: int = 30) -> str:
        if not text:
            return text
        parts = self._split_prompt_pieces(text)
        seen = set()
        cleaned: List[str] = []
        for item in parts:
            norm = self._normalize_piece(item)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            cleaned.append(item)
            if len(cleaned) >= max_items:
                break
        return "，".join(cleaned)

    def _split_prompt_pieces(self, prompt: str) -> List[str]:
        if not prompt:
            return []
        parts = re.split(r"[,，;；。\.\n!?！？]+", prompt)
        return [p.strip() for p in parts if p and p.strip()]

    def _normalize_piece(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip()).lower()
        normalized = re.sub(r"[，,;；。.!！？?\-_/|]+", "", normalized)
        return normalized

    def _dedupe_prompt(self, prompt: str) -> str:
        parts = self._split_prompt_pieces(prompt)
        if not parts:
            return (prompt or "").strip()
        seen = set()
        deduped: List[str] = []
        for part in parts:
            norm = self._normalize_piece(part)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            deduped.append(part)
        return "，".join(deduped) if deduped else (prompt or "").strip()

    def _enrich_image_prompt_if_too_short(self, prompt: str) -> str:
        text = (prompt or "").strip()
        if len(text) >= 70:
            return text
        parts = self._split_prompt_pieces(text)
        existing = {self._normalize_piece(p) for p in parts}
        enrich_terms = [
            "主体细节清晰",
            "服饰材质与颜色明确",
            "姿态自然",
            "背景环境完整",
            "光线层次分明",
            "画面构图稳定",
        ]
        for term in enrich_terms:
            norm = self._normalize_piece(term)
            if norm and norm not in existing:
                parts.append(term)
                existing.add(norm)
        return "，".join(parts) if parts else text

    def _ensure_spatial_layout_clauses(self, prompt: str) -> str:
        text = (prompt or "").strip()
        if not text:
            return text

        parts = self._split_prompt_pieces(text)
        if not parts:
            return text

        normalized_text = " ".join(self._normalize_piece(p) for p in parts)
        additions: List[str] = []

        direction_keywords = ("朝向", "面向", "看向", "视线", "侧身", "转向")
        if not any(keyword in normalized_text for keyword in direction_keywords):
            additions.append("人物面向镜头略偏右，视线聚焦主体动作")

        position_keywords = ("相对位置", "左侧", "右侧", "前方", "后方", "前景", "中景", "后景")
        if not any(keyword in normalized_text for keyword in position_keywords):
            additions.append("主体位于中景，道具位于人物手部前侧，前景与背景层次清晰")

        if not additions:
            return text
        return self._dedupe_prompt("，".join(parts + additions))

    def _is_light_optimize_request(self, user_input: str) -> bool:
        text = (user_input or "").strip().lower()
        if not text:
            return False
        # If user explicitly asks to replace core elements, do not use conservative one-click mode.
        hard_change_words = ("替换", "改成", "换成", "删除", "去掉", "remove", "replace", "change")
        if any(w in text for w in hard_change_words):
            return False
        return any(token in text for token in self._LIGHT_OPT_TOKENS)

    def _light_optimize_preserve(self, existing_prompt: str, lora_guidance: Optional[Dict[str, Any]]) -> str:
        base = self._strip_format_markers(existing_prompt or "")
        parts = self._split_prompt_pieces(base)
        if not parts:
            parts = [base.strip()] if base.strip() else []

        quality_terms = [
            "高细节",
            "清晰对焦",
            "自然光影",
            "真实质感",
            "构图稳定",
        ]
        existing = {self._normalize_piece(p) for p in parts}
        for term in quality_terms:
            norm = self._normalize_piece(term)
            if norm and norm not in existing:
                parts.append(term)
                existing.add(norm)

        merged = "，".join([p for p in parts if p])
        merged = self._replace_lora_aliases_with_triggers(merged, lora_guidance)
        merged = self._remove_non_trigger_lora_aliases(merged, lora_guidance)
        merged = self._dedupe_prompt(merged)
        merged = self._ensure_lora_extras_present(merged, lora_guidance)
        merged = self._enforce_trigger_subject_phrase(merged, lora_guidance)
        return merged

    def _extract_lora_extras(self, lora_guidance: Optional[Dict[str, Any]]) -> List[str]:
        if not isinstance(lora_guidance, dict):
            return []
        extras: List[str] = []
        seen = set()

        for text in lora_guidance.get("extras", []) or []:
            candidate = str(text or "").strip()
            if not candidate:
                continue
            norm = self._normalize_piece(candidate)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            extras.append(candidate)

        for item in lora_guidance.get("loras", []) or []:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("auto_use_prompt", True)):
                continue
            candidate = str(item.get("prompt", "") or "").strip()
            if not candidate:
                continue
            norm = self._normalize_piece(candidate)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            extras.append(candidate)
        return extras

    def _build_lora_instruction(self, lora_guidance: Optional[Dict[str, Any]]) -> str:
        extras = self._extract_lora_extras(lora_guidance)
        if not extras:
            return ""
        lines = ["必须包含以下LoRA触发词（逐字保留，不可改写）："]
        for text in extras:
            lines.append(f"- {text}")
        lines.append("触发词要贴在人物主体前，例如“触发词的年轻女子/触发词的女性”。")
        lines.append("如果原文中有其它LoRA触发词，请移除，只保留以上触发词。")
        lines.append("每个触发词最多出现1次，并自然融入人物描述，禁止单独重复罗列触发词。")
        lines.append("不要写“触发词风格、触发词风格强烈”等描述。")
        lines.append("禁止输出LoRA文件名、模型名、版本后缀。")
        return "\n".join(lines)

    def _collect_lora_alias_mappings(self, lora_guidance: Optional[Dict[str, Any]]) -> List[tuple[str, str]]:
        if not isinstance(lora_guidance, dict):
            return []

        mappings: List[tuple[str, str]] = []
        for item in lora_guidance.get("loras", []) or []:
            if not isinstance(item, dict):
                continue
            trigger = str(item.get("prompt", "") or "").strip()
            name = str(item.get("name", "") or "").strip()
            if not trigger or not name:
                continue

            aliases = {name}
            base = os.path.basename(name)
            aliases.add(base)
            stem, _ = os.path.splitext(base)
            if stem:
                aliases.add(stem)
                for token in re.split(r"[-_.\s]+", stem):
                    token = token.strip()
                    if len(token) >= 2:
                        aliases.add(token)

            norm_trigger = self._normalize_piece(trigger)
            for alias in aliases:
                alias = str(alias or "").strip()
                if not alias:
                    continue
                if self._normalize_piece(alias) == norm_trigger:
                    continue
                mappings.append((alias, trigger))

        mappings.sort(key=lambda x: len(x[0]), reverse=True)
        return mappings

    def _replace_lora_aliases_with_triggers(self, prompt: str, lora_guidance: Optional[Dict[str, Any]]) -> str:
        if not prompt:
            return prompt
        mappings = self._collect_lora_alias_mappings(lora_guidance)
        if not mappings:
            return prompt

        updated = prompt
        for alias, trigger in mappings:
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])"
            updated = re.sub(pattern, trigger, updated, flags=re.IGNORECASE)
        return updated

    def _remove_non_trigger_lora_aliases(self, prompt: str, lora_guidance: Optional[Dict[str, Any]]) -> str:
        if not prompt or not isinstance(lora_guidance, dict):
            return prompt

        triggers_norm = {self._normalize_piece(item) for item in self._extract_lora_extras(lora_guidance)}
        if not triggers_norm:
            return prompt

        aliases: List[str] = []
        for item in lora_guidance.get("loras", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue

            base = os.path.basename(name)
            stem, _ = os.path.splitext(base)
            candidates = {name, base, stem}
            candidates.update(token.strip() for token in re.split(r"[-_.\s]+", stem) if token.strip())

            for alias in candidates:
                norm_alias = self._normalize_piece(alias)
                if not norm_alias or norm_alias in triggers_norm:
                    continue
                if alias.isdigit():
                    continue
                if len(alias) < 3 and not re.search(r"[\u4e00-\u9fff]", alias):
                    continue
                aliases.append(alias)

        cleaned = prompt
        for alias in sorted(set(aliases), key=len, reverse=True):
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])"
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        return self._sanitize_prompt_punctuation(cleaned)

    def _pick_smart_insert_index(self, prompt_pieces: List[str]) -> int:
        if len(prompt_pieces) <= 1:
            return len(prompt_pieces)
        for idx, piece in enumerate(prompt_pieces):
            norm = self._normalize_piece(piece)
            if any(hint in norm for hint in self._STYLE_HINTS):
                return idx
        return min(2, len(prompt_pieces))

    def _ensure_lora_extras_present(self, prompt: str, lora_guidance: Optional[Dict[str, Any]]) -> str:
        extras = self._extract_lora_extras(lora_guidance)
        if not extras:
            return prompt

        parts = self._split_prompt_pieces(prompt)
        if not parts:
            return "，".join(extras)

        existing = {self._normalize_piece(p) for p in parts}
        missing: List[str] = []
        for extra in extras:
            norm = self._normalize_piece(extra)
            if norm and norm not in existing:
                existing.add(norm)
                missing.append(extra)
        if not missing:
            return self._keep_single_trigger_occurrence(self._dedupe_prompt(prompt), extras)

        insert_at = self._pick_smart_insert_index(parts)
        merged = parts[:insert_at] + missing + parts[insert_at:]
        merged_prompt = self._dedupe_prompt("，".join(merged))
        return self._keep_single_trigger_occurrence(merged_prompt, extras)

    def _keep_single_trigger_occurrence(self, prompt: str, triggers: List[str]) -> str:
        text = (prompt or "").strip()
        if not text or not triggers:
            return text

        for trigger in triggers:
            t = str(trigger or "").strip()
            if not t:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(t)}(?![A-Za-z0-9_])", re.IGNORECASE)
            matches = list(pattern.finditer(text))
            if len(matches) <= 1:
                continue
            rebuilt: List[str] = []
            last_idx = 0
            for idx, m in enumerate(matches):
                if idx == 0:
                    rebuilt.append(text[last_idx:m.end()])
                else:
                    rebuilt.append(text[last_idx:m.start()])
                last_idx = m.end()
            rebuilt.append(text[last_idx:])
            text = "".join(rebuilt)

        text = re.sub(r"\s*[，,]\s*[。\.]+\s*", "，", text)
        text = re.sub(r"\s*[。\.]+\s*[，,]\s*", "，", text)
        text = re.sub(r"[，,]\s*[，,]+", "，", text)
        text = re.sub(r"\s{2,}", " ", text).strip("，, ")
        parts = self._split_prompt_pieces(text)
        if parts:
            text = "，".join(parts)
        return text

    def _enforce_trigger_subject_phrase(self, prompt: str, lora_guidance: Optional[Dict[str, Any]]) -> str:
        text = (prompt or "").strip()
        if not text:
            return text

        extras = self._extract_lora_extras(lora_guidance)
        if not extras:
            return text
        trigger = str(extras[0] or "").strip()
        if not trigger:
            return text

        # Remove common malformed wording like "yy风格", keep trigger token only.
        text = re.sub(
            rf"{re.escape(trigger)}\s*风格(?:化)?[^，。；;]*",
            trigger,
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            rf"以\s*{re.escape(trigger)}\s*为?风格[^，。；;]*",
            trigger,
            text,
            flags=re.IGNORECASE,
        )

        subject_re = r"(年轻女子|年轻女性|女子|女性|女孩|女人|女孩子|人物)"
        anchored_re = re.compile(rf"{re.escape(trigger)}\s*的?\s*{subject_re}", re.IGNORECASE)
        if anchored_re.search(text):
            return self._sanitize_prompt_punctuation(self._keep_single_trigger_occurrence(text, [trigger]))

        mention_re = re.compile(rf"(一位|一个|一名)?\s*{subject_re}")

        def _repl(match: re.Match) -> str:
            quantifier = match.group(1) or ""
            subject = match.group(2)
            return f"{quantifier}{trigger}的{subject}"

        text, replaced = mention_re.subn(_repl, text, count=1)
        if replaced == 0:
            return self._sanitize_prompt_punctuation(self._keep_single_trigger_occurrence(text, [trigger]))

        text = self._keep_single_trigger_occurrence(text, [trigger])
        return self._sanitize_prompt_punctuation(text)
