# video2prompt

批量解析抖音视频链接，支持 AI 模型解读与视频时长判断，结果导出为 Excel，支持一键导入 Lumen 平台。

## 功能亮点

- **批量视频解读**：输入 pid 和抖音链接列表，自动解析视频直链并调用 AI 模型分析视频内容
- **多模型支持**：支持 Gemini（中转站）和火山方舟（Doubao / Seed 系列），通过配置一键切换
- **视频翻译审查**：结构化审查 6 项指标（儿童口播、多人口播、价格促销、字幕、贴纸花字、中文字符），自动判定能否翻译到 TikTok
- **视频复刻提示词**：分析爆款抖音视频，生成 Sora 英文提示词用于 TikTok 内容复刻
- **按类目分析模式**：支持输入 `pid + 链接 + 类目` 三列，自动将结果按类目聚合
- **视频时长判断模式**：仅解析直链并通过 `ffprobe` 判断时长，固定阈值 `<=15s`，支持双 Excel 导出
- **智能缓存**：基于链接 + Prompt 的 SHA-256 哈希去重，相同任务不重复调用模型
- **弹性容错**：重试退避 + 熔断器 + 限流慢启动 + 视频拉取失败自动重解析
- **高并发解析节奏**：支持 50 解析槽位，单槽位解析完成后冷却 3 秒再接下一条
- **实时状态**：Streamlit 界面实时显示每条任务的状态、重试次数、耗时、Token 用量
- **可中断执行**：运行中支持一键停止，立即取消待解析/解析中/模型解读中任务
- **多格式导出**：支持模型结果 Excel、类目 Markdown ZIP，以及时长判断双 Excel 导出

## 前置条件

- Python 3.11+
- 抖音解析服务（本地 Docker 部署，默认 `http://localhost:80`）
- `ffprobe`（用于视频时长探测）
- API Key：Gemini 或火山方舟（二选一，**仅模型解读模式需要**）

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. 配置环境

复制 `.env.example` 为 `.env`，填写对应的 API Key：

```bash
cp .env.example .env
```

| 环境变量                              | 说明                  |
| ------------------------------------- | --------------------- |
| `GEMINI_API_KEY`                      | Gemini 中转站 API Key |
| `VOLCENGINE_API_KEY` 或 `ARK_API_KEY` | 火山方舟 API Key      |

在 `config.yaml` 中设置 `provider` 为 `gemini` 或 `volcengine`，并按需调整模型参数。
当 `provider=volcengine` 时，`volcengine.endpoint_id` 必填，`target_model` 需为 `seed-2.0-*`，并可通过 `volcengine.reasoning_effort` 调节思考强度（`minimal/low/medium/high`）。

### 3. 启动服务

```bash
bash scripts/start.sh
```

浏览器会自动打开 Streamlit 界面。

## 使用流程

1. 选择**运行模式**：`视频复刻提示词`（默认）/ `按类目分析` / `视频时长判断`
2. 在输入区填写任务：
   - 默认模式：输入 **pid 列表**和**抖音链接列表**（按行一一对应）
   - 按类目分析：输入 **pid / 抖音链接 / 类目** 三列（按行对齐，空类目自动归为「未分类」）
   - 时长判断：输入 **pid / 抖音链接** 两列，执行“解析 + 时长探测”，不调用模型
3. 在模型解读模式下可编辑或加载 **提示词**（DEFAULT_USER_PROMPT），并选择输出格式
4. 按需调整**运行时配置**中的常用项（如并发、FPS、输出格式），仅本次运行生效；高级参数请改 `config.yaml`
5. 点击 **开始执行**，实时查看任务进度（未真正进入解析槽位的任务显示为「待解析」）
6. 如需提前终止，点击 **停止**：会取消待解析、解析中、模型解读中的未完成任务
7. 执行完成或停止后：
   - 默认模式：导出 Excel
   - 按类目分析：可导出 Excel（含类目列）或导出 Markdown（按类目 ZIP）
   - 时长判断：一键生成两份 Excel（`<=15s`、`>15s 或探测失败（含解析失败）`）
   - 模型解读模式下，导出仅包含已完成且有模型输出的任务

## 项目结构

```
video2prompt/
├── app.py                          # Streamlit 入口与 UI
├── config.yaml                     # 业务配置（模型、解析、重试、熔断等）
├── .env                            # 敏感凭据（API Key，不入库）
├── scripts/
│   └── start.sh                    # 一键启动脚本
├── src/video2prompt/
│   ├── config.py                   # YAML + .env 配置管理，支持运行时覆盖
│   ├── models.py                   # 数据模型（AppConfig / Task / TaskState 等）
│   ├── task_scheduler.py           # 核心任务调度器：解析 → 缓存 → 模型 → 重试 → 熔断
│   ├── duration_check_runner.py    # 时长判断执行器：解析 → ffprobe → 分桶
│   ├── parser_client.py            # 抖音解析客户端（获取无水印视频直链）
│   ├── gemini_client.py            # Gemini API 客户端
│   ├── volcengine_client.py        # 火山方舟 Chat Completions 客户端
│   ├── volcengine_files_client.py  # 火山方舟 Files API（视频上传/轮询/清理）
│   ├── volcengine_responses_client.py  # 火山方舟 Responses API
│   ├── volcengine_batch_client.py  # 火山方舟批量 Chat 接口
│   ├── video_analysis_client.py    # 统一协议接口（Protocol）
│   ├── review_result.py            # 审查结果解析与规则校正
│   ├── cache_store.py              # SQLite 异步缓存
│   ├── circuit_breaker.py          # 熔断器（连续失败 + 窗口失败率）
│   ├── validator.py                # 输入校验（行对齐、域名合法性）
│   ├── excel_exporter.py           # Excel 模板导出
│   ├── duration_excel_exporter.py  # 时长判断双 Excel 导出
│   ├── markdown_exporter.py        # Markdown 按类目导出 + ZIP 打包
│   ├── logging_utils.py            # 日志（按天滚动 + API Key 脱敏）
│   └── errors.py                   # 分层异常体系
├── tests/                          # 单元测试
├── docs/                           # 文档（提示词模板、审查规则等）
├── exports/                        # 导出结果目录
├── data/                           # 缓存数据库
└── logs/                           # 日志文件
```

