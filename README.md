# video2prompt

本项目用于批量解析抖音链接并调用模型服务进行视频理解（支持 Gemini / 火山方舟 Doubao），最终导出 Excel。

## 快速开始

1. 安装依赖：
   - `pip install -e .`
2. 准备配置：
   - 复制 `.env.example` 为 `.env`
   - 使用 Gemini 时填写 `GEMINI_API_KEY`
   - 使用火山方舟时填写 `VOLCENGINE_API_KEY`（或 `ARK_API_KEY`）
   - 在 `config.yaml` 里设置 `provider` 为 `gemini` 或 `volcengine`
   - 当 `provider=volcengine` 时，`volcengine.endpoint_id` 必填，且请求体 `model` 实际使用该 `endpoint_id`
   - `volcengine.target_model` 用于标注目标模型（如 `doubao-seed-1-8-251228`），不直接作为请求体 `model`
3. 启动：
   - `bash scripts/start.sh`
