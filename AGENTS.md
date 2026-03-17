# AGENTS.md

## 项目概览

`video2prompt` 是一个本地运行的 Streamlit 工具，用于批量处理抖音视频链接，并执行以下流程：

- 解析抖音页面，获取可访问的视频直链
- 调用火山方舟 Responses API / Files API 做视频解读
- 在“视频时长判断”模式下使用 `ffprobe` 探测时长
- 导出 Excel，按类目模式额外导出 Markdown ZIP

仓库是单包 Python 项目，不是 monorepo。UI 入口在 `app.py`，核心逻辑在 `src/video2prompt/`，测试在 `tests/`。

## 代理执行准则

- 默认使用简体中文回复、注释、文档和提交信息。
- 先基于事实工作。修改前先读相关实现和对应测试，不要凭猜测下结论。
- 优先保持 KISS、YAGNI、DRY 和单一职责，不要把业务逻辑继续堆进 `app.py`。
- 如果需求不够明确，先澄清；如果准备动手实现，先给出简短方案再改代码。
- 评估为超过 3 个文件的改动时，先拆成更小的任务单元，再逐步实施。
- 修复 Bug 时先补能复现问题的测试，再写修复代码。
- 改完后补一段简短分析：说明改动影响、潜在风险，以及建议补跑的测试。
- 若改动影响核心流程、配置方式、导出格式或开发流程，同步更新 `README.md`。
- 做文档任务也尽量使用真实命令验证，不要照抄经验性说法。

## 仓库结构

- `app.py`：Streamlit 页面、运行控制、导出入口、会话状态。
- `config.yaml`：业务配置，包含火山模型、解析并发、重试、熔断、缓存、日志。
- `.env.example`：环境变量模板，实际运行前复制为 `.env`。
- `scripts/start.sh`：启动脚本，要求依赖已安装且 `.env` 已存在。
- `src/video2prompt/config.py`：`.env` + `config.yaml` 加载、合并与校验。
- `src/video2prompt/task_scheduler.py`：AI 解读主调度器，负责解析、缓存、重试、熔断、节奏控制。
- `src/video2prompt/duration_check_runner.py`：时长判断模式，依赖 `ffprobe`。
- `src/video2prompt/volcengine_responses_client.py`：火山 Responses API 调用。
- `src/video2prompt/volcengine_files_client.py`：火山 Files API 上传与轮询。
- `src/video2prompt/review_result.py`：JSON 输出解析和“能否翻译”规则收敛。
- `src/video2prompt/excel_exporter.py`：基于 `docs/product_prompt_template.xlsx` 导出 Excel。
- `src/video2prompt/markdown_exporter.py`：按类目导出 Markdown 并打 ZIP。
- `src/video2prompt/cache_store.py`：SQLite 缓存与系统提示词持久化。
- `tests/`：pytest 测试，按模块拆分。
- `docs/`：需求说明、规则说明和 Excel 模板文件。
- `exports/`、`data/`、`logs/`：运行产物目录，默认不提交。

## 环境准备

推荐在仓库根目录执行：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m ensurepip --upgrade
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

运行前还需要：

- 复制环境变量模板：`cp .env.example .env`
- 在 `.env` 中填写 `VOLCENGINE_API_KEY` 或 `ARK_API_KEY`
- 准备可用的抖音网页 Cookie，并在页面中手动粘贴保存
- 若使用“视频时长判断”模式，确保 `ffprobe` 在 `PATH` 中

## 常用开发命令

激活虚拟环境：

```bash
. .venv/bin/activate
```

启动应用：

```bash
bash scripts/start.sh
```

直接运行 Streamlit：

```bash
. .venv/bin/activate
python -m streamlit run app.py --server.headless=false
```

注意事项：

- `scripts/start.sh` 不会自动激活 `.venv`，先手动激活再执行。
- 启动脚本只检查 `.env` 是否存在，不会帮你补全密钥。
- 当前项目只支持抖音视频，不支持 TikTok 链接，也不支持抖音图集。

## 测试说明

全量测试：

```bash
. .venv/bin/activate
python -m pytest
```

常用子集：

```bash
. .venv/bin/activate
python -m pytest tests/test_config.py
python -m pytest tests/test_task_scheduler_output_format.py -k json
python -m pytest tests/test_task_scheduler_volcengine_retry.py
python -m pytest tests/test_markdown_exporter.py
python -m pytest tests/test_duration_check_runner.py
```

测试约定：

- 测试框架是 `pytest`，配置在 `pyproject.toml`。
- `testpaths = ["tests"]`
- `pytest-asyncio` 使用 `asyncio_mode = "auto"`。
- 修改调度器、配置、导出器、解析/模型客户端时，必须补对应测试。
- 新增纯逻辑模块时优先写单元测试，不要只靠手工点页面。
- 改动 UI 交互状态时，同时检查 `tests/test_app_cookie_state.py` 和 `tests/test_app_run_controller_state.py` 是否需要更新。

