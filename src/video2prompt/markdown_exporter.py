"""Markdown 按类目导出。"""

from __future__ import annotations

import re
import shutil
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Task, TaskState


@dataclass
class MarkdownExportResult:
    output_dir: Path
    zip_path: Path
    exported_task_count: int
    exported_category_count: int
    files: list[Path]


class MarkdownExporter:
    """按类目导出 Markdown 并打包 zip。"""

    UNCATEGORIZED = "未分类"
    INVALID_FILENAME_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    def __init__(self, output_root: str = "exports"):
        self.output_root = Path(output_root)

    @classmethod
    def normalize_category(cls, category: str) -> str:
        cleaned = (category or "").strip()
        return cleaned or cls.UNCATEGORIZED

    @classmethod
    def sanitize_filename(cls, text: str) -> str:
        sanitized = cls.INVALID_FILENAME_PATTERN.sub("_", text.strip())
        return sanitized or cls.UNCATEGORIZED

    @staticmethod
    def _render_markdown(category: str, tasks: list[Task]) -> str:
        chunks = [f"# {category}", ""]
        for idx, task in enumerate(tasks, start=1):
            chunks.append(f"## 视频 {idx}")
            chunks.append("")
            chunks.append(task.gemini_output)
            chunks.append("")
            chunks.append("---")
            chunks.append("")
        return "\n".join(chunks)

    @staticmethod
    def _timestamp_dirname() -> str:
        return datetime.now().strftime("%Y-%m-%d_%H%M%S")

    def export_by_category(self, tasks: list[Task]) -> MarkdownExportResult:
        completed_tasks = [
            task for task in tasks if task.state == TaskState.COMPLETED and bool(task.gemini_output)
        ]
        if not completed_tasks:
            raise ValueError("没有可导出的已完成任务（仅导出状态为“完成”且有模型输出的任务）")

        grouped: OrderedDict[str, list[Task]] = OrderedDict()
        for task in completed_tasks:
            category = self.normalize_category(task.category)
            grouped.setdefault(category, []).append(task)

        timestamp = self._timestamp_dirname()
        output_dir = self.output_root / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        files: list[Path] = []
        for category, items in grouped.items():
            file_name = f"{self.sanitize_filename(category)}.md"
            output_path = output_dir / file_name
            output_path.write_text(self._render_markdown(category, items), encoding="utf-8")
            files.append(output_path)

        zip_path = Path(shutil.make_archive(str(self.output_root / timestamp), "zip", root_dir=output_dir))
        return MarkdownExportResult(
            output_dir=output_dir,
            zip_path=zip_path,
            exported_task_count=len(completed_tasks),
            exported_category_count=len(grouped),
            files=files,
        )
