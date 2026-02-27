from __future__ import annotations

from video2prompt.review_result import extract_can_translate, split_review_columns


def test_split_review_columns_from_json() -> None:
    raw = """
{
  "结论": {"能否翻译": "能"},
  "信息": {
    "儿童口播": "无",
    "多人口播": "无",
    "明确价格/促销信息": "有",
    "中文字符": {"字幕": "有", "贴纸/花字": "无", "其他": "有"},
    "说明": [{"时间点": "00:06", "内容": "口播提到拍1发3"}]
  }
}
    """.strip()

    can_translate, summary = split_review_columns(raw)
    assert can_translate == "不能"
    assert "1. 儿童口播：无" in summary
    assert "3. 明确价格/促销信息：有" in summary
    assert "00:06 口播提到拍1发3" in summary


def test_split_review_columns_legacy_text() -> None:
    raw = """
能否翻译：能
1. 儿童口播：有
2. 多人口播：无
3. 明确价格/促销信息：无
4. 中文字符：
- 字幕：无
- 贴纸/花字：无
- 其他（如商品包装）：无
    """.strip()

    can_translate, summary = split_review_columns(raw)
    # 按规则应修正为“不能”
    assert can_translate == "不能"
    assert "1. 儿童口播：有" in summary


def test_split_review_columns_plain_text_passthrough() -> None:
    raw = "this is plain output"
    can_translate, summary = split_review_columns(raw)
    assert can_translate == ""
    assert summary == raw
    assert extract_can_translate(raw) == ""