## 代码风格与实现边界

- 保持 Python 3.11+ 兼容写法，延续当前项目的类型注解、`dataclass` 和小模块拆分。
- docstring、注释、用户可见文案默认使用简体中文。
- 导入顺序遵循“标准库 / 第三方 / 本地模块”。
- 除非文件本身已大量使用中文源码或确有必要，否则尽量保持源码 ASCII。
- `app.py` 负责 UI 编排；配置、调度、导出、客户端逻辑应下沉到 `src/video2prompt/`。
- 不要无理由引入新的框架、状态管理层、任务队列或 ORM。
- 当前仓库没有独立的 `ruff`、`black`、`mypy` 配置，不要假设存在自动格式化或静态检查流水线。
- 修改导出格式时，必须检查 `docs/product_prompt_template.xlsx` 兼容性，并同步更新导出测试。

## 配置与运行机制

关键配置来源：

- `.env`：只放密钥
- `config.yaml`：放火山模型、解析、重试、熔断、缓存、日志等运行参数

当前 provider 事实：

- 项目现在只保留火山方舟路径
- `ConfigManager.get_provider_api_key()` 实际返回 `VOLCENGINE_API_KEY` 或 `ARK_API_KEY`
- `AppConfig.provider` 固定返回 `volcengine`

关键配置约束：

- `volcengine.endpoint_id` 必填
- `volcengine.input_mode` 仅支持 `auto` / `video_url` / `file_id`
- `volcengine.video_fps` 必须在 `0.2-5`
- `volcengine.files_expire_days` 必须在 `1-30`
- `parser.concurrency` 必须在 `1-50`
- `retry.*_cap_seconds` 必须 `>0` 且 `<=30`
- 日志级别必须是 `DEBUG/INFO/WARNING/ERROR/CRITICAL`

运行产物默认位置：

- SQLite 缓存：`data/cache.db`
- 日志：`logs/app.log`
- 导出结果：`exports/`
- 上次运行结果恢复文件：`exports/last_run_result.json`
- 用户 Cookie 持久化：`~/Library/Application Support/video2prompt/user_state.yaml`

## 安全与敏感信息

- 不要提交 `.env`、日志、缓存数据库、导出文件。
- 不要把真实 API Key、Cookie、请求头、文件直链写进测试、文档或截图。
- 日志虽然做了基础脱敏，但不要依赖脱敏去打印敏感信息。
- 修改网络客户端时，优先复用现有错误分层，不要绕开 `ConfigError`、`ParserError`、`ModelError` 等异常体系。

## 调试与排错

优先排查顺序：

1. 检查 `.env` 与 `config.yaml`
2. 查看 `logs/app.log`
3. 运行对应测试确认是否已有覆盖
4. 再看 UI 状态和导出产物

常见问题：

- `依赖未安装，请先执行: pip install -e .`：通常是没有激活 `.venv` 或依赖未安装。
- `未找到 .env`：先执行 `cp .env.example .env`。
- 时长判断失败且提示 `ffprobe`：本机未安装 ffmpeg/ffprobe。
- 解析失败：优先检查页面中保存的抖音 Cookie 是否过期，必要时重新复制。
- 导出失败：先确认 `docs/product_prompt_template.xlsx` 存在且未损坏，再检查 `exports/` 是否可写。

## 构建与交付

当前仓库主要交付方式是本地运行的 Streamlit 应用，没有现成的 CI/CD、Dockerfile 或部署脚本。

可接受的交付验证顺序：

1. 在 `.venv` 中安装 `-e ".[dev]"`
2. 运行相关 `pytest`
3. 如改动影响 UI、Cookie 状态或导出，手动启动 `streamlit run app.py`

除非任务明确要求，不要擅自补 Docker、发布流水线或额外部署脚本。

## Git 工作流

纯文档改动、很小的配置改动、明显低影响且易回滚的小修复，可以直接在 `main` 处理；其余改动默认不要直接改 `main`。

推荐流程：

1. 先确认本地 `main` 已同步最新代码
2. 从最新 `main` 切工作分支
3. 分支名使用 `feature/中文描述`、`fix/中文描述`、`refactor/中文描述`、`chore/中文描述`
4. 在分支上完成修改、测试、自检后，再合并回 `main`

提交要求：

- 提交信息使用中文
- 遵循约定式提交，例如 `feat: 增加按类目导出 Markdown ZIP`
- 不要执行 `git reset --hard`、`git checkout -- <file>` 或强制覆盖用户未提交改动，除非用户明确要求

## 代理工作建议

- 开始前优先阅读 `app.py`、`src/video2prompt/config.py`、相关模块和对应测试。
- 搜索优先用 `rg`，不要盲目全仓扫描。
- 改配置字段、导出列、任务状态、异常文案时，联动检查测试和 README。
- 如果工作区已有未提交改动，先理解并避开，不要擅自回滚。
- 文档型任务也尽量用真实命令验证；至少确认命令、路径、模块名与仓库现状一致。
