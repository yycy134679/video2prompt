# AGENTS.md

## Project Overview

`video2prompt` is a single-package Python project for locally processing Douyin video links in bulk.
It provides a Streamlit UI that:

- parses Douyin pages and resolves accessible video URLs
- runs Volcengine Ark Responses API / Files API based video analysis
- supports a duration-check mode powered by `ffprobe`
- exports Excel results and, for category mode, Markdown ZIP bundles

This repository is not a monorepo. The main UI entry is `app.py`, application code lives in `src/video2prompt/`, and tests live in `tests/`.

## Architecture Overview

- `app.py`: Streamlit UI composition, session state, run control, export entry points
- `src/video2prompt/config.py`: load, merge, and validate `.env` + `config.yaml`
- `src/video2prompt/task_scheduler.py`: main AI execution pipeline, retries, pacing, circuit breaking, caching
- `src/video2prompt/duration_check_runner.py`: duration-check mode using `ffprobe`
- `src/video2prompt/parser_client.py`: Douyin parsing client
- `src/video2prompt/volcengine_responses_client.py`: Volcengine Responses API client
- `src/video2prompt/volcengine_files_client.py`: Volcengine Files API upload and polling
- `src/video2prompt/review_result.py`: structured review result parsing and normalization
- `src/video2prompt/excel_exporter.py`: Excel export using `docs/product_prompt_template.xlsx`
- `src/video2prompt/markdown_exporter.py`: category Markdown export and ZIP packaging
- `src/video2prompt/cache_store.py`: SQLite cache and prompt persistence
- `src/video2prompt/runtime_paths.py`: runtime path resolution for dev and packaged app modes
- `src/video2prompt/desktop_entry.py`: packaged macOS app entrypoint

## Repository Layout

```text
video2prompt/
├── app.py
├── config.yaml
├── .env.example
├── README.md
├── scripts/
│   ├── start.sh
│   └── build_macos_app.sh
├── packaging/
│   ├── video2prompt-macos.spec
│   └── bin/
│       └── ffprobe
├── src/video2prompt/
├── tests/
├── docs/
└── exports/
```

## Setup Commands

Create and prepare a virtual environment from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m ensurepip --upgrade
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

Create local environment variables:

```bash
cp .env.example .env
```

Set one of the following in `.env` before using AI analysis modes:

```env
VOLCENGINE_API_KEY=your_key_here
ARK_API_KEY=your_key_here
```

Additional local requirements:

- provide a valid Douyin web cookie and paste it into the UI
- ensure `ffprobe` is available in `PATH` for duration-check mode when running from source
- for macOS packaging, place a distributable `ffprobe` binary at `packaging/bin/ffprobe`

## Development Workflow

Activate the virtual environment before running project commands:

```bash
. .venv/bin/activate
```

Start the app with the project script:

```bash
bash scripts/start.sh
```

Or run Streamlit directly:

```bash
. .venv/bin/activate
python -m streamlit run app.py --server.headless=false
```

Important runtime facts:

- `scripts/start.sh` does not activate `.venv` for you
- `scripts/start.sh` only checks whether `.env` exists; it does not populate secrets
- the current product scope is Douyin video links only; no TikTok support and no Douyin image-post support
- packaged macOS builds initialize user-writable files under `~/Library/Application Support/video2prompt/`

## Testing Instructions

Run the full test suite:

```bash
. .venv/bin/activate
python -m pytest
```

Run focused tests for common areas:

```bash
. .venv/bin/activate
python -m pytest tests/test_config.py
python -m pytest tests/test_task_scheduler_output_format.py -k json
python -m pytest tests/test_task_scheduler_volcengine_retry.py
python -m pytest tests/test_markdown_exporter.py
python -m pytest tests/test_duration_check_runner.py
```

Test conventions and expectations:

- test framework: `pytest`
- pytest config lives in `pyproject.toml`
- `testpaths = ["tests"]`
- `pytest-asyncio` runs with `asyncio_mode = "auto"`
- when modifying scheduler, config, exporters, parser/model clients, add or update tests in the corresponding area
- when fixing a bug, write or update a failing test first, then implement the fix
- when changing UI state behavior, review both `tests/test_app_cookie_state.py` and `tests/test_app_run_controller_state.py`
- new logic-heavy modules should get unit tests; do not rely only on manual Streamlit clicking

## Code Style And Implementation Boundaries

- Target Python `3.11+`
- Follow existing type hints, `dataclass`, and small-module patterns
- Default to Simplified Chinese for user-facing copy, comments, docs, and commit messages
- Keep source files ASCII unless a file already uses non-ASCII heavily or Unicode is clearly justified
- Maintain import grouping as: standard library / third-party / local modules
- Keep `app.py` focused on UI orchestration; move config, scheduling, export, client, and runtime logic into `src/video2prompt/`
- Prefer simple, local changes over introducing new frameworks, ORMs, queues, or state layers
- There is no dedicated `ruff`, `black`, or `mypy` config in this repository; do not assume formatter or type-check CI exists
- When changing export format or template assumptions, verify compatibility with `docs/product_prompt_template.xlsx` and update export tests

## Configuration And Runtime Rules

Configuration sources:

