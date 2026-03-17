from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from video2prompt.markdown_exporter import MarkdownExporter
from video2prompt.models import Task, TaskState


def test_export_by_category_generate_markdown_and_zip(tmp_path: Path) -> None:
    tasks = [
        Task(
            pid="p-001",
            original_link="https://www.douyin.com/video/1",
            category="服饰",
            state=TaskState.COMPLETED,
            model_output="脚本A",
        ),
        Task(
            pid="p-002",
            original_link="https://www.douyin.com/video/2",
            category="服饰",
            state=TaskState.COMPLETED,
            model_output="脚本B",
        ),
        Task(
            pid="p-003",
            original_link="https://www.douyin.com/video/3",
            category="",
            state=TaskState.COMPLETED,
            model_output="脚本C\n第二行",
        ),
        Task(
            pid="p-004",
            original_link="https://www.douyin.com/video/4",
            category="3C/数码",
            state=TaskState.COMPLETED,
            model_output="脚本D",
        ),
        Task(
            pid="p-005",
            original_link="https://www.douyin.com/video/5",
            category="美妆",
            state=TaskState.FAILED,
            model_output="脚本E",
        ),
    ]

    exporter = MarkdownExporter(output_root=str(tmp_path))
    result = exporter.export_by_category(tasks)

    assert result.exported_task_count == 4
    assert result.exported_category_count == 3
    assert result.output_dir.exists()
    assert result.zip_path.exists()

    fashion_md = result.output_dir / "服饰.md"
    uncategorized_md = result.output_dir / "未分类.md"
    digital_md = result.output_dir / "3C_数码.md"
    assert fashion_md.exists()
    assert uncategorized_md.exists()
    assert digital_md.exists()

    fashion_text = fashion_md.read_text(encoding="utf-8")
    assert fashion_text.startswith("# 服饰\n")
    assert fashion_text.count("## 视频 ") == 2
    assert fashion_text.index("脚本A") < fashion_text.index("脚本B")

    uncategorized_text = uncategorized_md.read_text(encoding="utf-8")
    assert "脚本C\n第二行" in uncategorized_text

    with ZipFile(result.zip_path) as zip_file:
        names = set(zip_file.namelist())
        assert {"服饰.md", "未分类.md", "3C_数码.md"}.issubset(names)


def test_export_by_category_raise_when_no_completed_task(tmp_path: Path) -> None:
    tasks = [
        Task(
            pid="p-001",
            original_link="https://www.douyin.com/video/1",
            category="服饰",
            state=TaskState.FAILED,
            model_output="脚本A",
        )
    ]
    exporter = MarkdownExporter(output_root=str(tmp_path))

    with pytest.raises(ValueError):
        exporter.export_by_category(tasks)
