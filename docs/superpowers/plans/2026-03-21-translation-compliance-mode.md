# 翻译合规判断模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增“翻译合规判断”运行模式，在页面层固定 JSON 输出并自动加载审查提示词，同时保证普通模式与合规模式的 prompt / output_format 在会话和持久化层都互不污染。

**Architecture:** 先补最小的枚举与纯函数前置条件，再补缓存层按 key 持久化设置，最后把这些能力接入 `app.py`。所有与模式分支相关的判断尽量收敛到小辅助函数中测试，避免直接依赖 Streamlit 组件做脆弱测试；调度器、导出器和 JSON 解析逻辑保持不变。

**Tech Stack:** Python 3.11+, Streamlit, pytest, aiosqlite, httpx

---

## 文件职责映射

- Modify: `src/video2prompt/models.py`
  - 新增 `AppMode.TRANSLATION_COMPLIANCE`
- Modify: `src/video2prompt/cache_store.py`
  - 增加 `app_settings` 表和 `save_setting/load_setting` 接口
- Modify: `app.py`
  - 提供模式默认 prompt / output_format / 运行前 prompt 归一化的辅助函数，并接入新模式 UI
- Modify: `tests/test_cache_store.py`
  - 覆盖 `app_settings` 读写与兼容行为
- Modify: `tests/test_app_run_controller_state.py`
  - 验证运行快照仍记录真实模式、prompt、output_format
- Modify: `tests/test_app_cookie_state.py`
  - 检查 UI 状态改动后是否需要同步调整；若不需要，至少验证不受影响
- Create: `tests/test_app_mode_defaults.py`
  - 覆盖模式默认值、模式隔离、空 prompt 归一化
- Modify: `README.md`
  - 说明新模式与按模式保存语义

### Task 1: 新增模式枚举这个最小前置条件

**Files:**
- Modify: `src/video2prompt/models.py`
- Create: `tests/test_app_mode_defaults.py`

- [ ] **Step 1: 写失败测试，要求 `AppMode` 包含新模式**

```python
from video2prompt.models import AppMode


def test_app_mode_contains_translation_compliance() -> None:
    assert AppMode.TRANSLATION_COMPLIANCE.value == "翻译合规判断"
```

- [ ] **Step 2: 运行测试，确认因枚举不存在而失败**

Run: `python -m pytest tests/test_app_mode_defaults.py::test_app_mode_contains_translation_compliance -v`
Expected: FAIL，提示 `TRANSLATION_COMPLIANCE` 不存在

- [ ] **Step 3: 最小实现枚举值**

```python
class AppMode(str, Enum):
    VIDEO_PROMPT = "视频复刻提示词"
    CATEGORY_ANALYSIS = "按类目分析"
    TRANSLATION_COMPLIANCE = "翻译合规判断"
    DURATION_CHECK = "视频时长判断"
```

- [ ] **Step 4: 重新运行测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py::test_app_mode_contains_translation_compliance -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video2prompt/models.py tests/test_app_mode_defaults.py
git commit -m "feat: 增加翻译合规判断模式枚举"
```

### Task 2: 提炼模式输出格式纯函数

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_mode_defaults.py`

- [ ] **Step 1: 写失败测试，合规模式固定返回 `json`**

```python
def test_resolve_output_format_for_translation_compliance_forces_json() -> None:
    session_state = {"video_prompt_output_format": "plain_text"}

    assert (
        app.resolve_output_format_for_mode(AppMode.TRANSLATION_COMPLIANCE, session_state)
        == app.OUTPUT_FORMAT_JSON
    )
```

- [ ] **Step 2: 写失败测试，普通模式恢复已保存输出格式**

```python
def test_resolve_output_format_for_video_prompt_uses_saved_value() -> None:
    session_state = {"video_prompt_output_format": app.OUTPUT_FORMAT_JSON}

    assert app.resolve_output_format_for_mode(AppMode.VIDEO_PROMPT, session_state) == app.OUTPUT_FORMAT_JSON
```

