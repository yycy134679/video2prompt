from __future__ import annotations

from pathlib import Path

import app


def test_resolve_runtime_files_prefers_environment_paths(tmp_path: Path) -> None:
    env = {
        "VIDEO2PROMPT_RESOURCE_ROOT": str(tmp_path / "bundle"),
        "VIDEO2PROMPT_APP_SUPPORT_DIR": str(tmp_path / "support"),
        "VIDEO2PROMPT_ENV_PATH": str(tmp_path / "support" / ".env"),
        "VIDEO2PROMPT_CONFIG_PATH": str(tmp_path / "support" / "config.yaml"),
    }

    runtime_files = app.resolve_runtime_files(env)

    assert runtime_files.resource_root == tmp_path / "bundle"
    assert runtime_files.env_path == tmp_path / "support" / ".env"
    assert runtime_files.config_path == tmp_path / "support" / "config.yaml"
    assert runtime_files.exports_dir == tmp_path / "support" / "exports"


def test_resolve_runtime_files_builds_template_paths_from_resource_root(tmp_path: Path) -> None:
    env = {
        "VIDEO2PROMPT_RESOURCE_ROOT": str(tmp_path / "bundle"),
        "VIDEO2PROMPT_APP_SUPPORT_DIR": str(tmp_path / "support"),
        "VIDEO2PROMPT_FFPROBE_PATH": str(tmp_path / "bundle" / "bin" / "ffprobe"),
    }

    runtime_files = app.resolve_runtime_files(env)

    assert runtime_files.video_prompt_template_path == tmp_path / "bundle" / "docs" / "视频复刻提示词.md"
    assert runtime_files.translation_template_path == tmp_path / "bundle" / "docs" / "视频内容审查.md"
    assert runtime_files.excel_template_path == tmp_path / "bundle" / "docs" / "product_prompt_template.xlsx"
    assert runtime_files.ffprobe_path == tmp_path / "bundle" / "bin" / "ffprobe"


def test_build_config_manager_uses_runtime_file_paths(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class DummyConfigManager:
        def __init__(self, env_path: str, config_path: str, runtime_paths=None):
            captured["env_path"] = env_path
            captured["config_path"] = config_path
            captured["runtime_paths"] = runtime_paths

    monkeypatch.setattr(app, "ConfigManager", DummyConfigManager)

    env = {
        "VIDEO2PROMPT_APP_SUPPORT_DIR": str(tmp_path / "support"),
        "VIDEO2PROMPT_ENV_PATH": str(tmp_path / "support" / ".env"),
        "VIDEO2PROMPT_CONFIG_PATH": str(tmp_path / "support" / "config.yaml"),
    }

    app.build_config_manager(env)

    assert captured == {
        "env_path": str(tmp_path / "support" / ".env"),
        "config_path": str(tmp_path / "support" / "config.yaml"),
        "runtime_paths": None,
    }


def test_build_config_manager_passes_runtime_paths(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class DummyConfigManager:
        def __init__(self, env_path: str, config_path: str, runtime_paths=None):
            captured["runtime_paths"] = runtime_paths

    monkeypatch.setattr(app, "ConfigManager", DummyConfigManager)

    env = {
        "VIDEO2PROMPT_RESOURCE_ROOT": str(tmp_path / "bundle"),
        "VIDEO2PROMPT_APP_SUPPORT_DIR": str(tmp_path / "support"),
        "VIDEO2PROMPT_ENV_PATH": str(tmp_path / "support" / ".env"),
        "VIDEO2PROMPT_CONFIG_PATH": str(tmp_path / "support" / "config.yaml"),
    }

    app.build_config_manager(env, use_runtime_paths=True)

    runtime_paths = captured["runtime_paths"]
    assert runtime_paths is not None
    assert runtime_paths.resource_root == tmp_path / "bundle"
    assert runtime_paths.exports_dir == tmp_path / "support" / "exports"


def test_build_excel_exporter_uses_runtime_template_path(tmp_path: Path) -> None:
    runtime_files = app.RuntimeFiles(
        resource_root=tmp_path / "bundle",
        app_support_dir=tmp_path / "support",
        env_path=tmp_path / "support" / ".env",
        config_path=tmp_path / "support" / "config.yaml",
        exports_dir=tmp_path / "support" / "exports",
        ffprobe_path=tmp_path / "bundle" / "bin" / "ffprobe",
        video_prompt_template_path=tmp_path / "bundle" / "docs" / "视频复刻提示词.md",
        translation_template_path=tmp_path / "bundle" / "docs" / "视频内容审查.md",
        excel_template_path=tmp_path / "bundle" / "docs" / "product_prompt_template.xlsx",
    )

    exporter = app.build_excel_exporter(runtime_files)

    assert exporter.template_path == str(runtime_files.excel_template_path)


def test_ensure_exports_dir_uses_runtime_exports_dir(tmp_path: Path) -> None:
    runtime_files = app.RuntimeFiles(
        resource_root=tmp_path / "bundle",
        app_support_dir=tmp_path / "support",
        env_path=tmp_path / "support" / ".env",
        config_path=tmp_path / "support" / "config.yaml",
        exports_dir=tmp_path / "support" / "exports",
        ffprobe_path=tmp_path / "bundle" / "bin" / "ffprobe",
        video_prompt_template_path=tmp_path / "bundle" / "docs" / "视频复刻提示词.md",
        translation_template_path=tmp_path / "bundle" / "docs" / "视频内容审查.md",
        excel_template_path=tmp_path / "bundle" / "docs" / "product_prompt_template.xlsx",
    )

    export_dir = app.ensure_exports_dir(runtime_files)

    assert export_dir == runtime_files.exports_dir
    assert export_dir.exists()


def test_build_duration_runner_passes_runtime_ffprobe_path(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class DummyRunner:
        def __init__(self, parser, config, logger=None, ffprobe_path=None):
            captured["parser"] = parser
            captured["config"] = config
            captured["logger"] = logger
            captured["ffprobe_path"] = ffprobe_path

    monkeypatch.setattr(app, "DurationCheckRunner", DummyRunner)

    runtime_files = app.RuntimeFiles(
        resource_root=tmp_path / "bundle",
        app_support_dir=tmp_path / "support",
        env_path=tmp_path / "support" / ".env",
        config_path=tmp_path / "support" / "config.yaml",
        exports_dir=tmp_path / "support" / "exports",
        ffprobe_path=tmp_path / "bundle" / "bin" / "ffprobe",
        video_prompt_template_path=tmp_path / "bundle" / "docs" / "视频复刻提示词.md",
        translation_template_path=tmp_path / "bundle" / "docs" / "视频内容审查.md",
        excel_template_path=tmp_path / "bundle" / "docs" / "product_prompt_template.xlsx",
    )
    parser = object()
    config = object()
    logger = object()

    app.build_duration_runner(parser, config, logger, runtime_files)

    assert captured["ffprobe_path"] == str(runtime_files.ffprobe_path)
