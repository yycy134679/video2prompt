# macOS App 打包一期 Implementation Plan

> 当前分支：`feature/macos-app-packaging`
>
> 目标交付：`dist/video2prompt.app`、`dist/video2prompt-macos.zip`

## 当前状态总览

- [x] 已建立运行时路径抽象，区分 bundle 资源目录与用户可写目录
- [x] 已实现桌面入口，负责准备 `.env` / `config.yaml` / `PATH` / `VIDEO2PROMPT_*`
- [x] 已把 API Key 校验后移到真正模型调用阶段
- [x] 已接通内置 `ffprobe` 路径解析与打包
- [x] 已落地 PyInstaller spec 与构建脚本，可生成 `.app` 与 `zip`
- [x] 已修复 `.app` 冻结态启动后误走 Streamlit dev server 的问题
- [x] 已验证 `.app` 首页可返回正式 Streamlit HTML，不再是 404/dev server 页面
- [x] 已修复 `.app` 真实 UI 启动时缺少 `httpx` 等 `app.py` 依赖的问题
- [x] 已实现固定端口占用策略：本应用复用、其他进程占用时报错
- [ ] 干净 macOS 机器分发验证仍未完成
- [ ] 提交拆分与 commit 仍未完成

## 任务进度

### Task 1: 冻结态启动链路

- [x] 桌面入口可在包内定位 `app.py`
- [x] 桌面入口通过 `streamlit.web.bootstrap.run()` 启动 bundle 内应用
- [x] 已固定端口为 `8501`
- [x] 已生成最小 `.app`
- [x] 已确认 `.app` 可实际启动
- [x] 端口冲突复用/报错策略已实现并验证

### Task 2: 运行时路径抽象

- [x] `src/video2prompt/runtime_paths.py`
- [x] `tests/test_runtime_paths.py`
- [x] 开发态 / 冻结态 / 用户目录派生测试通过

### Task 3: 配置路径重写

- [x] `src/video2prompt/config.py` 支持运行时路径覆盖
- [x] 相对 `data/`、`logs/` 路径重写到用户目录
- [x] `tests/test_config.py` 通过

### Task 4: `app.py` 消费运行时环境变量

- [x] `VIDEO2PROMPT_ENV_PATH`
- [x] `VIDEO2PROMPT_CONFIG_PATH`
- [x] `VIDEO2PROMPT_RESOURCE_ROOT`
- [x] `VIDEO2PROMPT_FFPROBE_PATH`
- [x] 导出目录统一落到运行时用户目录

### Task 5: API Key 延迟校验

- [x] 无 API Key 时应用初始化不阻断
- [x] 模型请求前再校验 API Key
- [x] “视频时长判断”模式在无 API Key 时仍可构造

### Task 6: 用户状态 / 日志 / 导出默认路径

- [x] `UserStateStore` 对齐统一用户目录
- [x] `ParserClient()` 默认实例跟随统一用户目录
- [x] 日志与 Markdown 导出路径已收敛

### Task 7: Excel 模板运行时路径

- [x] Excel 模板支持运行时资源目录
- [x] `tests/test_excel_exporter.py` 通过

### Task 8: 内置 `ffprobe`

- [x] `packaging/bin/ffprobe` 已接入
- [x] runner 支持显式 `ffprobe_path`
- [x] 构建后 bundle 内 `ffprobe` 依赖已改写为 `@rpath`
- [ ] 未在无 Homebrew 的干净机器上完成最终分发验证

### Task 9: 桌面入口完整化

- [x] 首启复制 `config.yaml`
- [x] 首启根据 `.env.example` 生成 `.env`
- [x] 二次启动不覆盖用户文件
- [x] 构造 `PATH` 让内置 `ffprobe` 可执行
- [x] 导出 `VIDEO2PROMPT_*` 环境变量
- [x] 启动前显式加载 Streamlit 配置，禁止冻结态误入 dev server
- [x] 端口占用策略已补齐

### Task 10: PyInstaller spec 与构建脚本

- [x] `packaging/video2prompt-macos.spec`
- [x] `scripts/build_macos_app.sh`
- [x] `README.md` 已补充未签名 app 放行说明
- [x] 可生成 `dist/video2prompt.app`
- [x] 可生成 `dist/video2prompt-macos.zip`
- [x] spec 已显式纳入 `app.py` 与 `video2prompt` 子模块依赖分析

### Task 11: 端到端验证

- [x] 相关回归测试已通过（最新一轮为 55 passed）
- [x] bundle 内关键资源存在：`app.py`、`config.yaml`、`.env.example`、`docs/product_prompt_template.xlsx`、`bin/ffprobe`
- [x] `.app` 启动后 `http://127.0.0.1:8501/` 返回正式 Streamlit 首页 HTML
- [x] 从非仓库目录 + 临时 HOME 启动时，`config.yaml` / `.env` 写入 `~/Library/Application Support/video2prompt/`，未写回当前目录
- [x] 当 `8501` 已被本应用占用时，第二次启动直接复用现有实例并返回 0
- [x] 当 `8501` 被其他进程占用时，`.app` 会明确报错退出
- [x] Cookie 持久化已验证：页面保存后写入 `user_state.yaml`，重启 `.app` 后状态仍显示已保存
- [x] 导出链路已做运行时 smoke：Excel / Markdown ZIP / 时长双文件可写入用户导出目录
- [x] AI 模式真实模型调用已验证：使用真实抖音链接完成 9/9 条模型解读成功

## 本轮新增修复

- [x] 根因确认：直接调用 `streamlit.web.bootstrap.run()` 时，没有走 CLI 的初始配置加载链路
- [x] 回归测试：`tests/test_desktop_entry.py` 已覆盖“启动前先加载 Streamlit 配置”
- [x] 修复实现：`src/video2prompt/desktop_entry.py` 先调用 `load_config_options(...)`，再启动 server
- [x] 实机 smoke：日志显示 `Local URL: http://localhost:8501`，不再出现 `localhost:3000` / `Node dev server`
- [x] 实机 smoke：端口复用与端口冲突行为已验证
- [x] 实机 UI 验证暴露并修复：`packaging/video2prompt-macos.spec` 现在显式分析 `app.py` 依赖，`.app` 不再报 `ModuleNotFoundError: httpx`

## 下一步

- [ ] 在干净机器验证未签名分发与内置 `ffprobe`
- [ ] 按主题拆分 commit