- [ ] **Step 3: 运行测试，确认因辅助函数不存在而失败**

Run: `python -m pytest tests/test_app_mode_defaults.py -k output_format -v`
Expected: FAIL，提示 `resolve_output_format_for_mode` 不存在

- [ ] **Step 4: 最小实现纯函数和所需常量**

```python
SESSION_VIDEO_PROMPT_OUTPUT_FORMAT = "video_prompt_output_format"


def resolve_output_format_for_mode(app_mode: AppMode, session_state: MutableMapping[str, Any]) -> str:
    if app_mode == AppMode.TRANSLATION_COMPLIANCE:
        return OUTPUT_FORMAT_JSON
    return str(session_state.get(SESSION_VIDEO_PROMPT_OUTPUT_FORMAT, OUTPUT_FORMAT_PLAIN_TEXT))
```

- [ ] **Step 5: 重新运行测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k output_format -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app_mode_defaults.py
git commit -m "test: 补充模式输出格式隔离逻辑"
```

### Task 3: 提炼模式 prompt 选择与运行前归一化纯函数

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_mode_defaults.py`

- [ ] **Step 1: 写失败测试，普通模式和合规模式各自读取独立 prompt**

```python
def test_resolve_mode_prompt_uses_mode_specific_session_value() -> None:
    session_state = {
        app.SESSION_VIDEO_PROMPT: "video-prompt",
        app.SESSION_TRANSLATION_COMPLIANCE_PROMPT: "review-prompt",
    }

    assert app.resolve_mode_prompt(
        AppMode.VIDEO_PROMPT,
        session_state,
        video_prompt_default="video-doc",
        translation_prompt_default="review-doc",
    ) == "video-prompt"
    assert app.resolve_mode_prompt(
        AppMode.TRANSLATION_COMPLIANCE,
        session_state,
        video_prompt_default="video-doc",
        translation_prompt_default="review-doc",
    ) == "review-prompt"
```

- [ ] **Step 2: 写失败测试，空 prompt 运行前按模式模板补回**

```python
def test_normalize_runtime_prompt_falls_back_to_mode_default() -> None:
    assert app.normalize_runtime_prompt("   ", "mode-default") == "mode-default"
    assert app.normalize_runtime_prompt(" custom ", "mode-default") == "custom"
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `python -m pytest tests/test_app_mode_defaults.py -k "resolve_mode_prompt or normalize_runtime_prompt" -v`
Expected: FAIL，提示辅助函数或常量不存在

- [ ] **Step 4: 最小实现 prompt 纯函数与 session key 常量**

```python
SESSION_VIDEO_PROMPT = "video_prompt"
SESSION_TRANSLATION_COMPLIANCE_PROMPT = "translation_compliance_prompt"


def resolve_mode_prompt(
    app_mode: AppMode,
    session_state: MutableMapping[str, Any],
    video_prompt_default: str,
    translation_prompt_default: str,
) -> str:
    ...


def normalize_runtime_prompt(prompt_text: str, default_prompt: str) -> str:
    return (prompt_text or "").strip() or default_prompt
```

- [ ] **Step 5: 重新运行测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k "resolve_mode_prompt or normalize_runtime_prompt" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app_mode_defaults.py
git commit -m "test: 补充模式提示词选择与归一化逻辑"
```

### Task 4: 为缓存层增加按 key 保存设置能力

**Files:**
- Modify: `src/video2prompt/cache_store.py`
- Modify: `tests/test_cache_store.py`

- [ ] **Step 1: 写失败测试，覆盖 `save_setting/load_setting`**

```python
@pytest.mark.asyncio
async def test_cache_store_save_and_load_setting(tmp_path: Path) -> None:
    store = CacheStore(db_path=str(tmp_path / "cache.db"))
    await store.init_db()

    await store.save_setting("prompt.video_prompt", "value-a")

    assert await store.load_setting("prompt.video_prompt") == "value-a"
```

