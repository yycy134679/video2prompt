# video2prompt

批量解析抖音 / TikTok 视频链接，调用 AI 模型完成内容分析，并导出 Excel 或 Markdown 结果。

当前版本新增了面向 mac 非技术同事的本地交付层：

- 提供 `scripts/mac/安装.command`、`scripts/mac/启动.command`、`scripts/mac/停止.command`
- 首次配置改为应用内“首次设置 / 环境检查”页面
- 内置受管本地解析服务，不再要求同事手动安装 `git`、Docker 或单独维护解析仓库

## 给谁看

- 维护者：先读本文档
- 非技术同事：优先阅读 [docs/mac-非技术同事使用说明.md](docs/mac-非技术同事使用说明.md)

## 主要能力

- 批量解析抖音 / TikTok 视频链接，生成视频直链
- 支持火山方舟与 Gemini 两种模型服务商
- 支持 `视频复刻提示词`、`按类目分析`、`视频时长判断` 三种模式
- 支持缓存、重试退避、熔断、运行时参数覆盖
- 支持 Excel 导出、类目 Markdown ZIP 导出、时长模式双 Excel 导出

## mac 非技术交付方式

### 首次安装

1. 下载项目 ZIP 并解压
2. 双击运行 [scripts/mac/安装.command](scripts/mac/安装.command)
3. 双击运行 [scripts/mac/启动.command](scripts/mac/启动.command)
4. 浏览器打开后，先进入“首次设置 / 环境检查”完成配置

### 运行时会发生什么

- 应用自身会安装到项目根目录下的 `.venv`
- 受管解析服务会安装到 `.managed/douyin_tiktok_download_api`
- Streamlit PID / 日志会写到 `.runtime/`
- 解析服务会固定监听 `http://127.0.0.1:18080`

### 受管解析服务

- 底层仍使用 [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API)
- 当前固定版本：`V4.1.2`
- 启动时会自动写入以下受管配置：
  - `API.Host_IP = 127.0.0.1`
  - `API.Host_Port = 18080`
  - `Web.PyWebIO_Enable = false`
- 抖音 / TikTok Cookie 由本工具设置页写入对应 YAML 配置

## 应用内设置

首次打开页面后，建议先完成以下配置：

- `VOLCENGINE_API_KEY` 或 `ARK_API_KEY`
- `volcengine.endpoint_id`
- 抖音 Cookie

进阶配置放在设置页的“进阶设置”里：

- `GEMINI_API_KEY`
- TikTok Cookie
- `ffprobe` 检查状态

说明：

- API Key 保存在本地 `.env`
- 业务配置保存在 `config.yaml`
- parser Cookie 保存在受管解析服务源码目录里的 YAML 文件
- 设置页默认不回显完整 Cookie 或 API Key

## 开发者快速开始

### 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
bash scripts/start.sh
```

`scripts/start.sh` 仍适用于开发调试；即使 `.env` 还没准备好，也可以先进入设置页。

### 运行测试

```bash
source .venv/bin/activate
pytest
```

## 配置说明

### 模型服务商

- 默认主流程：`volcengine`
- 进阶可切换：`gemini`

运行任务时才会校验对应 provider 的密钥和必要配置；应用启动时不再因为缺少 API Key 直接退出。

### 默认 parser 地址

```yaml
parser:
  base_url: "http://127.0.0.1:18080"
```

### 时长判断模式

- 依赖 `ffprobe`
- 不纳入首次安装阻塞项
- 只有进入“视频时长判断”模式时才需要安装 `ffmpeg`

## 目录结构

```text
video2prompt/
├── app.py
├── config.yaml
├── .env
├── scripts/
│   ├── start.sh
│   └── mac/
│       ├── common.sh
│       ├── 安装.command
│       ├── 启动.command
│       └── 停止.command
├── src/video2prompt/
│   ├── config.py
│   ├── managed_parser_service.py
│   ├── local_service_cli.py
│   ├── task_scheduler.py
│   ├── duration_check_runner.py
│   ├── parser_client.py
│   ├── gemini_client.py
│   ├── volcengine_client.py
│   └── ...
├── docs/
│   ├── mac-非技术同事使用说明.md
│   └── ...
├── .managed/                      # 受管解析服务（运行后生成，不入库）
├── .runtime/                      # 本地 PID / 日志（运行后生成，不入库）
├── data/
├── exports/
└── logs/
```

## 故障排查

### 页面能打开，但无法执行任务

优先检查：

- 设置页里的 provider 密钥是否已配置
- 火山 `endpoint_id` 是否已填写
- 解析服务是否已安装、已启动、健康检查通过
- 抖音 Cookie 是否已填写且仍然有效

### `安装.command` 无法运行

常见原因：

- 没有安装 Python 3.11+
- macOS 安全策略阻止未知来源脚本
- 机器无法访问 Python 官网、PyPI 或 GitHub

### parser 启动失败

优先看：

- [scripts/mac/启动.command](scripts/mac/启动.command) 的终端输出
- 受管 parser 日志：`.managed/douyin_tiktok_download_api/runtime/parser.log`

### Streamlit 启动失败

优先看：

- `.runtime/streamlit.log`

## License

Private / Internal Use Only