## 模型服务商配置

### Gemini

通过中转站访问 Gemini API，支持视频直链传入。

```yaml
provider: "gemini"

gemini:
  base_url: "https://qfgapi.com"
  model: "gemini-3-flash-preview"
  thinking_level: "high"           # minimal / low / medium / high
  media_resolution: "media_resolution_medium"
  video_fps: 2.0                   # 视频采样帧率
  fps_fallback: 1.0                # 主帧率失败后回退值
  timeout_seconds: 300
```

### 火山方舟（Volcengine）

支持三种 API 调用模式，通过 `input_mode` 配置：

| 模式             | 说明                          | 视频大小限制 |
| ---------------- | ----------------------------- | ------------ |
| `chat_url`       | 直接传视频 URL                | ≤ 50 MB      |
| `responses_file` | 下载 → 上传 → 轮询激活 → 调用 | ≤ 512 MB     |
| `auto`（默认）   | 根据视频大小自动选择          | 自适应       |

```yaml
provider: "volcengine"

volcengine:
  base_url: "https://ark.cn-beijing.volces.com/api/v3"
  endpoint_id: "ep-xxxxxxxx"       # 推理接入点（实际作为请求体 model）
  target_model: "seed-2.0-lite"    # 标注用，不作为请求参数
  timeout_seconds: 300
  video_fps: 2.0
  thinking_type: "enabled"         # enabled / disabled / auto
  reasoning_effort: "medium"       # minimal / low / medium / high
  input_mode: "auto"               # auto / chat_url / responses_file
  use_batch_chat: false            # 批量 Chat 模式（灰度）
  batch_size: 20
```

## 弹性容错机制

### 重试与退避

- **解析服务**：默认退避序列 `[10, 30]` 秒，可配置；最多重试 2 次
- **模型服务**：默认退避序列 `[5, 15]` 秒，可配置；最多重试 2 次
- **退避上限**：单次退避最终等待（含抖动）不超过 `30s`
- **突发限流慢启动**：检测到 `RequestBurstTooFast` 时动态增大惩罚因子（最大 8x），成功后逐步衰减
- **视频拉取失败自动重解析**：模型报视频资源拉取失败时，自动重新解析获取新直链

### 熔断器

双维度判断，解析服务和模型服务各自独立监控：

| 维度                     | 解析服务默认值 | 模型服务默认值 |
| ------------------------ | -------------- | -------------- |
| 连续失败次数             | 4              | 4              |
| 窗口失败率（5 分钟窗口） | 60%            | 50%            |

触发熔断后，所有未完成任务标记为 `CIRCUIT_BREAK` 并停止执行。4xx 客户端错误和视频拉取失败不计入熔断统计。

## 缓存策略

- **存储引擎**：本地 SQLite（`data/cache.db`）
- **缓存键**：`SHA-256(link) + SHA-256(prompt)` 复合主键
- **缓存内容**：`aweme_id`、`video_url`、`gemini_output`、`can_translate`、`fps_used`
- **冲突处理**：同键重跑自动更新（`ON CONFLICT DO UPDATE`）
- **Prompt 持久化**：编辑后保存到 SQLite，下次启动自动加载
- 可通过 `cache.include_prompt_hash_in_key` 控制是否将 Prompt 纳入缓存键

## 任务状态机

```
WAITING → PARSING → INTERVAL → INTERPRETING → COMPLETED
                                             → FAILED
                                             → CIRCUIT_BREAK
                                             → CANCELLED
```

- `WAITING`：待解析（尚未占用解析槽位）
- `PARSING`：解析中（已实际发起解析请求）
- `INTERPRETING`：模型解读中

每次状态变更通过回调实时刷新 UI 表格，展示以下信息：

| 字段                              | 说明                           |
| --------------------------------- | ------------------------------ |
| 状态                              | 当前任务阶段                   |
| 解析重试 / 模型重试               | 各自重试次数                   |
| 耗时(s)                           | 单任务总耗时                   |
| 能否翻译                          | 审查结论                       |
| FPS                               | 实际使用的采样帧率             |
| prompt_tokens / completion_tokens | Token 用量                     |
| reasoning_tokens                  | 思考 Token（仅 thinking 模式） |
| request_id                        | 模型请求 ID（便于排查）        |
| api_mode                          | 实际使用的 API 模式            |

## 开发

### 运行测试

```bash
source .venv/bin/activate
pytest
```

### 主要依赖

| 包              | 用途             |
| --------------- | ---------------- |
| `streamlit`     | Web UI 框架      |
| `httpx`         | 异步 HTTP 客户端 |
| `aiosqlite`     | 异步 SQLite 驱动 |
| `openpyxl`      | Excel 读写       |
| `PyYAML`        | YAML 配置解析    |
| `python-dotenv` | 环境变量加载     |

## License

Private / Internal Use Only
