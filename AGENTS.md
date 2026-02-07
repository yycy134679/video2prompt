# Project Guidelines

## Code Style

- Python ≥ 3.11，使用 `dataclass`（非 Pydantic）定义数据模型
- 所有 docstring、注释、枚举值使用**中文**（如 `TaskState` 的值 `"等待中"`, `"解析中"`）
- src layout：源码在 `src/video2prompt/`，入口 `app.py` 在根目录
- 异步优先：所有 I/O 操作使用 `async/await`，HTTP 用 `httpx.AsyncClient`，SQLite 用 `aiosqlite`
- 示例风格参考 [src/video2prompt/gemini_client.py](src/video2prompt/gemini_client.py) 和 [src/video2prompt/task_scheduler.py](src/video2prompt/task_scheduler.py)

## Architecture

```
Streamlit UI (app.py)
  ├── ConfigManager        — .env(密钥) + config.yaml(业务参数)，支持运行时覆盖不回写
  ├── CacheStore           — SQLite 复合主键 (link_hash, prompt_hash)，SHA-256
  ├── InputValidator       — 批量输入按行对齐 pid ↔ 链接
  ├── TaskScheduler        — 核心编排：Semaphore 并发 + gather 并行 + Event 取消
  │     ├── BatchManager   — 批次拆分 + 批间随机休息 5-15 分钟
  │     ├── CircuitBreaker — Parser/Gemini 各一个，双维度(连续失败+窗口失败率)
  │     ├── ParserClient   — Douyin_TikTok_Download_API (localhost:80)
  │     └── GeminiClient   — huandutech 中转站原生 Gemini REST API
  └── ExcelExporter        — 基于 openpyxl 模板导出
```

**关键数据流**：输入链接 → 缓存检查 → Parser 获取无水印直链 → 选链(H264≤1080p 最高码率) → Gemini 视频解读 → 缓存结果 → Excel 导出

## Build and Test

```bash
pip install -e ".[dev]"          # 安装含开发依赖
bash scripts/start.sh            # 启动 Streamlit（或 PYTHONPATH=src python -m streamlit run app.py）
pytest                           # 运行测试（asyncio_mode="auto"）
```

## Project Conventions

- **httpx 客户端注入模式**：`ParserClient`/`GeminiClient` 接受可选 `http_client` 参数；None 时内部创建并通过 `close_client` 标志管理生命周期——参见 [gemini_client.py](src/video2prompt/gemini_client.py)
- **异常分层**：`Video2PromptError` → `ParserError`/`GeminiError`/`ConfigError`/`CircuitBreakerOpenError`；HTTP 429/5xx → 可重试子类，其他 4xx → 不可重试——定义在 [errors.py](src/video2prompt/errors.py)
- **全局暂停**：退避期间 `_global_pause_until` + `asyncio.Lock` 暂停整个队列出队——参见 [task_scheduler.py](src/video2prompt/task_scheduler.py)
- **Task 是可变 dataclass**：调度过程中原地修改状态，通过 `on_update` 回调通知 UI
- **fps 降级**：Gemini 先尝试 `video_fps`(2.0)，fps 相关错误降级到 `fps_fallback`(1.0)
- **视频直链失效自动重解析**：Gemini 资源拉取失败 → 重新调 Parser 获取直链再重试
- **选链禁止使用 `download_addr`**（含水印），优先 `bit_rate[]` H264≤1080p，回退 `play_addr_h264` → `play_addr`
- **配置覆盖**：支持点路径 key (如 `parser.concurrency`)，仅内存生效不回写文件
- **不使用 `google-generativeai` SDK**，直接 httpx 调用原生 Gemini REST API，不发送 `systemInstruction`
- **测试**：pytest + respx mock httpx，当前仅单元测试（同步方法），无集成测试

## Integration Points

| 服务                       | 地址                         | 说明                                                      |
| -------------------------- | ---------------------------- | --------------------------------------------------------- |
| Douyin_TikTok_Download_API | `localhost:80`               | 本地 Docker 部署，`GET /api/hybrid/video_data?url={link}` |
| huandutech Gemini 中转站   | `https://api.huandutech.com` | Bearer Token，原生 Gemini `generateContent` 格式          |

## Security

- `GEMINI_API_KEY` 仅存于 `.env`（已 gitignore），通过 `python-dotenv` 加载
- [logging_utils.py](src/video2prompt/logging_utils.py) 的 `SecretMaskFilter` 自动脱敏所有日志中的 API Key
- HTTP 响应文本截断 (`[:300]`/`[:500]`) 防止日志泄露大量数据
- Excel 导出不包含任何凭据信息
