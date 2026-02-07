# 需求文档

## 简介

video2prompt 是一个本地部署的批量视频解读工具，面向非技术同事使用。用户输入抖音视频链接与对应 pid，工具自动调用 Douyin_TikTok_Download_API 解析服务获取视频直链，再通过 Gemini 中转站（huandutech）API 以 fileUri 方式进行视频内容解读，最终批量导出 Excel 结果。工具内置保守风控策略（随机间隔、指数退避、熔断机制、分批运行），并使用 SQLite 本地缓存实现去重与结果复用。

## 术语表

- **Streamlit_App**：基于 Streamlit 框架的主程序界面，负责用户交互、任务编排、风控控制、结果展示与导出
- **Parser_Service**：Douyin_TikTok_Download_API 解析服务，独立运行的 HTTP 服务，提供 `/api/hybrid/video_data` 接口解析抖音视频链接
- **Gemini_Client**：调用 huandutech 中转站原生 Gemini 格式 API 的客户端模块，负责视频解读请求的构建与发送
- **Task_Scheduler**：任务编排与调度模块，管理任务队列、并发控制、风控节奏、状态流转
- **Circuit_Breaker**：熔断器模块，独立监控解析服务与 Gemini 服务的失败计数与失败率，触发熔断时停止任务
- **Cache_Store**：基于 SQLite 的本地缓存模块，存储链接解析结果与 Gemini 解读结果，支持去重与复用
- **Config_Manager**：配置管理模块，加载 .env 敏感配置与 config.yaml 业务配置，支持运行时覆盖
- **pid**：产品标识符，用户提供的与视频链接一一对应的业务标识
- **aweme_id**：抖音视频的唯一标识，从解析结果中提取
- **fileUri**：视频 CDN 直链地址，作为 Gemini API 的 fileData.fileUri 参数传入
- **退避序列**：请求失败后逐步增加等待时间的策略，每次失败后等待时间按预设序列递增
- **熔断**：当连续失败次数或失败率超过阈值时，自动停止所有任务以防止进一步风控触发

## 需求

### 需求 1：批量输入与校验

**用户故事：** 作为非技术同事，我希望能批量粘贴 pid 和视频链接，以便一次性提交多条视频解读任务。

#### 验收标准

1. THE Streamlit_App SHALL 提供两个多行文本输入框，分别用于输入 pid 列表和视频链接列表，按行对齐（第 N 行 pid 对应第 N 行链接）
2. WHEN 用户提交输入时，THE Streamlit_App SHALL 校验两个输入框的非空行数是否一致，不一致时显示明确的行数差异提示
3. WHEN 两个输入框中同一行均为空时，THE Streamlit_App SHALL 自动忽略该行，不生成对应任务
4. WHEN 视频链接不包含 "douyin" 或 "iesdouyin" 域名时，THE Streamlit_App SHALL 标记该行为无效链接并显示提示，同时允许其余有效行继续处理
5. THE Streamlit_App SHALL 允许 pid 为空但保留行占位，对应任务的 pid 字段记录为空值


### 需求 2：视频直链解析

**用户故事：** 作为非技术同事，我希望工具能自动从抖音链接解析出可用的视频直链，以便后续 Gemini 解读使用。

#### 验收标准

1. WHEN 处理一条任务时，THE Task_Scheduler SHALL 调用 Parser_Service 的 `GET /api/hybrid/video_data?url={链接}` 接口获取解析结果
2. THE Parser_Service 客户端 SHALL 按以下策略提取无水印视频直链：从 `data.video.bit_rate` 数组中筛选仅 H264 编码（`is_h265 == 0`）且分辨率不超过 1080p 的条目，按 `bit_rate` 字段降序排序，取码率最高的条目的 `play_addr.url_list[0]` 作为视频直链；若 `bit_rate` 数组为空或无符合条件的条目，则回退到 `data.video.play_addr_h264.url_list[0]`，再回退到 `data.video.play_addr.url_list[0]`；禁止使用 `download_addr`（该字段包含水印）
3. WHEN 解析请求返回 429、403、5xx 状态码或解析结果为空时，THE Task_Scheduler SHALL 按退避序列（10s、30s、120s、300s，最大不超过 10 分钟）等待后重试
4. WHEN 解析请求前，THE Task_Scheduler SHALL 随机等待 1.5 到 4 秒（可配置），用于降低风控风险
5. THE Task_Scheduler SHALL 将解析并发数限制在 1-5 之间（默认 3，可配置）
6. WHILE 任一服务（解析或 Gemini）处于退避等待期间，THE Task_Scheduler SHALL 全局暂停新任务出队，避免其他任务继续请求同一服务

