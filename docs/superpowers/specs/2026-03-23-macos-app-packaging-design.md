# macOS App 打包设计

## 目标

- 仅支持 macOS 分发。
- 交付物为 `zip`，不做 `dmg`。
- 运营同事解压后双击 `video2prompt.app` 即可启动。
- 第一阶段不做签名、公证、自动升级。
- 内置 `ffprobe`，保证“视频时长判断”模式可用。

## 约束

- 当前项目是本地 `Streamlit` 应用，真实业务入口为仓库根目录 `app.py`。
- 运行依赖 Python 3.11+、`.env`、`config.yaml`、模板文件与 `ffprobe`。
- 当前仓库中的 `config.yaml` 仍使用相对路径，如 `data/cache.db`、`logs/app.log`，不能直接原样用于打包态。
- 应用运行时会写入缓存、日志、导出文件和用户 Cookie，不适合写回 `.app` 包内。
- 第一阶段接受页面仍以系统默认浏览器打开，不追求原生桌面壳 UI。

## 方案选择

采用 `PyInstaller + macOS .app + zip`。

原因：

- 现有入口与依赖结构适合 `PyInstaller`。
- 相比 `py2app`，对 `Streamlit` 这类动态导入项目更容易通过 hidden imports 和 data files 处理。
- 用户体验满足“像 app 一样双击启动”，同时保留现有业务逻辑。
- 只做单平台时，`PyInstaller` 的维护成本最低。

## 运行形态

- `video2prompt.app` 内置 Python 运行时、项目代码、`streamlit`、模板资源和 `ffprobe`。
- 双击 `.app` 后，桌面入口脚本负责准备用户目录、设置环境变量，并在冻结环境内直接调用 `streamlit.web.bootstrap.run()` 启动 `app.py`。
- 不依赖外部 `python` 或外部 `streamlit` 命令，避免冻结态中子进程找不到解释器或包。
- 启动后自动打开系统默认浏览器到本地地址。

## 端口与重复启动策略

- 第一阶段固定使用单一本地端口，例如 `8501`。
- 桌面入口启动前先检查该端口是否已被当前应用实例占用：
  - 若已存在本应用实例，则不再重复拉起服务，只把浏览器打开到现有地址。
  - 若端口被其他进程占用，则给出明确错误提示，提示用户关闭冲突进程或改端口后重试。
- 第一阶段不做多实例并行，也不做自动端口漂移，避免给运营同事带来“打开多个地址”的困惑。

## 资源目录与用户目录

区分“只读资源目录”和“用户可写数据目录”：

- 资源目录：打包进 `.app`
  - `app.py`
  - `config.yaml`
  - `.env.example`
  - `docs/视频复刻提示词.md`
  - `docs/视频内容审查.md`
  - `docs/product_prompt_template.xlsx`
  - `bin/ffprobe`
- 用户数据目录：`~/Library/Application Support/video2prompt/`
  - `config.yaml`
  - `.env`
  - `data/cache.db`
  - `exports/`
  - `logs/app.log`
  - `user_state.yaml`

首次启动时，将默认配置从资源目录复制到用户数据目录；若缺少 `.env`，则基于 `.env.example` 生成。后续升级 `.app` 不覆盖用户数据。

## 冻结态资源定位

不能继续假设普通源码目录结构。运行时路径必须统一由 `RuntimePaths` 解析：

- 开发态：使用仓库根目录作为 `resource_root`
- PyInstaller 冻结态：
  - 通过 `getattr(sys, "frozen", False)` 判断
  - 通过 `Path(getattr(sys, "_MEIPASS"))` 获取 bundle 资源根目录
- 所有资源文件都从 `resource_root` 派生：
  - `app.py`
  - `docs/*.md`
  - `docs/product_prompt_template.xlsx`
  - `config.yaml`
  - `.env.example`
  - `bin/ffprobe`

这样才能保证 `.app` 内部布局变化时，业务代码仍只依赖统一路径工厂，而不是散落的相对路径。

## 路径与配置传递策略

第一阶段的关键设计不是“把默认值改掉”，而是“统一运行时路径来源”并把它传给真实应用入口：

- 开发态继续允许使用仓库相对路径，方便本地开发与测试。
- 打包态通过 `RuntimePaths` 提供：
  - 资源目录
  - Application Support 根目录
  - 数据目录
  - 导出目录
  - 日志目录
  - 内置二进制目录
- 所有可写路径都必须在启动阶段或配置加载后被重写到用户目录。
- 即使 `config.yaml` 里仍写的是 `data/cache.db` / `logs/app.log`，打包态也不能把数据写回当前工作目录。

桌面入口必须导出运行时环境变量，例如：

- `VIDEO2PROMPT_RESOURCE_ROOT`
- `VIDEO2PROMPT_APP_SUPPORT_DIR`
- `VIDEO2PROMPT_ENV_PATH`
- `VIDEO2PROMPT_CONFIG_PATH`
- `VIDEO2PROMPT_FFPROBE_PATH`

