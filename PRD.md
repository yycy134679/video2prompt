PRD: 抖音视频批量解析与 Gemini 视频理解生成 11s Sora Prompt 工具

> 相关文档：[Gemini 视频理解官方文档](docs/gemini%20视频理解官方文档.md)

1. 背景与问题
   你现在用本地服务已经能通过接口拿到抖音视频的结构化数据与可播放地址，接下来要让非技术同事也能批量输入商品 pid 和抖音视频链接，自动调用 Gemini 做视频理解，输出每条 pid 对应的 11s Sora prompt，并导出 Excel。
   系统需要在不做下载带宽限速的前提下，尽量减少重复请求与失败重试造成的压力，同时面对网络抖动、第三方限制、Gemini 配额等情况也要稳定可控。
   
   **API 接入方案**：使用 Google Cloud Vertex AI 调用 Gemini 模型，支持完整的 File API 上传大视频文件（>1分钟），适合批量处理长视频场景。

2. 目标与成功指标
   目标
   A. 非技术同事可在 Web 页面粘贴两列数据并一键运行。
   B. 支持自定义 Gemini 分析提示词，默认提供一条可用模板。
   C. 批量生成并导出 Excel，至少包含 pid 和 sora_prompt 两列。
   D. 稳定性策略内置，避免重复请求，失败可重试，可暂停与继续。

成功指标
A. 100 条任务批量运行的成功率与可恢复性可接受，失败条目能明确报错原因并可重试。
B. 对同一视频与同一提示词重复运行时，命中缓存并跳过 Gemini 费用与请求。
C. 全流程对用户可见进度，包括排队数、成功数、失败数、重试次数。

3. 用户与使用场景
   目标用户
   A. 运营与内容同事，懂复制粘贴，不关心接口细节。
   B. 你作为维护者，需要能排查失败原因，导出日志摘要。

核心场景
A. 从表格复制 pid 列与抖音链接列，粘贴进页面两块输入框，每行一条。
B. 编辑 Gemini 提示词，点击开始生成。
C. 等待进度完成，下载 Excel。
D. 针对失败条目点击重试，或把失败条目导出单独重跑。

4. 范围与非目标
   范围内
   A. Web 界面录入与导入校验。
   B. 调用现有解析服务获取视频信息与可用视频地址。
   C. 下载视频或把可访问的视频 URL 交给 Gemini 处理。
   D. Gemini 视频理解生成结构化结果，再转换成 11s Sora prompt。
   E. Excel 导出与任务记录。
   F. 并发、批次、重试退避、熔断、本地缓存与去重。

非目标
A. 不做下载带宽限速与限速器配置界面。
B. 不做账号体系与复杂权限管理，先按内网或本机单用户版本设计。
C. 不提供绕过平台安全机制的能力，系统只做礼貌访问与降载，重点放在减少重复与稳健重试。

5. 关键产品交互与流程
   页面布局
   A. 输入区
6. pid 输入框，多行文本，每行一个 pid
7. 抖音视频链接输入框，多行文本，每行一个链接
8. Gemini 提示词输入框，多行文本，可编辑，带默认模板
   B. 控制区
9. 运行按钮
10. 暂停按钮
11. 继续按钮
12. 仅重试失败按钮
    C. 状态区
13. 总数、排队中、处理中、成功、失败、已缓存跳过
14. 失败列表，显示 pid、链接、错误原因、重试次数
    D. 导出区
15. 下载 Excel
16. 下载失败条目清单

导入校验规则
A. pid 行数必须等于链接行数，空行自动忽略。
B. pid 去空格，链接做基础合法性校验。
C. 重复 pid 允许存在，但会作为独立任务处理，后续可用缓存降低 Gemini 请求。

任务处理流程
A. 解析阶段

1. 对每条链接调用本地解析接口，拿到视频 id、可播放地址等信息

2. 若解析失败，进入重试队列
   B. 视频输入准备阶段

3. 统一使用 Vertex AI File API 上传视频
   由于视频可能超过 1 分钟，统一采用 File API 上传方式，确保大文件稳定处理。File API 支持单文件最大 2GB，上传后文件保留 48 小时，可被多次引用。

4. 视频处理流程
   - 下载抖音视频到本地临时目录
   - 通过 Vertex AI File API 上传到 Google Cloud
   - 获取 file_uri 用于后续 Gemini 调用
   - 同一视频可复用已上传的 file_uri（通过本地缓存 video_id -> file_uri 映射）
   
   **Vertex AI 视频上传说明**：
   - 支持格式：video/mp4、video/mpeg、video/mov、video/avi、video/webm 等
   - 单文件限制：最大 2GB
   - 文件有效期：48 小时，过期需重新上传
   - 上传后返回 file_uri，格式如 `https://generativelanguage.googleapis.com/v1beta/files/{file_id}`
   
   C. Gemini 分析阶段

