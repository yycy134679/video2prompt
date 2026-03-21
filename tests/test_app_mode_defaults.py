from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import (
    OUTPUT_FORMAT_JSON,
    OUTPUT_FORMAT_PLAIN_TEXT,
    ResolvedRunSettings,
    SESSION_TRANSLATION_COMPLIANCE_PROMPT,
    SESSION_VIDEO_PROMPT,
    SESSION_VIDEO_PROMPT_OUTPUT_FORMAT,
    build_persist_operations,
    build_controller_payload,
    build_run_settings,
    choose_translation_prompt_initial_value,
    choose_video_prompt_initial_value,
    load_prompt_template,
    normalize_runtime_prompt,
    resolve_mode_prompt,
    resolve_output_format_for_mode,
    resolve_prompt_setting_key,
    should_persist_output_format,
)
from video2prompt.review_result import DEFAULT_REVIEW_PROMPT
from video2prompt.models import AppMode


def test_translation_compliance_mode_value() -> None:
    assert AppMode.TRANSLATION_COMPLIANCE.value == "翻译合规判断"


def test_translation_compliance_mode_forces_json_output_format() -> None:
    session_state = {
        "output_format": OUTPUT_FORMAT_PLAIN_TEXT,
        SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_PLAIN_TEXT,
    }

    result = resolve_output_format_for_mode(
        AppMode.TRANSLATION_COMPLIANCE, session_state
    )

    assert result == OUTPUT_FORMAT_JSON


def test_normal_mode_restores_saved_output_format() -> None:
    session_state = {
        "output_format": OUTPUT_FORMAT_JSON,
        SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_PLAIN_TEXT,
    }

    result = resolve_output_format_for_mode(AppMode.VIDEO_PROMPT, session_state)

    assert result == OUTPUT_FORMAT_PLAIN_TEXT


def test_resolve_mode_prompt_reads_independent_session_keys() -> None:
    session_state = {
        SESSION_VIDEO_PROMPT: "普通模式提示词",
        SESSION_TRANSLATION_COMPLIANCE_PROMPT: "合规模式提示词",
    }

    assert (
        resolve_mode_prompt(
            AppMode.VIDEO_PROMPT,
            session_state,
            video_prompt_default="普通模式默认提示词",
            translation_prompt_default="合规模式默认提示词",
        )
        == "普通模式提示词"
    )
    assert (
        resolve_mode_prompt(
            AppMode.TRANSLATION_COMPLIANCE,
            session_state,
            video_prompt_default="普通模式默认提示词",
            translation_prompt_default="合规模式默认提示词",
        )
        == "合规模式提示词"
    )


def test_resolve_mode_prompt_falls_back_to_mode_specific_default() -> None:
    session_state = {}

    assert (
        resolve_mode_prompt(
            AppMode.VIDEO_PROMPT,
            session_state,
            video_prompt_default="普通模式默认提示词",
            translation_prompt_default="合规模式默认提示词",
        )
        == "普通模式默认提示词"
    )
    assert (
        resolve_mode_prompt(
            AppMode.TRANSLATION_COMPLIANCE,
            session_state,
            video_prompt_default="普通模式默认提示词",
            translation_prompt_default="合规模式默认提示词",
        )
        == "合规模式默认提示词"
    )


def test_normalize_runtime_prompt_falls_back_to_default_template_for_empty_prompt() -> (
    None
):
    assert (
        normalize_runtime_prompt("   ", DEFAULT_REVIEW_PROMPT) == DEFAULT_REVIEW_PROMPT
    )


def test_normalize_runtime_prompt_keeps_non_empty_prompt() -> None:
    assert normalize_runtime_prompt("保留原值", DEFAULT_REVIEW_PROMPT) == "保留原值"


