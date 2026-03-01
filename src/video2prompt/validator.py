"""输入解析与校验。"""

from __future__ import annotations

from .models import TaskInput, ValidationResult


class InputValidator:
    """输入校验器。"""

    VALID_DOMAINS = ("douyin", "iesdouyin")
    UNCATEGORIZED = "未分类"

    @staticmethod
    def parse_lines(pid_text: str, link_text: str) -> list[TaskInput]:
        pid_lines = pid_text.splitlines() if pid_text else []
        link_lines = link_text.splitlines() if link_text else []

        max_len = max(len(pid_lines), len(link_lines))
        items: list[TaskInput] = []
        for idx in range(max_len):
            pid = pid_lines[idx].strip() if idx < len(pid_lines) else ""
            link = link_lines[idx].strip() if idx < len(link_lines) else ""

            if not pid and not link:
                continue

            if not link:
                items.append(TaskInput(pid=pid, link=link, is_valid=False, error="链接为空"))
                continue

            if not InputValidator.validate_link(link):
                items.append(TaskInput(pid=pid, link=link, is_valid=False, error="无效抖音链接"))
                continue

            items.append(TaskInput(pid=pid, link=link, is_valid=True))

        return items

    @staticmethod
    def validate_link(link: str) -> bool:
        lower = link.lower()
        return any(domain in lower for domain in InputValidator.VALID_DOMAINS)

    @staticmethod
    def validate_line_count(pid_lines: list[str], link_lines: list[str]) -> ValidationResult:
        pid_count = sum(1 for line in pid_lines if line.strip())
        link_count = sum(1 for line in link_lines if line.strip())
        if pid_count != link_count:
            return ValidationResult(
                is_valid=False,
                pid_count=pid_count,
                link_count=link_count,
                error_message=f"pid 非空行数({pid_count}) 与链接非空行数({link_count})不一致",
            )
        return ValidationResult(is_valid=True, pid_count=pid_count, link_count=link_count)

    @staticmethod
    def parse_lines_with_category(pid_text: str, link_text: str, category_text: str) -> list[TaskInput]:
        pid_lines = pid_text.splitlines() if pid_text else []
        link_lines = link_text.splitlines() if link_text else []
        category_lines = category_text.splitlines() if category_text else []

        max_len = max(len(pid_lines), len(link_lines), len(category_lines))
        items: list[TaskInput] = []
        for idx in range(max_len):
            pid = pid_lines[idx].strip() if idx < len(pid_lines) else ""
            link = link_lines[idx].strip() if idx < len(link_lines) else ""
            category = category_lines[idx].strip() if idx < len(category_lines) else ""

            if not pid and not link and not category:
                continue

            if not link:
                items.append(
                    TaskInput(
                        pid=pid,
                        link=link,
                        category=category or InputValidator.UNCATEGORIZED,
                        is_valid=False,
                        error="链接为空",
                    )
                )
                continue

            if not InputValidator.validate_link(link):
                items.append(
                    TaskInput(
                        pid=pid,
                        link=link,
                        category=category or InputValidator.UNCATEGORIZED,
                        is_valid=False,
                        error="无效抖音链接",
                    )
                )
                continue

            items.append(
                TaskInput(
                    pid=pid,
                    link=link,
                    category=category or InputValidator.UNCATEGORIZED,
                    is_valid=True,
                )
            )

        return items

    @staticmethod
    def validate_line_count_with_category(
        pid_lines: list[str], link_lines: list[str], category_lines: list[str]
    ) -> ValidationResult:
        max_len = max(len(pid_lines), len(link_lines), len(category_lines))
        pid_count = 0
        link_count = 0
        category_count = 0

        for idx in range(max_len):
            pid = pid_lines[idx].strip() if idx < len(pid_lines) else ""
            link = link_lines[idx].strip() if idx < len(link_lines) else ""
            category = category_lines[idx].strip() if idx < len(category_lines) else ""
            if not pid and not link and not category:
                continue

            if pid:
                pid_count += 1
            if link:
                link_count += 1
            # 类目允许空值（空类目导出时归为“未分类”），但行占位仍计入对齐校验。
            if category or pid or link:
                category_count += 1

        if pid_count != link_count or link_count != category_count:
            return ValidationResult(
                is_valid=False,
                pid_count=pid_count,
                link_count=link_count,
                category_count=category_count,
                error_message=(
                    f"pid 非空行数({pid_count})、链接非空行数({link_count})、"
                    f"类目有效行数({category_count})不一致"
                ),
            )

        return ValidationResult(
            is_valid=True,
            pid_count=pid_count,
            link_count=link_count,
            category_count=category_count,
        )