- [ ] **Step 2: 运行测试，确认因方法不存在而失败**

Run: `python -m pytest tests/test_cache_store.py -k save_and_load_setting -v`
Expected: FAIL，提示 `save_setting/load_setting` 不存在

- [ ] **Step 3: 写失败测试，确保旧 `system_prompt` 仍可正常工作**

```python
@pytest.mark.asyncio
async def test_cache_store_keeps_legacy_system_prompt_behavior(tmp_path: Path) -> None:
    store = CacheStore(db_path=str(tmp_path / "cache.db"))
    await store.init_db()

    await store.save_system_prompt("legacy")

    assert await store.load_system_prompt() == "legacy"
```

- [ ] **Step 4: 运行测试，确认新增测试失败而旧行为测试仍可通过**

Run: `python -m pytest tests/test_cache_store.py -k "save_and_load_setting or legacy_system_prompt_behavior" -v`
Expected: 新增 settings 测试 FAIL；legacy 测试 PASS

- [ ] **Step 5: 最小实现 `app_settings` 表与两个接口**

```python
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

- [ ] **Step 6: 运行缓存测试，确认通过**

Run: `python -m pytest tests/test_cache_store.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/video2prompt/cache_store.py tests/test_cache_store.py
git commit -m "feat: 增加按模式保存页面设置能力"
```

### Task 5: 提炼文档模板加载纯函数

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_mode_defaults.py`

- [ ] **Step 1: 写失败测试，文档存在时返回文件内容**

```python
def test_load_prompt_template_reads_file_content(tmp_path: Path) -> None:
    file_path = tmp_path / "prompt.md"
    file_path.write_text("doc prompt", encoding="utf-8")

    assert app.load_prompt_template(file_path, fallback_text="fallback") == "doc prompt"
```

- [ ] **Step 2: 写失败测试，文档缺失时回退 fallback**

```python
def test_load_prompt_template_falls_back_when_missing(tmp_path: Path) -> None:
    assert app.load_prompt_template(tmp_path / "missing.md", fallback_text="fallback") == "fallback"
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `python -m pytest tests/test_app_mode_defaults.py -k load_prompt_template -v`
Expected: FAIL，提示 `load_prompt_template` 不存在

- [ ] **Step 4: 最小实现模板加载函数**

```python
def load_prompt_template(path: Path, fallback_text: str) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback_text
    return text or fallback_text
```

- [ ] **Step 5: 重新运行测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k load_prompt_template -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app_mode_defaults.py
git commit -m "test: 补充提示词模板加载与回退逻辑"
```

### Task 6: 接入 `app.py` 初始化与保存逻辑

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_mode_defaults.py`

- [ ] **Step 1: 写失败测试，普通模式初始化优先顺序正确**

```python
def test_initialize_video_prompt_prefers_saved_setting_then_legacy_then_doc() -> None:
    assert app.choose_video_prompt_initial_value("saved", "legacy", "doc") == "saved"
    assert app.choose_video_prompt_initial_value("", "legacy", "doc") == "legacy"
    assert app.choose_video_prompt_initial_value("", "", "doc") == "doc"
```

- [ ] **Step 2: 写失败测试，合规模式初始化优先顺序正确**

```python
def test_initialize_translation_prompt_prefers_saved_setting_then_doc() -> None:
    assert app.choose_translation_prompt_initial_value("saved", "doc") == "saved"
    assert app.choose_translation_prompt_initial_value("", "doc") == "doc"
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `python -m pytest tests/test_app_mode_defaults.py -k "initial_value" -v`
Expected: FAIL，提示辅助函数不存在

- [ ] **Step 4: 最小实现初始化辅助函数**

```python
video_prompt_initial = choose_video_prompt_initial_value(saved_video_prompt, legacy_prompt, video_doc_prompt)
translation_prompt_initial = choose_translation_prompt_initial_value(saved_translation_prompt, review_doc_prompt)
```

