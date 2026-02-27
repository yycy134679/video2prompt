"""视频审查结果解析与格式化。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_REVIEW_PROMPT = """你是短视频翻译可行性审查助手。请逐项检查视频并严格输出 JSON，不要输出任何额外说明。

检查项：
1. 儿童进行口播或商品介绍（儿童口播）
2. 口播人物声音切换，或男声变女声口播（多人口播）
3. 口播或画面出现明确价格/促销活动（明确价格/促销信息）
4. 画面中是否出现超过 1 个中文字符：
   - 字幕：底部跟随口播内容的文字（不影响翻译）
   - 贴纸/花字：装饰性叠加文字（不能翻译）
   - 其他：包装或背景中的文字（不影响翻译）

判定规则：
- 若 1/2/3 任一项为“有”，或“贴纸/花字”为“有”，则“能否翻译”为“不能”；
- 否则“能否翻译”为“能”。

输出 JSON Schema（字段名必须一致）：
{
  "结论": {
    "能否翻译": "能/不能"
  },
  "信息": {
    "儿童口播": "有/无",
    "多人口播": "有/无",
    "明确价格/促销信息": "有/无",
    "中文字符": {
      "字幕": "有/无",
      "贴纸/花字": "有/无",
      "其他": "有/无"
    },
    "说明": [
      {
        "时间点": "可选，如 00:03",
        "内容": "可选，简要说明画面或口播内容"
      }
    ]
  }
}

