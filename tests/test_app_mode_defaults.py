from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app

from app import (
    OUTPUT_FORMAT_JSON,
    OUTPUT_FORMAT_PLAIN_TEXT,
    ResolvedRunSettings,
    SETTING_CATEGORY_ANALYSIS_PROMPT_CUSTOM_ENABLED,
    SETTING_VIDEO_PROMPT_CUSTOM_ENABLED,
    SESSION_CATEGORY_ANALYSIS_PROMPT,
    SESSION_TRANSLATION_COMPLIANCE_PROMPT,
    SESSION_VIDEO_PROMPT,
    SESSION_VIDEO_PROMPT_OUTPUT_FORMAT,
    build_persist_operations,
    build_controller_payload,
    build_run_settings,
    choose_category_prompt_initial_value,
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _reset_cache_db() -> None:
    cache_db = _repo_root() / "data" / "cache.db"
    if cache_db.exists():
        cache_db.unlink()


def _new_app_test() -> AppTest:
    _reset_cache_db()
    return AppTest.from_file(str(_repo_root() / "app.py"))


def _text_area_by_label(at: AppTest, label: str):
    for text_area in at.text_area:
        if text_area.label == label:
            return text_area
    raise AssertionError(f"未找到文本框: {label}")


def _button_by_label(at: AppTest, label: str):
    for button in at.button:
        if button.label == label:
            return button
    raise AssertionError(f"未找到按钮: {label}")


def _button_labels(at: AppTest) -> list[str]:
    return [button.label for button in at.button]


def _default_video_prompt() -> str:
    return app.load_prompt_template(app.resolve_runtime_files().video_prompt_template_path, "")


def _default_category_prompt() -> str:
    return app.load_prompt_template(
        app.resolve_runtime_files().category_prompt_template_path,
        "",
    )


def test_translation_compliance_mode_value() -> None:
    assert AppMode.TRANSLATION_COMPLIANCE.value == "翻译合规判断"


def test_translation_compliance_mode_is_listed_first() -> None:
    assert list(AppMode)[0] == AppMode.TRANSLATION_COMPLIANCE


def test_translation_compliance_mode_forces_json_output_format() -> None:
    session_state = {
        "output_format": OUTPUT_FORMAT_PLAIN_TEXT,
        SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_PLAIN_TEXT,
    }

    result = resolve_output_format_for_mode(
        AppMode.TRANSLATION_COMPLIANCE, session_state
    )

    assert result == OUTPUT_FORMAT_JSON


def test_non_compliance_mode_always_uses_plain_text_output_format() -> None:
    session_state = {
        "output_format": OUTPUT_FORMAT_JSON,
        SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_JSON,
    }

    result = resolve_output_format_for_mode(AppMode.VIDEO_PROMPT, session_state)

    assert result == OUTPUT_FORMAT_PLAIN_TEXT


def test_category_mode_always_uses_plain_text_output_format() -> None:
    session_state = {
        "output_format": OUTPUT_FORMAT_JSON,
        SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_JSON,
    }

    result = resolve_output_format_for_mode(AppMode.CATEGORY_ANALYSIS, session_state)

    assert result == OUTPUT_FORMAT_PLAIN_TEXT


def test_resolve_mode_prompt_reads_independent_session_keys() -> None:
    session_state = {
        SESSION_VIDEO_PROMPT: "普通模式提示词",
        SESSION_CATEGORY_ANALYSIS_PROMPT: "类目模式提示词",
        SESSION_TRANSLATION_COMPLIANCE_PROMPT: "合规模式提示词",
    }

    assert (
        resolve_mode_prompt(
            AppMode.VIDEO_PROMPT,
            session_state,
            video_prompt_default="普通模式默认提示词",
            category_prompt_default="类目模式默认提示词",
            translation_prompt_default="合规模式默认提示词",
        )
        == "普通模式提示词"
    )
    assert (
        resolve_mode_prompt(
            AppMode.CATEGORY_ANALYSIS,
            session_state,
            video_prompt_default="普通模式默认提示词",
            category_prompt_default="类目模式默认提示词",
            translation_prompt_default="合规模式默认提示词",
        )
        == "类目模式提示词"
    )
    assert (
        resolve_mode_prompt(
            AppMode.TRANSLATION_COMPLIANCE,
            session_state,
            video_prompt_default="普通模式默认提示词",
            category_prompt_default="类目模式默认提示词",
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
            category_prompt_default="类目模式默认提示词",
            translation_prompt_default="合规模式默认提示词",
        )
        == "普通模式默认提示词"
    )
    assert (
        resolve_mode_prompt(
            AppMode.CATEGORY_ANALYSIS,
            session_state,
            video_prompt_default="普通模式默认提示词",
            category_prompt_default="类目模式默认提示词",
            translation_prompt_default="合规模式默认提示词",
        )
        == "类目模式默认提示词"
    )
    assert (
        resolve_mode_prompt(
            AppMode.TRANSLATION_COMPLIANCE,
            session_state,
            video_prompt_default="普通模式默认提示词",
            category_prompt_default="类目模式默认提示词",
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
    assert choose_video_prompt_initial_value("saved", "legacy", "doc", True) == "saved"
    assert choose_video_prompt_initial_value("", "legacy", "doc", True) == "legacy"
    assert choose_video_prompt_initial_value("", "", "doc", True) == "doc"
    assert choose_video_prompt_initial_value("saved", "legacy", "doc", False) == "doc"


def test_choose_translation_prompt_initial_value_prefers_saved_then_doc() -> None:
    assert choose_translation_prompt_initial_value("saved", "doc") == "saved"
    assert choose_translation_prompt_initial_value("", "doc") == "doc"


def test_choose_category_prompt_initial_value_prefers_saved_then_doc() -> None:
    assert choose_category_prompt_initial_value("saved", "doc", True) == "saved"
    assert choose_category_prompt_initial_value("", "doc", True) == "doc"
    assert choose_category_prompt_initial_value("saved", "doc", False) == "doc"


def test_resolve_prompt_setting_key_matches_mode() -> None:
    assert resolve_prompt_setting_key(AppMode.VIDEO_PROMPT) == "prompt.video_prompt"
    assert (
        resolve_prompt_setting_key(AppMode.CATEGORY_ANALYSIS)
        == "prompt.category_analysis"
    )
    assert (
        resolve_prompt_setting_key(AppMode.TRANSLATION_COMPLIANCE)
        == "prompt.translation_compliance"
    )


def test_should_not_persist_output_format_for_any_mode() -> None:
    assert should_persist_output_format(AppMode.VIDEO_PROMPT) is False
    assert should_persist_output_format(AppMode.CATEGORY_ANALYSIS) is False
    assert should_persist_output_format(AppMode.TRANSLATION_COMPLIANCE) is False


def test_build_persist_operations_for_translation_mode_only_writes_prompt() -> None:
    operations = build_persist_operations(
        app_mode=AppMode.TRANSLATION_COMPLIANCE,
        prompt_text="review",
        output_format=OUTPUT_FORMAT_JSON,
    )

    assert operations == [("prompt.translation_compliance", "review")]


def test_build_persist_operations_for_video_mode_only_writes_prompt() -> None:
    operations = build_persist_operations(
        app_mode=AppMode.VIDEO_PROMPT,
        prompt_text="video",
        output_format=OUTPUT_FORMAT_JSON,
    )

    assert operations == [
        ("prompt.video_prompt", "video"),
        (SETTING_VIDEO_PROMPT_CUSTOM_ENABLED, "1"),
    ]


def test_build_persist_operations_for_category_mode_only_writes_prompt() -> None:
    operations = build_persist_operations(
        app_mode=AppMode.CATEGORY_ANALYSIS,
        prompt_text="category",
        output_format=OUTPUT_FORMAT_JSON,
    )

    assert operations == [
        ("prompt.category_analysis", "category"),
        (SETTING_CATEGORY_ANALYSIS_PROMPT_CUSTOM_ENABLED, "1"),
    ]


def test_build_run_settings_uses_normalized_prompt_for_translation_mode() -> None:
    settings = build_run_settings(
        app_mode=AppMode.TRANSLATION_COMPLIANCE,
        prompt_text="   ",
        video_prompt_default="视频模板",
        category_prompt_default="类目模板",
        translation_prompt_default="合规模板",
        session_state={SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_PLAIN_TEXT},
    )

    assert settings.output_format == OUTPUT_FORMAT_JSON
    assert settings.prompt_text == "合规模板"


def test_build_run_settings_uses_plain_text_output_format_for_video_mode() -> None:
    settings = build_run_settings(
        app_mode=AppMode.VIDEO_PROMPT,
        prompt_text="自定义提示词",
        video_prompt_default="视频模板",
        category_prompt_default="类目模板",
        translation_prompt_default="合规模板",
        session_state={SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_JSON},
    )

    assert settings.output_format == OUTPUT_FORMAT_PLAIN_TEXT
    assert settings.prompt_text == "自定义提示词"


def test_build_run_settings_uses_category_default_for_empty_prompt() -> None:
    settings = build_run_settings(
        app_mode=AppMode.CATEGORY_ANALYSIS,
        prompt_text="   ",
        video_prompt_default="视频模板",
        category_prompt_default="类目模板",
        translation_prompt_default="合规模板",
        session_state={SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_JSON},
    )

    assert settings.output_format == OUTPUT_FORMAT_PLAIN_TEXT
    assert settings.prompt_text == "类目模板"


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


def test_switching_from_category_mode_back_to_video_prompt_takes_effect_immediately() -> (
    None
):
    at = _new_app_test()

    at.run(timeout=10)
    at.selectbox[0].set_value(AppMode.CATEGORY_ANALYSIS.value)
    at.run(timeout=10)

    assert at.selectbox[0].value == AppMode.CATEGORY_ANALYSIS.value
    assert any(
        text_area.label == "类目列表（每行一个）" for text_area in at.text_area
    )

    at.selectbox[0].set_value(AppMode.VIDEO_PROMPT.value)
    at.run(timeout=10)

    assert at.selectbox[0].value == AppMode.VIDEO_PROMPT.value
    assert not any(
        text_area.label == "类目列表（每行一个）" for text_area in at.text_area
    )


def test_app_starts_with_translation_compliance_as_default_mode() -> None:
    at = _new_app_test()

    at.run(timeout=10)

    assert at.selectbox[0].options[0] == AppMode.TRANSLATION_COMPLIANCE.value
    assert at.selectbox[0].value == AppMode.TRANSLATION_COMPLIANCE.value


def test_app_hides_technical_copy_for_business_users() -> None:
    at = _new_app_test()

    at.run(timeout=10)

    captions = [caption.value for caption in at.caption]
    expander_labels = [expander.label for expander in at.expander]

    assert not any("当前模型服务商" in caption for caption in captions)
    assert not any("本地保存位置" in caption for caption in captions)
    assert not any("Cookie 仅保存在当前用户目录" in caption for caption in captions)
    assert not any("页面仅保留常用运行参数" in caption for caption in captions)
    assert not any("固定使用 JSON 输出" in caption for caption in captions)
    assert "高级设置" in expander_labels
    assert not any("仅本次运行生效，不写回 config.yaml" in label for label in expander_labels)


def test_app_uses_business_friendly_labels_for_settings_and_prompt_editor() -> None:
    at = _new_app_test()

    at.run(timeout=10)

    subheaders = [subheader.value for subheader in at.subheader]
    text_area_labels = [text_area.label for text_area in at.text_area]
    number_input_labels = [number_input.label for number_input in at.number_input]
    selectbox_labels = [selectbox.label for selectbox in at.selectbox]
    button_labels = [button.label for button in at.button]

    assert "提示词设置" in subheaders
    assert "视频解析提示词配置" not in subheaders
    assert "提示词内容" in text_area_labels
    assert "DEFAULT_USER_PROMPT" not in text_area_labels
    assert "保存提示词" in button_labels
    assert "保存 DEFAULT_USER_PROMPT" not in button_labels
    assert "解析并发数" in number_input_labels
    assert not any("parser.concurrency" in label for label in number_input_labels)
    assert "视频采样帧率" in number_input_labels
    assert not any("volcengine.video_fps" in label for label in number_input_labels)
    assert "思考模式" in selectbox_labels
    assert not any("volcengine.thinking_type" in label for label in selectbox_labels)
    assert "思考强度" in selectbox_labels
    assert not any("volcengine.reasoning_effort" in label for label in selectbox_labels)


def test_switching_to_category_mode_shows_category_prompt_content() -> None:
    session_state = {
        SESSION_CATEGORY_ANALYSIS_PROMPT: choose_category_prompt_initial_value(
            saved_prompt=None,
            default_prompt=_default_category_prompt(),
            use_saved_prompt=False,
        )
    }

    assert (
        resolve_mode_prompt(
            AppMode.CATEGORY_ANALYSIS,
            session_state,
            video_prompt_default=_default_video_prompt(),
            category_prompt_default=_default_category_prompt(),
            translation_prompt_default=DEFAULT_REVIEW_PROMPT,
        )
        == _default_category_prompt()
    )


def test_existing_saved_category_prompt_is_ignored_before_user_enables_custom_value() -> None:
    initial_value = choose_category_prompt_initial_value(
        saved_prompt="旧的类目自定义值",
        default_prompt=_default_category_prompt(),
        use_saved_prompt=False,
    )

    assert initial_value == _default_category_prompt()


def test_video_and_category_prompt_saved_values_remain_independent() -> None:
    at = _new_app_test()

    at.run(timeout=10)
    at.selectbox[0].set_value(AppMode.VIDEO_PROMPT.value)
    at.run(timeout=10)
    _text_area_by_label(at, "提示词内容").set_value("视频模式保存值")
    _button_by_label(at, "保存提示词").click()
    at.run(timeout=10)

    at.selectbox[0].set_value(AppMode.CATEGORY_ANALYSIS.value)
    at.run(timeout=10)
    _text_area_by_label(at, "提示词内容").set_value("类目模式保存值")
    _button_by_label(at, "保存提示词").click()
    at.run(timeout=10)

    at.selectbox[0].set_value(AppMode.VIDEO_PROMPT.value)
    at.run(timeout=10)
    assert _text_area_by_label(at, "提示词内容").value == "视频模式保存值"

    at.selectbox[0].set_value(AppMode.CATEGORY_ANALYSIS.value)
    at.run(timeout=10)
    assert _text_area_by_label(at, "提示词内容").value == "类目模式保存值"


def test_reset_default_prompt_only_resets_current_mode() -> None:
    at = _new_app_test()

    at.run(timeout=10)
    at.selectbox[0].set_value(AppMode.CATEGORY_ANALYSIS.value)
    at.run(timeout=10)
    _text_area_by_label(at, "提示词内容").set_value("类目模式保存值")
    _button_by_label(at, "保存提示词").click()
    at.run(timeout=10)

    at.selectbox[0].set_value(AppMode.VIDEO_PROMPT.value)
    at.run(timeout=10)
    _text_area_by_label(at, "提示词内容").set_value("视频模式保存值")
    _button_by_label(at, "保存提示词").click()
    at.run(timeout=10)
    _button_by_label(at, "恢复默认提示词").click()
    at.run(timeout=10)

    assert _text_area_by_label(at, "提示词内容").value == _default_video_prompt()

    at.selectbox[0].set_value(AppMode.CATEGORY_ANALYSIS.value)
    at.run(timeout=10)
    assert _text_area_by_label(at, "提示词内容").value == "类目模式保存值"


def test_unsaved_prompt_draft_is_discarded_after_switching_modes() -> None:
    at = _new_app_test()

    at.run(timeout=10)
    at.selectbox[0].set_value(AppMode.VIDEO_PROMPT.value)
    at.run(timeout=10)
    _text_area_by_label(at, "提示词内容").set_value("视频模式已保存值")
    _button_by_label(at, "保存提示词").click()
    at.run(timeout=10)
    _text_area_by_label(at, "提示词内容").set_value("视频模式未保存草稿")
    at.run(timeout=10)

    at.selectbox[0].set_value(AppMode.CATEGORY_ANALYSIS.value)
    at.run(timeout=10)
    at.selectbox[0].set_value(AppMode.VIDEO_PROMPT.value)
    at.run(timeout=10)

    assert _text_area_by_label(at, "提示词内容").value == "视频模式已保存值"


def test_start_run_uses_current_prompt_input_without_saving() -> None:
    settings = build_run_settings(
        app_mode=AppMode.VIDEO_PROMPT,
        prompt_text="未保存直接运行提示词",
        video_prompt_default="视频模板",
        category_prompt_default="类目模板",
        translation_prompt_default="合规模板",
        session_state={
            SESSION_VIDEO_PROMPT: "已保存提示词",
            SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: OUTPUT_FORMAT_PLAIN_TEXT,
        },
    )

    assert settings.prompt_text == "未保存直接运行提示词"


def test_translation_mode_does_not_show_reset_default_prompt_button() -> None:
    at = _new_app_test()

    at.run(timeout=10)

    assert "保存提示词" in _button_labels(at)
    assert "恢复默认提示词" not in _button_labels(at)


def test_duration_mode_hides_prompt_editor() -> None:
    at = _new_app_test()

    at.run(timeout=10)
    at.selectbox[0].set_value(AppMode.DURATION_CHECK.value)
    at.run(timeout=10)

    assert "提示词设置" not in [subheader.value for subheader in at.subheader]
    assert not any(text_area.label == "提示词内容" for text_area in at.text_area)
