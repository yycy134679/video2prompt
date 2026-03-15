# AGENTS.md

## 项目概览

`video2prompt` 是一个本地 Streamlit 工具，用于批量解析抖音/TikTok 链接，并执行以下任务：

- 生成视频复刻提示词
- 按类目聚合视频分析结果
- 判断视频时长是否 `<=15s`
- 导出 Excel 或按类目导出 Markdown ZIP

当前仓库是单包 Python 项目，不是 monorepo。核心代码在 `src/video2prompt/`，UI 入口是 `app.py`。

## 基本约束

- 默认使用简体中文编写回复、文档、注释和提交信息。
- 请进入虚拟环境（`.venv`）安装依赖和测试。
- 遵循 KISS、YAGNI、DRY，避免为了“以后可能会用到”而提前抽象。
- 优先保持单一职责：UI、配置、调度、客户端、导出逻辑分层清晰，不要把新逻辑堆进 `app.py`。
- 基于事实修改代码，先读现有实现和测试，再动手。
- 改完代码后，补一段简短的变更分析，并给出下一步可选改进建议。
- 如果改动影响核心流程、配置方式、导出格式或开发方式，同步更新 README。

## 仓库结构

- `app.py`：Streamlit 入口，负责页面交互、运行控制、导出按钮和会话状态。
- `config.yaml`：业务配置，包含 provider、解析并发、重试、熔断、缓存和日志。
- `.env.example`：环境变量模板，实际运行需要复制为 `.env`。
- `scripts/start.sh`：启动脚本，依赖已激活的虚拟环境和 `.env` 文件。
- `src/video2prompt/config.py`：`.env` + `config.yaml` 加载、合并与校验。
- `src/video2prompt/task_scheduler.py`：主流程调度器，负责解析、缓存、模型调用、重试、熔断和节奏控制。
- `src/video2prompt/duration_check_runner.py`：时长判断模式，依赖 `ffprobe`。
- `src/video2prompt/review_result.py`：模型 JSON 输出解析和“能否翻译”规则收敛。
- `src/video2prompt/excel_exporter.py`：基于 `docs/product_prompt_template.xlsx` 导出 Excel。
- `src/video2prompt/markdown_exporter.py`：按类目导出 Markdown 并打 ZIP。
- `src/video2prompt/cache_store.py`：SQLite 缓存与系统提示词持久化。
- `tests/`：pytest 测试，按模块拆分。
- `docs/`：需求、规则、模板文件；`docs/product_prompt_template.xlsx` 是运行依赖，不要误删。
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

已验证以上安装命令在当前仓库可执行。

运行前还需要：

- 复制环境变量模板：`cp .env.example .env`
- 在 `.env` 中填写 `GEMINI_API_KEY` 或 `VOLCENGINE_API_KEY` / `ARK_API_KEY`
- 确认本地抖音解析服务可访问，默认地址为 `http://localhost:80`
- 如果要使用“视频时长判断”模式，确保 `ffprobe` 在 `PATH` 中

## 常用开发命令

激活虚拟环境：

```bash
. .venv/bin/activate
```

启动应用：

```bash
bash scripts/start.sh
```

注意：

- `scripts/start.sh` 不会自动激活 `.venv`，请先激活再执行。
- 当前仓库若缺少 `.env`，启动脚本会直接失败并提示复制 `.env.example`。

如果只想直接运行 Streamlit：

```bash
. .venv/bin/activate
python -m streamlit run app.py --server.headless=false
```

## 测试说明

全量测试：

```bash
. .venv/bin/activate
python -m pytest
```

已验证当前测试命令可执行，现状为全量通过。

常用子集运行方式：

```bash
. .venv/bin/activate
python -m pytest tests/test_config.py
python -m pytest tests/test_task_scheduler_output_format.py -k json
```

测试约定：

- 测试框架是 `pytest`，配置写在 `pyproject.toml`
- `testpaths = ["tests"]`
- `pytest-asyncio` 以 `asyncio_mode = "auto"` 运行
- 修改调度器、配置、导出器、客户端时，必须补对应测试
- 新增模块时，优先为纯逻辑层补单元测试，不要只依赖手工点页面

## 代码风格