- [ ] **Step 5: 重新运行初始化测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k "initial_value" -v`
Expected: PASS

- [ ] **Step 6: 写失败测试，覆盖保存时选择正确 setting key**

```python
def test_resolve_prompt_setting_key_matches_mode() -> None:
    assert app.resolve_prompt_setting_key(AppMode.VIDEO_PROMPT) == "prompt.video_prompt"
    assert app.resolve_prompt_setting_key(AppMode.CATEGORY_ANALYSIS) == "prompt.video_prompt"
    assert app.resolve_prompt_setting_key(AppMode.TRANSLATION_COMPLIANCE) == "prompt.translation_compliance"


def test_should_persist_output_format_only_for_normal_modes() -> None:
    assert app.should_persist_output_format(AppMode.VIDEO_PROMPT) is True
    assert app.should_persist_output_format(AppMode.CATEGORY_ANALYSIS) is True
    assert app.should_persist_output_format(AppMode.TRANSLATION_COMPLIANCE) is False
```

- [ ] **Step 7: 运行测试，确认失败**

Run: `python -m pytest tests/test_app_mode_defaults.py -k "setting_key or persist_output_format" -v`
Expected: FAIL，提示保存辅助函数不存在

- [ ] **Step 8: 最小实现保存辅助函数**

```python
def resolve_prompt_setting_key(app_mode: AppMode) -> str:
    ...


def should_persist_output_format(app_mode: AppMode) -> bool:
    ...
```

- [ ] **Step 9: 重新运行保存辅助函数测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k "setting_key or persist_output_format" -v`
Expected: PASS

- [ ] **Step 10: 写失败测试，覆盖保存桥接 helper 产出正确的持久化操作**

```python
def test_build_persist_operations_for_translation_mode_only_writes_prompt() -> None:
    operations = app.build_persist_operations(
        app_mode=AppMode.TRANSLATION_COMPLIANCE,
        prompt_text="review",
        output_format=app.OUTPUT_FORMAT_JSON,
    )

    assert operations == [("prompt.translation_compliance", "review")]


def test_build_persist_operations_for_video_mode_writes_prompt_and_format() -> None:
    operations = app.build_persist_operations(
        app_mode=AppMode.VIDEO_PROMPT,
        prompt_text="video",
        output_format=app.OUTPUT_FORMAT_JSON,
    )

    assert operations == [
        ("prompt.video_prompt", "video"),
        ("output_format.video_prompt", app.OUTPUT_FORMAT_JSON),
    ]
```

- [ ] **Step 11: 运行测试，确认失败**

Run: `python -m pytest tests/test_app_mode_defaults.py -k build_persist_operations -v`
Expected: FAIL，提示 `build_persist_operations` 不存在

- [ ] **Step 12: 最小实现保存桥接 helper**

```python
def build_persist_operations(app_mode: AppMode, prompt_text: str, output_format: str) -> list[tuple[str, str]]:
    ...
```

- [ ] **Step 13: 重新运行桥接 helper 测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k build_persist_operations -v`
Expected: PASS

- [ ] **Step 14: 在 `main()` 中接入初始化 helper 与保存 wiring**

具体改动：

- 保存按钮不再手写分支，而是遍历 `build_persist_operations()` 返回结果写入缓存
- 普通模式输出格式切换写 `output_format.video_prompt`

- [ ] **Step 15: 运行测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k "initial_value or resolve_" -v`
Expected: PASS

- [ ] **Step 16: Commit**

```bash
git add app.py tests/test_app_mode_defaults.py
git commit -m "feat: 接入按模式初始化与保存逻辑"
```