要求：
- 所有布尔判断字段只能输出“有”或“无”。
- 仅输出一个 JSON 对象；不要使用 Markdown 代码块。"""

_YES_SET = {
    "有",
    "是",
    "true",
    "yes",
    "y",
    "1",
    "出现",
    "包含",
    "命中",
}
_NO_SET = {
    "无",
    "否",
    "false",
    "no",
    "n",
    "0",
    "未出现",
    "没有",
    "未命中",
}
_CAN_SET = {
    "能",
    "可以",
    "可翻译",
    "允许翻译",
}
_CANNOT_SET = {
    "不能",
    "不可以",
    "不可翻译",
    "禁止翻译",
}


@dataclass
class ReviewResult:
    """结构化审查结果。"""

    can_translate: str
    child_voiceover: str
    multi_voiceover: str
    explicit_price_promo: str
    chinese_subtitle: str
    chinese_sticker: str
    chinese_other: str
    notes: list[str] = field(default_factory=list)

    def to_summary(self) -> str:
        """转为便于人工查看的文本摘要。"""

        lines = [
            f"1. 儿童口播：{self.child_voiceover}",
            f"2. 多人口播：{self.multi_voiceover}",
            f"3. 明确价格/促销信息：{self.explicit_price_promo}",
            "4. 中文字符：",
            f"- 字幕：{self.chinese_subtitle}",
            f"- 贴纸/花字：{self.chinese_sticker}",
            f"- 其他（如商品包装）：{self.chinese_other}",
        ]
        if self.notes:
            lines.append("说明：")
            for note in self.notes:
                if note:
                    lines.append(f"- {note}")
        return "\n".join(lines)


def split_review_columns(raw_text: str) -> tuple[str, str]:
    """将模型输出拆分为“能否翻译”和“可读摘要”。"""

    text = (raw_text or "").strip()
    if not text:
        return "", ""

    payload = _parse_json_payload(text)
    if isinstance(payload, dict):
        result = _parse_from_json(payload)
        return result.can_translate, result.to_summary()

    result, recognized = _parse_from_legacy_text(text)
    if recognized:
        return result.can_translate, result.to_summary()
    return "", text


def parse_review_output(raw_text: str) -> ReviewResult:
    """解析模型输出，无法结构化时返回空结果。"""

    text = (raw_text or "").strip()
    if not text:
        return _empty_result()

    payload = _parse_json_payload(text)
    if isinstance(payload, dict):
        return _parse_from_json(payload)

    result, recognized = _parse_from_legacy_text(text)
    return result if recognized else _empty_result()


def extract_can_translate(text: str) -> str:
    """从任意输出文本中提取“能否翻译”。"""

    can_translate, _ = split_review_columns(text)
    return can_translate


def _empty_result() -> ReviewResult:
    return ReviewResult(
        can_translate="",
        child_voiceover="无",
        multi_voiceover="无",
        explicit_price_promo="无",
        chinese_subtitle="无",
        chinese_sticker="无",
        chinese_other="无",
        notes=[],
    )


def _parse_json_payload(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", candidate)
        candidate = re.sub(r"\n```$", "", candidate)
        candidate = candidate.strip()

    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except ValueError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        payload = json.loads(candidate[start : end + 1])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _normalize_yes_no(value: Any, default: str = "无") -> str:
    if isinstance(value, bool):
        return "有" if value else "无"
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in _YES_SET:
        return "有"
    if text in _NO_SET:
        return "无"
    if any(token in text for token in ("有", "是", "true", "yes", "出现", "包含")):
        return "有"
    if any(token in text for token in ("无", "否", "false", "no", "未", "没有")):
        return "无"
    return default


def _normalize_can_translate(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in _CAN_SET:
        return "能"
    if text in _CANNOT_SET:
        return "不能"
    if "不能" in text or "不可" in text:
        return "不能"
    if "能" in text or "可" in text:
        return "能"
    return ""


def _normalize_notes(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        note = value.strip()
        return [note] if note else []

    if isinstance(value, dict):
        time_text = str(_pick(value, "时间点", "time", "timestamp", "time_point") or "").strip()
        content_text = str(_pick(value, "内容", "content", "desc", "description") or "").strip()
        if time_text and content_text:
            return [f"{time_text} {content_text}"]
        if content_text:
            return [content_text]
        if time_text:
            return [time_text]
        return []

    if isinstance(value, list):
        notes: list[str] = []
        for item in value:
            notes.extend(_normalize_notes(item))
        return [note for note in notes if note]

    text = str(value).strip()
    return [text] if text else []


def _compute_can_translate(
    child_voiceover: str,
    multi_voiceover: str,
    explicit_price_promo: str,
    chinese_sticker: str,
    declared: str,
) -> tuple[str, str]:
    computed = "不能" if "有" in {child_voiceover, multi_voiceover, explicit_price_promo, chinese_sticker} else "能"
    if declared and declared != computed:
        return computed, f"模型原结论为“{declared}”，已按规则修正为“{computed}”。"
    return computed, ""


def _parse_from_json(payload: dict[str, Any]) -> ReviewResult:
    conclusion = _pick(payload, "结论", "conclusion")
    if not isinstance(conclusion, dict):
        conclusion = {}

    info = _pick(payload, "信息", "details", "detail")
    if not isinstance(info, dict):
        info = payload

    chinese = _pick(info, "中文字符", "chinese_text", "chinese_chars")
    if not isinstance(chinese, dict):
        chinese = {}

    child_voiceover = _normalize_yes_no(
        _pick(info, "儿童口播", "child_voiceover", "child_narration", "child_presenter"),
    )
    multi_voiceover = _normalize_yes_no(
        _pick(info, "多人口播", "multi_voiceover", "multiple_speakers", "voice_switch", "gender_switch"),
    )
    explicit_price_promo = _normalize_yes_no(
        _pick(info, "明确价格/促销信息", "价格促销", "price_promo", "explicit_price_promo"),
    )
    chinese_subtitle = _normalize_yes_no(
        _pick(chinese, "字幕", "subtitle", "captions"),
    )
    chinese_sticker = _normalize_yes_no(
        _pick(chinese, "贴纸/花字", "贴纸花字", "sticker", "decorative_text", "overlay_text"),
    )
    chinese_other = _normalize_yes_no(
        _pick(chinese, "其他", "其他文字", "other", "packaging_text", "background_text"),
    )

    declared = _normalize_can_translate(
        _pick(conclusion, "能否翻译", "can_translate", "translation_allowed", "可翻译")
    )
    notes = _normalize_notes(_pick(info, "说明", "notes", "time_points", "evidence"))

    can_translate, mismatch_note = _compute_can_translate(
        child_voiceover=child_voiceover,
        multi_voiceover=multi_voiceover,
        explicit_price_promo=explicit_price_promo,
        chinese_sticker=chinese_sticker,
        declared=declared,
    )
    if mismatch_note:
        notes = [mismatch_note, *notes]

    return ReviewResult(
        can_translate=can_translate,
        child_voiceover=child_voiceover,
        multi_voiceover=multi_voiceover,
        explicit_price_promo=explicit_price_promo,
        chinese_subtitle=chinese_subtitle,
        chinese_sticker=chinese_sticker,
        chinese_other=chinese_other,
        notes=notes,
    )


def _extract_label_yes_no(text: str, label: str) -> str:
    pattern = rf"{re.escape(label)}(?:（[^）]*）)?\s*[:：]\s*(有|无|是|否|true|false|yes|no)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return "无"
    return _normalize_yes_no(match.group(1), default="无")


def _parse_from_legacy_text(text: str) -> tuple[ReviewResult, bool]:
    recognized = any(key in text for key in ("儿童口播", "多人口播", "明确价格", "贴纸/花字", "能否翻译"))

    child_voiceover = _extract_label_yes_no(text, "儿童口播")
    multi_voiceover = _extract_label_yes_no(text, "多人口播")
    explicit_price_promo = _extract_label_yes_no(text, "明确价格/促销信息")
    chinese_subtitle = _extract_label_yes_no(text, "字幕")
    chinese_sticker = _extract_label_yes_no(text, "贴纸/花字")
    chinese_other = _extract_label_yes_no(text, "其他")

    declared_match = re.search(r"能否翻译\s*[:：]\s*(能|不能|可以|不可以|可翻译|不可翻译)", text)
    declared = _normalize_can_translate(declared_match.group(1) if declared_match else "")

    can_translate, mismatch_note = _compute_can_translate(
        child_voiceover=child_voiceover,
        multi_voiceover=multi_voiceover,
        explicit_price_promo=explicit_price_promo,
        chinese_sticker=chinese_sticker,
        declared=declared,
    )

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    notes: list[str] = []
    if lines and recognized:
        for line in lines:
            if line.startswith(("能否翻译", "1.", "2.", "3.", "4.", "- 字幕", "- 贴纸/花字", "- 其他", "说明")):
                continue
            notes.append(line)

    if mismatch_note:
        notes = [mismatch_note, *notes]

    result = ReviewResult(
        can_translate=can_translate,
        child_voiceover=child_voiceover,
        multi_voiceover=multi_voiceover,
        explicit_price_promo=explicit_price_promo,
        chinese_subtitle=chinese_subtitle,
        chinese_sticker=chinese_sticker,
        chinese_other=chinese_other,
        notes=notes,
    )
    return result, recognized