- 保持 Python 3.11+ 兼容风格，延续当前项目广泛使用的类型注解、`dataclass`、小模块拆分。
- docstring、注释、用户可见文案默认使用简体中文。
- 导入顺序遵循“标准库 / 第三方 / 本地模块”。
- 除非文件原本就是中文语义密集型内容，否则尽量保持源码为 ASCII；必要的中文文案按现有风格保留。
- 不要无理由引入新的框架、状态管理层、任务队列或 ORM。
- `app.py` 主要负责 UI 编排；业务逻辑应下沉到 `src/video2prompt/`。
- 修改导出格式时，必须检查 `docs/product_prompt_template.xlsx` 兼容性，并同步更新导出测试。

当前仓库没有独立的 `ruff`、`black`、`mypy` 配置。不要假设存在自动格式化或静态检查流水线；以现有测试和清晰实现为准。

## 配置与运行机制

关键配置文件：

- `.env`：仅放密钥
- `config.yaml`：放 provider、超时、并发、重试、熔断、缓存、日志

provider 约束：

- `provider=gemini` 时，读取 `GEMINI_API_KEY`
- `provider=volcengine` 时，读取 `VOLCENGINE_API_KEY` 或 `ARK_API_KEY`
- `provider=volcengine` 时，`volcengine.endpoint_id` 必填
- 当前配置校验要求 `volcengine.target_model` 以 `seed-2.0` 开头

运行产物：

- SQLite 缓存默认在 `data/cache.db`
- 日志默认写入 `logs/app.log`
- 导出结果默认写入 `exports/`
- `exports/last_run_result.json` 可能被 UI 用于恢复上次结果

## 安全与敏感信息

- 不要提交 `.env`、日志、缓存数据库、导出文件。
- 日志层有基础 API Key 脱敏，但不要依赖脱敏来“安全地”打印敏感信息。
- 不要把真实密钥写进测试、fixture、文档示例或截图。
- 修改网络客户端时，优先复用现有错误类型和重试机制，不要绕开 `ConfigError`、`ParserError`、`GeminiError` 等分层异常。

## 构建与交付

当前仓库主要交付方式是本地运行的 Streamlit 应用，没有现成的 CI/CD、容器构建或部署脚本。

可接受的交付验证顺序：

1. 在 `.venv` 中安装 `-e ".[dev]"`
2. 运行相关 pytest
3. 如改动影响 UI 或导出，手动启动 `streamlit run app.py`

除非任务明确要求，不要擅自补充 Dockerfile、打包流水线或发布脚本。

## 调试与排错

常见问题：

- `依赖未安装，请先执行: pip install -e .`：通常是没有激活 `.venv`
- `未找到 .env`：先执行 `cp .env.example .env`
- 时长判断失败且提示 `ffprobe`：本机未安装 ffmpeg/ffprobe
- 解析失败：优先检查本地解析服务是否在 `config.yaml` 指定地址运行
- 导出异常：先确认 `docs/product_prompt_template.xlsx` 存在且未损坏

排查顺序建议：

1. 先看 `config.yaml` 和 `.env`
2. 再看 `logs/app.log`
3. 最后看对应测试是否已经覆盖该场景

## Git 与提交规则

纯文档改动、极小配置改动、明显低影响的小修复，可以直接在 `main` 处理；除此之外，默认不要直接改 `main`。

推荐流程：

1. 从最新 `main` 切工作分支
2. 分支名使用 `feature/中文描述`、`fix/中文描述`、`refactor/中文描述`、`chore/中文描述`
3. 在分支上完成修改、测试、自检
4. 再合并回 `main`

提交信息使用中文，并遵循约定式提交，例如：

```text
feat: 增加按类目导出 Markdown ZIP
fix: 修复火山文件上传重试逻辑
docs: 完善 AGENTS 使用说明
```

不要执行这些操作，除非用户明确要求：

- `git reset --hard`
- `git checkout -- <file>`
- 强制覆盖用户已有未提交改动

## 代理工作建议

- 先读 `app.py`、`config.py`、相关模块和对应测试，再决定改动点。
- 优先使用 `rg` 搜索，避免盲扫。
- 改动配置字段、导出列、任务状态或异常文案时，联动检查测试和文档。
- 如果工作区已有用户未提交改动，先理解并避开，不要擅自回滚。
- 做文档型任务时，也要尽量用真实命令验证，而不是凭经验填写。