### Task 7: 接入页面模式分支与启动运行参数

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_run_controller_state.py`
- Modify: `tests/test_app_cookie_state.py`
- Modify: `tests/test_app_mode_defaults.py`

- [ ] **Step 1: 写失败测试，启动运行参数使用归一化后的 prompt**

```python
def test_build_run_settings_uses_normalized_prompt_for_translation_mode() -> None:
    settings = app.build_run_settings(
        app_mode=AppMode.TRANSLATION_COMPLIANCE,
        prompt_text="   ",
        video_prompt_default="video-doc",
        translation_prompt_default="review-doc",
        session_state={app.SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: app.OUTPUT_FORMAT_PLAIN_TEXT},
    )

    assert settings.output_format == app.OUTPUT_FORMAT_JSON
    assert settings.prompt_text == "review-doc"
```

- [ ] **Step 2: 写失败测试，普通模式运行参数恢复独立 output_format**

```python
def test_build_run_settings_uses_saved_output_format_for_video_mode() -> None:
    settings = app.build_run_settings(
        app_mode=AppMode.VIDEO_PROMPT,
        prompt_text="custom",
        video_prompt_default="video-doc",
        translation_prompt_default="review-doc",
        session_state={app.SESSION_VIDEO_PROMPT_OUTPUT_FORMAT: app.OUTPUT_FORMAT_JSON},
    )

    assert settings.output_format == app.OUTPUT_FORMAT_JSON
    assert settings.prompt_text == "custom"
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `python -m pytest tests/test_app_mode_defaults.py -k build_run_settings -v`
Expected: FAIL，提示运行参数辅助结构不存在

- [ ] **Step 4: 最小实现运行参数辅助结构与纯函数**

```python
@dataclass
class ResolvedRunSettings:
    prompt_text: str
    output_format: str


def build_run_settings(... ) -> ResolvedRunSettings:
    ...
```

- [ ] **Step 5: 重新运行运行参数测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k build_run_settings -v`
Expected: PASS

- [ ] **Step 6: 写失败测试，覆盖桥接 helper 能产出 `RunController` 所需关键字段**

```python
def test_build_controller_payload_uses_resolved_run_settings() -> None:
    payload = app.build_controller_payload(
        app_mode=AppMode.TRANSLATION_COMPLIANCE,
        resolved_settings=app.ResolvedRunSettings(prompt_text="review-doc", output_format=app.OUTPUT_FORMAT_JSON),
    )

    assert payload["app_mode_value"] == "翻译合规判断"
    assert payload["default_user_prompt"] == "review-doc"
    assert payload["output_format"] == app.OUTPUT_FORMAT_JSON
```

- [ ] **Step 7: 运行测试，确认失败**

Run: `python -m pytest tests/test_app_mode_defaults.py -k build_controller_payload -v`
Expected: FAIL，提示 `build_controller_payload` 不存在

- [ ] **Step 8: 最小实现 controller 桥接 helper**

```python
def build_controller_payload(app_mode: AppMode, resolved_settings: ResolvedRunSettings) -> dict[str, str | bool]:
    ...
```

- [ ] **Step 9: 重新运行桥接 helper 测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k build_controller_payload -v`
Expected: PASS

- [ ] **Step 10: 检查并补测试，确认 cookie 相关状态逻辑未被模式改动破坏**

示例方向：

```python
def test_cookie_state_helpers_are_mode_independent() -> None:
    ...
```

如果阅读后确认无需改动，也要在执行记录里注明“已检查 `tests/test_app_cookie_state.py`，无需修改”。

- [ ] **Step 11: 接入模式下拉与输出格式分支**

具体改动：

1. 模式下拉包含“翻译合规判断”
2. 合规模式运行时固定 `output_format = json`
3. 普通模式继续使用独立保存的 output_format