5. 把上传后的视频 file_uri 作为输入，带上用户自定义提示词，要求输出 11s Sora prompt

6. 将 Gemini 输出与 pid 绑定写入结果表
   Gemini 的视频理解会对视频进行抽帧与音频采样，视频按每秒约 1 帧抽样，音频也按秒级间隔处理，适合做结构分析与脚本提取。
   
   **Vertex AI Python SDK 示例**：
   ```python
   import vertexai
   from vertexai.generative_models import GenerativeModel, Part
   
   # 初始化 Vertex AI
   vertexai.init(project="your-project-id", location="us-central1")
   
   # 上传视频文件
   video_file = genai.upload_file(path="local_video.mp4")
   
   # 调用 Gemini 分析视频
   model = GenerativeModel("gemini-2.5-flash")
   response = model.generate_content([
       Part.from_uri(video_file.uri, mime_type="video/mp4"),
       "你是抖音爆款视频结构专家，请分析该视频并输出一个 11s 的 sora 提示词"
   ])
   print(response.text)
   ```
   
   **REST API 示例**：
   ```bash
   # 1. 上传视频
   curl -X POST "https://generativelanguage.googleapis.com/upload/v1beta/files" \
     -H "Authorization: Bearer $(gcloud auth print-access-token)" \
     -H "X-Goog-Upload-Protocol: resumable" \
     -F "file=@video.mp4"
   
   # 2. 调用 generateContent
   curl -X POST "https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}/publishers/google/models/gemini-2.5-flash:generateContent" \
     -H "Authorization: Bearer $(gcloud auth print-access-token)" \
     -H "Content-Type: application/json" \
     -d '{
       "contents": [{
         "parts": [
           {"file_data": {"file_uri": "files/{FILE_ID}", "mime_type": "video/mp4"}},
           {"text": "分析视频并输出 11s sora 提示词"}
         ]
       }]
     }'
   ```
   
   D. 导出阶段
   生成 Excel，至少两列 pid 与 sora_prompt，同时建议附加 status 与 error 便于排查。

7. Gemini 提示词能力设计
   默认提示词模板
   你是抖音爆款视频结构专家，请分析该视频并输出一个 11s 的 sora 提示词

增强建议
A. 支持变量占位符，例如 {pid} {url}，在发给 Gemini 前做字符串替换。
B. 支持输出约束，例如只输出英文提示词或固定字段结构，减少后处理难度。
C. 对超长视频可在提示词里要求先总结结构再给 11s 脚本，降低跑偏概率。

7. 稳定性与吞吐策略
   你要求写入文档的策略我这里全部落成可实现的规则。

并发 3
A. 全局任务并发上限固定为 3，适用于解析请求、视频准备、Gemini 调用三类网络动作。
B. 并发控制在任务队列层实现，确保任何时候最多 3 条处于网络请求状态。

随机间隔
A. 在每次发起对外网络请求前加入抖动时间 jitter。
B. jitter 只用于打散并发尖峰与避免同一时刻集中请求，不用于规避安全机制。

指数退避
A. 对可重试错误执行指数退避重试，例如网络超时、临时 5xx、429 配额或繁忙等。
B. 退避公式建议 base 1s，指数增长到上限 60s，并叠加随机抖动。
C. 每条任务最大重试次数默认 5 次，超过后标记失败。

熔断
A. 以域名维度维护熔断器，至少分 Vertex AI（Gemini）与抖音解析两类。
B. 在短时间内连续失败达到阈值，例如 10 次，进入 open 状态，暂停对该域名的新请求一段时间，例如 2 分钟。
C. 进入 half open 后放行少量探测请求，成功则恢复，失败则继续熔断。

减少重复请求
A. 本地缓存分两层

1. 解析缓存 key: 规范化后的 douyin_url 或 aweme_id
2. 文件上传缓存 key: video_id -> file_uri（48小时有效期内可复用）
3. Gemini 结果缓存 key: 视频唯一标识加提示词 hash 加模型版本
   B. 命中缓存直接写结果并标记 cached_skip，不再请求 Gemini。
   C. 缓存持久化建议用 SQLite，方便单机部署与查询。
   D. 文件上传缓存需记录上传时间，超过 48 小时自动失效重传。

批次运行
A. 大批量导入后按 batch_size 切分，例如每批 50 条。
B. 批次内按并发 3 跑完后再进入下一批。
C. 支持暂停与继续，本质是停止派发新任务，保留队列状态。
D. 这样可以让 UI 体验更稳，内存占用可控，也便于中途导出阶段性结果。

8. 输出与 Excel 规范
   必选列
   A. pid
   B. sora_prompt