`app.py` 启动时优先读取这些环境变量，并用其初始化 `ConfigManager`、模板路径和导出路径；若环境变量不存在，再回退到开发态默认行为。

其中 `app.py` 内所有直接写 `Path("exports")` 的导出分支，也必须统一改为使用运行时用户导出目录，不能遗漏普通 Excel、时长模式 Excel、按类目 Excel/Markdown 这几条链路。

## 首次启动与 API Key 策略

第一阶段不能承诺“解压后立即完整可用”，因为当前 AI 模式启动依赖 `VOLCENGINE_API_KEY` 或 `ARK_API_KEY`。因此首启策略改为：

- 用户解压后可以启动 app
- 首次启动时，若用户目录缺少 `.env`，自动根据 `.env.example` 生成
- 若未配置 API Key：
  - app 仍可打开页面
  - UI 中明确提示需要填写 `.env` 后重启，AI 模式才能运行
  - “视频时长判断”模式应允许继续使用

为实现这个体验，需要把 API Key 校验从“应用初始化时强制校验”收敛为“仅在需要模型调用时校验”。

## 首次启动流程

桌面入口在首次启动时做以下事情：

1. 解析当前运行模式的 `RuntimePaths`
2. 创建 `~/Library/Application Support/video2prompt/` 及其子目录
3. 若用户目录下缺少 `config.yaml`，从资源目录复制默认版本
4. 若用户目录下缺少 `.env`，根据 `.env.example` 生成 `.env`
5. 保留用户已修改的 `.env` / `config.yaml`，二次启动不覆盖
6. 将内置 `bin/ffprobe` 加入 `PATH`
7. 导出 `VIDEO2PROMPT_*` 环境变量
8. 在冻结环境内直接调用 `streamlit.web.bootstrap.run(app.py, ...)`
9. 自动打开浏览器访问本地地址

## ffprobe 策略

- 第一阶段直接内置 `ffprobe`，避免运营自行安装 ffmpeg。
- 运行时优先使用显式内置路径；若不存在，再回退到系统 `PATH`。
- 第一阶段只支持单一构建架构，建议与构建机保持一致；若在 Apple Silicon 上构建，则先以 `arm64` 为准。
- `packaging/bin/ffprobe` 必须是可独立分发的实际二进制；若不是静态构建，则必须把依赖的 `.dylib` 一并打包并验证可加载。
- 构建前需校验存在、可执行、可输出版本信息，并检查依赖是否都能在目标机器上解析。

## 打包策略

`PyInstaller` 需要显式处理以下事项：

- `src` 布局：在 spec 中配置 `pathex=["src"]`
- 根入口文件：把仓库根目录 `app.py` 一并作为数据文件打包到 bundle 中，供桌面入口调用
- `Streamlit` hidden imports 与其运行所需资源
- 模板与文档资源打包进 `docs/`
- `config.yaml`、`.env.example` 打包到资源根目录
- `ffprobe` 作为 `binaries` 打包到 `bin/`

构建输出：

- `dist/video2prompt.app`
- `dist/video2prompt-macos.zip`

## 验证策略

至少覆盖三类验证：

- 单元测试
  - 路径解析
  - 冻结态资源根目录解析
  - 首次启动复制逻辑
  - 配置路径重写
  - API Key 缺失时的非崩溃行为
  - `ffprobe` 路径解析
  - Excel 模板运行时路径
- 构建验证
  - 能成功生成 `.app` 和 `zip`
  - `.app` 可启动桌面入口
  - bundle 内 `app.py`、`docs/*.md`、`docs/product_prompt_template.xlsx`、`config.yaml`、`.env.example` 可被真实读取
- 运行验证
  - 从任意工作目录启动时，缓存、日志、导出仍写入用户目录
  - Cookie 持久化正常
  - Excel / Markdown ZIP 导出正常
  - 时长判断模式可调用内置 `ffprobe`
  - 无 API Key 时可启动并看到配置提示

## 非目标

- 不做 `dmg`
- 不做 Apple Developer 签名和 notarization
- 不改造成原生桌面 UI
- 不做自动更新或增量升级
- 不做 Windows 兼容

## 未签名分发约束

- 第一阶段默认是未签名、未公证 app，不能承诺只会出现一次固定样式的系统提示。
- 分发说明必须明确写出首启放行方法：
  - 右键 `video2prompt.app` 选择“打开”
  - 或在“系统设置 -> 隐私与安全性”中允许打开
- 若压缩包带有隔离属性导致拦截更严格，需要在交付说明中补充这一现实限制，而不是把它描述成稳定的单次提示。

## 验收标准

- 干净 macOS 机器解压后无需安装 Python 即可启动。
- 无 API Key 时应用不会直接崩溃，且能提示如何补配。
- “视频时长判断”模式可在无 API Key 条件下运行。
- AI 模式在配置 API Key 后可正常运行。
- Excel 与 Markdown ZIP 可正常导出。
- 关闭后再次打开，Cookie、缓存和日志仍保留。
- 从非仓库目录启动时，不会把缓存、日志、导出写回当前目录。
- 用户能够按照分发说明完成未签名 app 的放行并成功启动。