### 需求 3：Gemini 视频解读

**用户故事：** 作为非技术同事，我希望工具能调用 Gemini API 对视频进行内容解读，以便获取结构化的视频分析结果。

#### 验收标准

1. WHEN 获取到视频直链后，THE Gemini_Client SHALL 立即调用 huandutech 中转站的 `{gemini.base_url}/v1beta/models/{gemini.model}:generateContent` 接口，使用 `fileData.fileUri` 传入视频直链，认证方式为 `Authorization: Bearer {GEMINI_API_KEY}`
2. THE Gemini_Client SHALL 在请求体中包含可自定义的 DEFAULT_USER_PROMPT（作为用户提示词），并且 SHALL NOT 发送 `systemInstruction` 字段
3. WHEN Gemini 请求返回 429、5xx 状态码时，THE Task_Scheduler SHALL 按退避序列（5s、15s、60s、180s，最大不超过 5 分钟）等待后重试
4. WHEN Gemini 返回错误且错误信息指向拉取视频资源失败时，THE Task_Scheduler SHALL 先重新调用 Parser_Service 获取新直链，再重试 Gemini 请求
5. WHEN 重新解析后 Gemini 仍然失败时，THE Task_Scheduler SHALL 标记该任务为失败状态并记录错误原因
6. THE Gemini_Client SHALL 不在请求前添加随机间隔，获取直链后立即发起解读请求


### 需求 4：Prompt 管理

**用户故事：** 作为非技术同事，我希望能自定义 Gemini 的 DEFAULT_USER_PROMPT，以便根据需要调整解读指令。

#### 验收标准

1. THE Streamlit_App SHALL 提供可编辑的 DEFAULT_USER_PROMPT 文本输入框，同事可自定义用户提示词内容
2. WHEN 用户修改 DEFAULT_USER_PROMPT 后，THE Streamlit_App SHALL 将内容持久化到本机 SQLite 数据库，打开页面时自动加载上次保存的内容
3. THE Gemini_Client SHALL 优先使用用户在页面中配置的 DEFAULT_USER_PROMPT；当其为空时回退到代码默认值："按要求解析视频并输出 sora 提示词"
4. WHEN 执行 Gemini 解读时，THE Gemini_Client SHALL 将 DEFAULT_USER_PROMPT 作为 `contents.parts[].text` 发送，并且 SHALL NOT 发送 `systemInstruction`

### 需求 5：任务状态机与实时展示

**用户故事：** 作为非技术同事，我希望能实时看到每条任务的处理状态和进度，以便了解批量任务的整体执行情况。

#### 验收标准

1. THE Task_Scheduler SHALL 为每条任务维护以下状态之一：等待中、解析中、等待间隔、Gemini解读中、完成、失败、熔断停止
2. WHEN 任务状态发生变化时，THE Streamlit_App SHALL 实时更新任务表中对应行的状态显示
3. THE Streamlit_App SHALL 在任务表中展示每条任务的以下信息：pid、原始链接、aweme_id、当前阶段、重试次数、耗时、错误原因、Gemini 输出预览
4. WHEN 每条任务完成后，THE Task_Scheduler SHALL 额外随机等待 0.8 到 2 秒再处理下一条任务，避免节奏过于固定

### 需求 6：熔断机制

**用户故事：** 作为非技术同事，我希望工具在检测到异常时能自动停止任务并给出可读提示，以便我采取正确的应对措施。

#### 验收标准

1. THE Circuit_Breaker SHALL 为解析服务和 Gemini 服务分别独立计数失败次数与失败率
2. WHEN 解析服务连续失败达到 8 次（可配置）或近 5 分钟失败率超过 60%（可配置）时，THE Circuit_Breaker SHALL 触发解析服务熔断
3. WHEN Gemini 服务连续失败达到 5 次（可配置）或近 5 分钟失败率超过 50%（可配置）时，THE Circuit_Breaker SHALL 触发 Gemini 服务熔断
4. WHEN 任一服务熔断触发时，THE Task_Scheduler SHALL 停止整批任务，THE Streamlit_App SHALL 显示对应的建议操作提示（解析侧提示检查解析服务状态或降低并发，Gemini 侧提示检查 API Key 或服务状态）
5. WHEN 熔断触发后，THE Streamlit_App SHALL 提供"继续"按钮，点击后从未完成的任务继续执行

### 需求 7：分批运行

**用户故事：** 作为非技术同事，我希望大批量任务能自动分批执行并在批次间休息，以便降低风控风险。

#### 验收标准

