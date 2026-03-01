from __future__ import annotations

from video2prompt.validator import InputValidator


def test_validate_line_count_with_category_allow_empty_category_cell() -> None:
    pid_lines = ["p1", "p2"]
    link_lines = ["https://www.douyin.com/video/1", "https://www.douyin.com/video/2"]
    category_lines = ["服饰", ""]

    result = InputValidator.validate_line_count_with_category(pid_lines, link_lines, category_lines)

    assert result.is_valid
    assert result.pid_count == 2
    assert result.link_count == 2
    assert result.category_count == 2


def test_validate_line_count_with_category_detect_mismatch() -> None:
    pid_lines = ["p1"]
    link_lines = ["https://www.douyin.com/video/1", "https://www.douyin.com/video/2"]
    category_lines = ["服饰", "美妆"]

    result = InputValidator.validate_line_count_with_category(pid_lines, link_lines, category_lines)

    assert not result.is_valid
    assert result.pid_count == 1
    assert result.link_count == 2
    assert result.category_count == 2


def test_parse_lines_with_category_skip_all_empty_rows_and_fill_uncategorized() -> None:
    pid_text = "p1\n\np2"
    link_text = "https://www.douyin.com/video/1\n\nhttps://www.douyin.com/video/2"
    category_text = "服饰\n\n"

    items = InputValidator.parse_lines_with_category(pid_text, link_text, category_text)

    assert len(items) == 2
    assert items[0].is_valid
    assert items[0].category == "服饰"
    assert items[1].is_valid
    assert items[1].category == InputValidator.UNCATEGORIZED


def test_parse_lines_with_category_keep_invalid_item() -> None:
    pid_text = "p1"
    link_text = "https://example.com/video/1"
    category_text = ""

    items = InputValidator.parse_lines_with_category(pid_text, link_text, category_text)

    assert len(items) == 1
    assert not items[0].is_valid
    assert items[0].error == "无效抖音链接"
    assert items[0].category == InputValidator.UNCATEGORIZED