- [ ] **Step 12: 运行模式默认值相关测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py -k "output_format or build_run_settings" -v`
Expected: PASS

- [ ] **Step 13: 接入提示词框默认值与显示分支**

具体改动：

1. 合规模式提示词框显示审查模板默认值
2. 普通模式提示词框显示普通模式默认值
3. 保存按钮按当前模式走对应 setting key

- [ ] **Step 14: 接入启动运行前归一化并写入 `RunController` / 线程参数**

具体改动：

1. 启动运行前调用 `build_run_settings()`
2. 通过 `build_controller_payload()` 生成 `RunController` 所需关键字段
3. 将归一化后的 prompt/output_format 传给线程入口

- [ ] **Step 15: 运行相关测试，先看失败点或确认通过**

Run: `python -m pytest tests/test_app_run_controller_state.py tests/test_app_cookie_state.py -v`
Expected: PASS，若失败则补齐最小修复

- [ ] **Step 16: 补一个快照回归测试，确认新模式值可完整持久化**

```python
def test_persist_completed_run_snapshot_keeps_translation_compliance_runtime_values() -> None:
    ...
```

- [ ] **Step 17: 运行相关测试，确认通过**

Run: `python -m pytest tests/test_app_mode_defaults.py tests/test_app_run_controller_state.py tests/test_app_cookie_state.py -v`
Expected: PASS

- [ ] **Step 18: Commit**

```bash
git add app.py tests/test_app_run_controller_state.py tests/test_app_cookie_state.py tests/test_app_mode_defaults.py
git commit -m "feat: 接入翻译合规判断模式页面分支"
```

### Task 8: 用特征测试锁定客户端空 prompt 兜底现状

**Files:**
- Modify: `tests/test_volcengine_responses_client.py`

- [ ] **Step 1: 新增特征测试，说明客户端在收到空 prompt 时仍会回退默认值**

```python
def test_client_uses_default_prompt_when_runtime_prompt_empty() -> None:
    client = VolcengineResponsesClient(base_url="https://example.com", endpoint_id="ep", api_key="k")
    client.set_default_user_prompt("fallback")

    payload = client._build_video_url_input(video_url="https://example.com/video.mp4", prompt="", fps=1.0)

    assert payload[0]["content"][1]["text"] == "fallback"
```

- [ ] **Step 2: 运行测试，确认通过并记录这是特征测试，不是 TDD 主链路**

Run: `python -m pytest tests/test_volcengine_responses_client.py -k default_prompt_when_runtime_prompt_empty -v`
Expected: PASS

- [ ] **Step 3: 运行完整客户端测试，确认无回归**

Run: `python -m pytest tests/test_volcengine_responses_client.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_volcengine_responses_client.py
git commit -m "test: 锁定客户端空提示词回退行为"
```

### Task 9: 更新 README 并做回归验证

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 README**

补充以下内容：

- 新增“翻译合规判断”模式；
- 该模式固定 JSON 输出；
- 该模式默认加载 `docs/视频内容审查.md`；
- 普通模式默认提示词来源为 `docs/视频复刻提示词.md`；
- 提示词保存改为按模式隔离。

- [ ] **Step 2: 运行核心相关测试子集**

Run: `python -m pytest tests/test_cache_store.py tests/test_app_mode_defaults.py tests/test_app_run_controller_state.py tests/test_app_cookie_state.py tests/test_task_scheduler_output_format.py tests/test_volcengine_responses_client.py -v`
Expected: PASS

- [ ] **Step 3: 如时间允许，运行全量测试**

Run: `python -m pytest`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: 更新翻译合规判断模式说明"
```

## 实施注意事项

- Task 1-7 走严格 TDD：先写失败测试，再最小实现，再回归；`main()` 接线通过 `build_persist_operations()` 与 `build_controller_payload()` 这两个桥接 helper 被红灯测试约束。
- Task 8 明确是特征测试，用来锁定客户端现状，解释为何必须在 `app.py` 归一化 prompt；不要把它当作新功能的 TDD 替代。
- 不修改 `TaskScheduler`、导出器和 `review_result.py` 的 JSON 解析逻辑。
- 如发现 `tests/test_app_cookie_state.py` 无需改动，也必须在执行记录里明确写出检查结论。
- 提交步骤仅在用户明确要求提交时执行；否则把这些 commit 信息当作推荐切分方案。
