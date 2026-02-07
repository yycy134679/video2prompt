# video2prompt

本项目用于批量解析抖音链接并调用 Gemini 进行视频理解，最终导出 Excel。

## 快速开始

1. 安装依赖：
   - `pip install -e .`
2. 准备配置：
   - 复制 `.env.example` 为 `.env`
   - 填写 `GEMINI_API_KEY`
3. 启动：
   - `bash scripts/start.sh`