建议附加列
A. douyin_url
B. status，success failed cached_skip
C. error_message
D. retries_count
E. video_id 或 aweme_id

导出行为
A. 任务进行中允许导出当前已完成部分，便于先用先走。
B. 导出时按输入顺序排序，便于同事对照。

9. 系统架构设计
   总体原则
   最简单可用，优先复用你当前的本地解析服务与 FastAPI 服务形态。

组件
A. Web UI
单页表单加任务状态轮询即可，避免引入复杂前端框架也能满足非技术同事使用。
B. Orchestrator 任务编排器
负责导入校验、切批、并发控制、重试退避、熔断、缓存命中判断、进度统计。
C. Parser Adapter
封装调用现有本地解析接口，输出统一的 VideoMeta。
D. Video Input Adapter
实现视频下载与 Vertex AI File API 上传，管理 file_uri 缓存与过期重传。
E. Gemini Analyzer
封装调用 Vertex AI Gemini 模型做视频分析与脚本输出。

**Vertex AI 配置项**：
- `GOOGLE_CLOUD_PROJECT`：Google Cloud 项目 ID
- `GOOGLE_CLOUD_LOCATION`：区域，默认 `us-central1`
- `GOOGLE_APPLICATION_CREDENTIALS`：服务账号密钥文件路径（或使用 ADC 默认凭证）
- `GEMINI_MODEL`：默认 `gemini-2.5-flash`，可选 `gemini-2.5-pro`、`gemini-2.0-flash` 等

**环境要求**：
- 需要能访问 Google Cloud API（本机代理或部署在海外/香港服务器）
- 安装 `google-cloud-aiplatform` Python SDK
- 配置服务账号并授予 `Vertex AI User` 角色

F. Result Store
SQLite 保存 job、task、cache、result，支持断点续跑与导出。

10. 数据结构建议
    Job
    job_id, created_at, status, total, success, failed, cached_skip, prompt_template, model_name

Task
task_id, job_id, pid, douyin_url, normalized_url, video_id, status, retries, last_error, result_sora_prompt, cache_hit

Cache
parse_cache: normalized_url, video_meta_json, updated_at
file_upload_cache: video_id, file_uri, uploaded_at, expires_at
gemini_cache: video_fingerprint, prompt_hash, model_name, sora_prompt, updated_at

11. 接口建议
    为了实现简单，接口可以只提供三类
    A. POST /jobs
    body: pid_lines, url_lines, prompt_template, model_name
    return: job_id
    B. GET /jobs/{job_id}
    return: job 状态与 task 列表分页
    C. GET /jobs/{job_id}/export
    return: xlsx 文件流

12. 风险与合规
    A. 对外部平台的访问有不确定性，系统策略放在减少重复与稳健重试，避免无意义的高频请求。
    B. 视频内容与导出结果可能包含敏感信息，默认只存本机，日志中避免落地 Google Cloud 凭证与完整 Cookie。
    C. Gemini 对上传内容会进行安全检查与政策约束，可能触发内容安全过滤与返回相应结果。
    D. Vertex AI 按用量计费，需关注视频处理的 token 消耗（约 300 tokens/秒视频），建议设置预算告警。
    E. 上传到 Google Cloud 的视频文件 48 小时后自动删除，无需手动清理。

13. 验收标准
    A. 输入两列各 10 行，能正常跑完并导出 Excel，pid 与 sora_prompt 不为空。
    B. 并发始终不超过 3，可通过日志或监控指标验证。
    C. 人为制造网络失败时，能看到指数退避重试次数变化，最终失败可导出失败清单。
    D. 同一批数据重复跑，至少 50% 以上命中缓存并显示 cached_skip。
    E. 暂停后不再派发新任务，继续后能从队列恢复。

14. 里程碑建议
    M1 最小可用版本
    Web 表单导入校验，串行跑通解析加 Gemini，加 Excel 导出。
    M2 稳定性版本
    并发 3，批次运行，指数退避与熔断，缓存去重，失败清单与仅重试失败。
    M3 体验优化
    进度更细，任务分页，结果预览，模型与提示词版本管理。

我有几条澄清问题，回答任意几条就能把 PRD 里的实现细节定死到接口与数据结构层面。

1. ~~你计划用 Gemini API Key 走 Google AI Studio 体系，还是走 Vertex AI 体系~~ **已确定：Vertex AI**
2. 结果的 Sora prompt 需要强制英文输出吗，还是中英文都可
3. ~~你更偏向视频输入走本地下载再上传，还是优先尝试把解析到的公开视频 URL 直接交给 Gemini~~ **已确定：下载后通过 File API 上传**
4. 运行环境是你本机单人使用居多，还是需要局域网同事也能访问同一个服务
5. Excel 里除了 pid 与 sora_prompt，你希望默认再加哪两列方便你后续批量处理