- `.env`: secrets only
- `config.yaml`: runtime behavior, Volcengine settings, parser options, retries, circuit breakers, cache, logging

Current provider facts:

- the project currently supports only the Volcengine path
- `ConfigManager.get_provider_api_key()` resolves `VOLCENGINE_API_KEY` or `ARK_API_KEY`
- `AppConfig.provider` is fixed to `volcengine`

Important config constraints:

- `volcengine.endpoint_id` is required
- `volcengine.input_mode` supports only `auto`, `video_url`, `file_id`
- `volcengine.video_fps` must be within `0.2-5`
- `volcengine.files_expire_days` must be within `1-30`
- `parser.concurrency` must be within `1-50`
- `retry.*_cap_seconds` must be `>0` and `<=30`
- log level must be one of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

Default runtime outputs when running from source:

- SQLite cache: `data/cache.db`
- logs: `logs/app.log`
- exports: `exports/`
- last run snapshot: `exports/last_run_result.json`
- persisted UI cookie state: `~/Library/Application Support/video2prompt/user_state.yaml`

Packaged macOS app behavior:

- user-writable config and runtime files live under `~/Library/Application Support/video2prompt/`
- packaged app startup can succeed without an API key
- AI analysis calls validate the API key at request time, not during initial app boot

## Build And Packaging

This project is primarily delivered as a local Streamlit app. There is no current CI/CD pipeline, Dockerfile, or deployment automation.

For the first macOS distribution phase, the expected outputs are:

- `dist/video2prompt.app`
- `dist/video2prompt-macos.zip`

Prepare packaging prerequisites:

```bash
. .venv/bin/activate
python -m pip install pyinstaller
chmod +x packaging/bin/ffprobe
```

Build the macOS app:

```bash
bash scripts/build_macos_app.sh
```

Packaging notes:

- the build script validates `app.py`, `config.yaml`, `.env.example`, and required docs assets before building
- the build script checks that `packaging/bin/ffprobe` exists, is executable, and can report its version
- the generated macOS app is currently unsigned and not notarized
- first-time users may need to open the app via Finder context menu or allow it in macOS Security settings

## Security And Sensitive Data

- never commit `.env`, logs, cache databases, export files, or user state files
- never place real API keys, cookies, request headers, or direct media URLs in tests, docs, screenshots, or fixtures
- do not rely on log redaction as a reason to print secrets
- preserve the existing exception layering such as `ConfigError`, `ParserError`, and `ModelError` when changing network logic

## Debugging And Troubleshooting

Preferred debugging order:

1. inspect `.env` and `config.yaml`
2. inspect `logs/app.log`
3. run the relevant tests
4. inspect UI state and export artifacts

Common issues:

- `依赖未安装，请先执行: pip install -e .`: usually `.venv` is not activated or dependencies were not installed
- `未找到 .env`: create it from `.env.example`
- duration-check failures mentioning `ffprobe`: local ffmpeg/ffprobe is missing or unavailable
- parse failures: usually stale Douyin cookie; re-copy the cookie from a logged-in browser session
- export failures: verify `docs/product_prompt_template.xlsx` exists and `exports/` is writable

Known repository quirk:

- `scripts/start.sh` still prints a `GEMINI_API_KEY` hint in one error message, but the actual supported environment variables are `VOLCENGINE_API_KEY` and `ARK_API_KEY`

## Git And Pull Request Guidelines

Branching policy:

- low-risk doc edits, tiny config edits, and clearly local easy-to-revert fixes may be done on `main`
- all other work should start from an up-to-date `main` on a dedicated branch
- preferred branch names: `feature/中文描述`, `fix/中文描述`, `refactor/中文描述`, `chore/中文描述`

Commit expectations:

- use Chinese commit messages
- follow Conventional Commit style, for example `feat: 增加按类目导出 Markdown ZIP`
- do not use destructive git commands such as `git reset --hard` or `git checkout -- <file>` unless explicitly requested

Before opening or merging a PR:

- run the relevant `pytest` commands for changed areas
- update `README.md` when the change affects core workflow, configuration, export format, packaging, or development flow
- keep unrelated local changes untouched

## Agent Working Agreement

When operating in this repository, agents should:

- default to Simplified Chinese responses unless the user asks otherwise
- work from facts by reading the relevant implementation and tests before changing code
- keep changes KISS, YAGNI, DRY, and single-responsibility oriented
- avoid piling more business logic into `app.py`
- provide a short implementation approach before making non-trivial code changes
- decompose work when a change is likely to span more than three files
- verify commands, paths, and module names against the current repository instead of relying on memory
- prefer `rg`/targeted search over broad blind scanning

## Useful File References

- UI entry: `app.py`
- main config loader: `src/video2prompt/config.py`
- scheduler: `src/video2prompt/task_scheduler.py`
- runtime packaging entry: `src/video2prompt/desktop_entry.py`
- runtime path logic: `src/video2prompt/runtime_paths.py`
- packaging spec: `packaging/video2prompt-macos.spec`
- startup script: `scripts/start.sh`
- macOS build script: `scripts/build_macos_app.sh`
- tests root: `tests/`
- human-facing project overview: `README.md`