def test_load_prompt_template_reads_file_content(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("文档提示词", encoding="utf-8")

    assert load_prompt_template(prompt_file, fallback_text="回退提示词") == "文档提示词"


def test_load_prompt_template_falls_back_when_missing(tmp_path: Path) -> None:
    assert (
        load_prompt_template(tmp_path / "missing.md", fallback_text="回退提示词")
        == "回退提示词"
    )


def test_choose_video_prompt_initial_value_prefers_saved_then_legacy_then_doc() -> None:
    assert choose_video_prompt_initial_value("saved", "legacy", "doc") == "saved"
    assert choose_video_prompt_initial_value("", "legacy", "doc") == "legacy"
    assert choose_video_prompt_initial_value("", "", "doc") == "doc"


def test_choose_translation_prompt_initial_value_prefers_saved_then_doc() -> None:
    assert choose_translation_prompt_initial_value("saved", "doc") == "saved"
    assert choose_translation_prompt_initial_value("", "doc") == "doc"


def test_resolve_prompt_setting_key_matches_mode() -> None:
    assert resolve_prompt_setting_key(AppMode.VIDEO_PROMPT) == "prompt.video_prompt"
    assert (
        resolve_prompt_setting_key(AppMode.CATEGORY_ANALYSIS) == "prompt.video_prompt"
    )
    assert (
        resolve_prompt_setting_key(AppMode.TRANSLATION_COMPLIANCE)
        == "prompt.translation_compliance"
    )


def test_should_persist_output_format_only_for_normal_modes() -> None:
    assert should_persist_output_format(AppMode.VIDEO_PROMPT) is True
    assert should_persist_output_format(AppMode.CATEGORY_ANALYSIS) is True
    assert should_persist_output_format(AppMode.TRANSLATION_COMPLIANCE) is False


def test_build_persist_operations_for_translation_mode_only_writes_prompt() -> None:
    operations = build_persist_operations(
        app_mode=AppMode.TRANSLATION_COMPLIANCE,
        prompt_text="review",
        output_format=OUTPUT_FORMAT_JSON,
    )

    assert operations == [("prompt.translation_compliance", "review")]


def test_build_persist_operations_for_video_mode_writes_prompt_and_format() -> None:
    operations = build_persist_operations(
        app_mode=AppMode.VIDEO_PROMPT,
        prompt_text="video",
        output_format=OUTPUT_FORMAT_JSON,
    )

    assert operations == [
        ("prompt.video_prompt", "video"),
        ("output_format.video_prompt", OUTPUT_FORMAT_JSON),
    ]


def test_build_run_settings_uses_normalized_prompt_for_translation_mode() -> None:
    settings = build_run_settings(
        app_mode=AppMode.TRANSLATION_COMPLIANCE,
        prompt_text="   ",
        video_prompt_default="视频模板",
        translation_prompt_default="合规模板",
        session_state={SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_PLAIN_TEXT},
    )

    assert settings.output_format == OUTPUT_FORMAT_JSON
    assert settings.prompt_text == "合规模板"


def test_build_run_settings_uses_saved_output_format_for_video_mode() -> None:
    settings = build_run_settings(
        app_mode=AppMode.VIDEO_PROMPT,
        prompt_text="自定义提示词",
        video_prompt_default="视频模板",
        translation_prompt_default="合规模板",
        session_state={SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_JSON},
    )

    assert settings.output_format == OUTPUT_FORMAT_JSON
    assert settings.prompt_text == "自定义提示词"


def test_build_controller_payload_uses_resolved_run_settings() -> None:
    payload = build_controller_payload(
        app_mode=AppMode.TRANSLATION_COMPLIANCE,
        resolved_settings=ResolvedRunSettings(
            prompt_text="合规模板",
            output_format=OUTPUT_FORMAT_JSON,
        ),
    )

    assert payload["app_mode_value"] == "翻译合规判断"
    assert payload["default_user_prompt"] == "合规模板"
    assert payload["output_format"] == OUTPUT_FORMAT_JSON