1. THE Task_Scheduler SHALL 将任务按批次大小（默认 100，可配置 50-200）分批执行
2. WHEN 一个批次执行完毕后，THE Task_Scheduler SHALL 随机等待 5 到 15 分钟（可配置）再开始下一批
3. WHILE 批次间休息期间，THE Streamlit_App SHALL 显示倒计时并提供"跳过休息"按钮，点击后立即开始下一批
4. WHILE 批次间休息期间，THE Streamlit_App SHALL 提供"取消任务"按钮，点击后终止后续批次，已完成的结果保留可导出

### 需求 8：本地缓存与去重

**用户故事：** 作为非技术同事，我希望重复的视频链接能自动复用之前的结果，以便节省时间和 API 调用次数。

#### 验收标准

1. THE Cache_Store SHALL 使用 SQLite 存储链接哈希到 aweme_id、选链结果和 Gemini 解读输出的映射
2. WHEN 同一链接重复出现时，THE Cache_Store SHALL 默认复用已缓存的解析结果和 Gemini 解读结果
3. WHEN 缓存命中时，THE Task_Scheduler SHALL 跳过对应的解析和 Gemini 调用步骤，直接使用缓存结果

### 需求 9：Excel 导出

**用户故事：** 作为非技术同事，我希望能将所有任务结果导出为 Excel 文件，以便交付给上下游使用。

#### 验收标准

1. WHEN 用户点击导出按钮时，THE Streamlit_App SHALL 按照 `docs/product_prompt_template.xlsx` 模板定义的列结构和格式生成 Excel 文件
2. THE Streamlit_App SHALL 将导出的 Excel 文件命名为 `video2prompt-{时间戳}.xlsx`，时间戳格式为 `YYYYMMDDHHmmss`
3. THE Streamlit_App SHALL 确保导出的 Excel 文件不包含 Cookie、API Key 等任何敏感凭据
4. WHEN 部分任务已完成而其余任务被取消或失败时，THE Streamlit_App SHALL 仍允许导出已完成任务的结果

### 需求 10：配置管理

**用户故事：** 作为维护者，我希望敏感配置与业务配置分离管理，以便安全地维护和调整工具参数。

#### 验收标准

1. THE Config_Manager SHALL 从 .env 文件加载敏感配置（GEMINI_API_KEY），从 config.yaml 文件加载业务配置（并发数、批次大小、退避参数、中转站地址、模型名称等）
2. THE Streamlit_App SHALL 在页面上提供运行时配置项（并发数、批次大小等），运行时值覆盖 config.yaml 默认值但不回写文件
3. IF .env 文件缺少必需的 GEMINI_API_KEY 配置，THEN THE Config_Manager SHALL 在启动时显示明确的配置缺失提示

### 需求 11：部署与启动

**用户故事：** 作为非技术同事，我希望能简单启动工具并确认依赖服务可用，以便快速开始使用。

#### 验收标准

1. THE 启动脚本 SHALL 启动 Streamlit_App 并自动打开浏览器页面
2. WHEN Streamlit_App 启动时，THE Streamlit_App SHALL 检测 Parser_Service 的连通性（按 config.yaml 中配置的 parser.base_url），连通失败时在页面显示明确提示（如"解析服务未启动，请先启动 Douyin_TikTok_Download_API"）
3. WHEN 启动时检测到依赖未安装，THE 启动脚本 SHALL 显示依赖安装提示
4. THE Streamlit_App SHALL 仅通过 HTTP 接口调用 Parser_Service，不直接 import 其源码

### 需求 12：错误处理与日志

**用户故事：** 作为维护者，我希望错误提示对非技术用户可读，同时技术细节写入日志文件，以便分别满足使用者和排查者的需求。

#### 验收标准

1. WHEN 任务执行过程中发生错误时，THE Streamlit_App SHALL 在界面上显示面向非技术用户的可读错误提示
2. WHEN 任务执行过程中发生错误时，THE Streamlit_App SHALL 将完整的技术错误详情（堆栈信息、请求参数、响应内容）写入日志文件
3. THE Streamlit_App SHALL 确保 API Key 不出现在日志正文、控制台输出或导出文件中

### 需求 13：安全性

**用户故事：** 作为维护者，我希望敏感凭据得到妥善保护，以便防止信息泄露。

#### 验收标准

1. THE Streamlit_App SHALL 确保 API Key 不写入导出的 Excel 文件
2. THE Streamlit_App SHALL 确保 API Key 不打印到控制台日志正文
3. THE Config_Manager SHALL 确保 .env 文件已加入 .gitignore，防止敏感配置被提交到版本库
