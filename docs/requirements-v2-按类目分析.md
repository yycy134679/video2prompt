# 需求文档 v2：按类目分析视频脚本

## 背景

团队负责短视频电商内容运营，需要批量分析抖音上不同类目的爆款带货视频，拆解其视频脚本，从中寻找各类目的拍摄方法与技巧。

当前系统（v1）已实现「批量输入抖音视频链接 → AI 解读 → 导出视频脚本」的完整流程。但在实际工作中，同一批任务往往涵盖多个商品类目，分析完成后需要人工按类目手动整理脚本，再将同类目的脚本喂给下游 AI 做拍摄技巧总结，流程繁琐且低效。

本次迭代的目标是：**在保留 v1 全部功能的前提下，新增「按类目分析」模式**，让用户在输入时标注类目，导出时自动按类目聚合生成独立的 Markdown 文件，可直接作为下游 AI 的输入。

## 术语表（增量）

- **AppMode**：运行模式枚举，区分「视频复刻提示词」（v1 默认模式）与「按类目分析」（v2 新模式）
- **类目（category）**：商品的一级分类名称，如「服饰」「美妆」「3C 数码」等，由用户在输入时手动指定
- **Markdown 导出**：按类目将同类视频脚本聚合到一个 `.md` 文件中，供下游 AI 消费

## 核心原则

1. **向后兼容**：v1 模式的输入、处理、输出逻辑完全不变，`category` 字段默认为空
2. **管线复用**：视频解析 → 模型分析 → 缓存/熔断 等核心管线零改动，后续任何优化自动惠及两种模式
3. **最小变更**：仅在输入层和输出层做策略切换，不修改中间环节
4. **能力边界一致**：按类目分析模式沿用 v1 的解析能力边界，即仅支持抖音视频，依赖已保存的抖音 Cookie

## 需求

### 需求 14：运行模式切换

**用户故事：** 作为运营同事，我希望在界面上切换「视频复刻提示词」和「按类目分析」两种运行模式，以便在不同业务场景下使用同一工具。

#### 验收标准

1. THE Streamlit_App SHALL 在页面顶部（标题下方）提供「运行模式」下拉选择器，选项包括：「视频复刻提示词」（默认）和「按类目分析」
2. WHEN 用户切换运行模式时，THE Streamlit_App SHALL 动态调整输入区域的列数和导出区域的按钮选项，无需刷新页面
3. WHEN 选择「视频复刻提示词」模式时，THE Streamlit_App SHALL 展示与 v1 完全一致的界面和行为
4. THE Streamlit_App SHALL 在 session_state 中记住用户选择的模式，同一会话内切换页面不丢失

### 需求 15：类目输入（按类目分析模式）

**用户故事：** 作为运营同事，我希望在输入视频链接时能同时标注每条视频所属的商品类目，以便系统在导出时自动分类。

#### 验收标准

1. WHEN 运行模式为「按类目分析」时，THE Streamlit_App SHALL 显示三列输入框：pid 列表、视频链接列表、类目列表，按行对齐（第 N 行 pid 对应第 N 行链接和第 N 行类目）
2. THE Streamlit_App SHALL 校验三个输入框的非空行数是否一致，不一致时显示明确的行数差异提示
3. WHEN 类目列表中某行为空时，THE Streamlit_App SHALL 将该任务的类目标记为「未分类」
4. THE Streamlit_App SHALL 不限制类目名称的格式或取值范围，用户可自由输入任意文本作为类目名
5. WHEN 三个输入框中同一行均为空时，THE Streamlit_App SHALL 自动忽略该行，不生成对应任务

### 需求 16：类目数据透传

**用户故事：** 作为系统维护者，我希望类目信息能在整个处理管线中透传而不影响核心处理逻辑。

#### 验收标准

1. THE TaskInput 数据模型 SHALL 新增可选字段 `category`（类型 `str`，默认值 `""`），用于存储用户输入的类目名称
2. THE Task 数据模型 SHALL 新增可选字段 `category`（类型 `str`，默认值 `""`），从 TaskInput 透传
3. WHEN 构造 Task 对象时，THE Streamlit_App SHALL 将 TaskInput.category 赋值给 Task.category
4. THE Task_Scheduler、Model_Client、Parser_Client、Cache_Store、Circuit_Breaker 等核心模块 SHALL NOT 依赖或修改 `category` 字段，保证零侵入
5. WHEN 运行模式为「视频复刻提示词」时，所有 Task 的 `category` 字段 SHALL 为空字符串

### 需求 17：Markdown 按类目导出

**用户故事：** 作为运营同事，我希望完成分析后能一键导出按类目分组的 Markdown 文件，以便直接将每个类目的视频脚本合集喂给下游 AI 做拍摄技巧分析。

#### 验收标准

1. WHEN 运行模式为「按类目分析」且任务执行完成后，THE Streamlit_App SHALL 在导出区域显示「导出 Markdown（按类目）」按钮
2. WHEN 用户点击该导出按钮时，THE MarkdownExporter SHALL 按 `task.category` 字段对所有已完成任务进行分组
3. THE MarkdownExporter SHALL 为每个类目生成一个独立的 `.md` 文件，文件名格式为 `{类目名}.md`
4. THE MarkdownExporter SHALL 将同一批次的所有类目 md 文件存放在 `exports/{时间戳}/` 目录下，时间戳格式为 `YYYY-MM-DD_HHmmss`
5. 每个 md 文件的内容结构 SHALL 如下：
   - 一级标题为类目名称
   - 每个视频脚本以二级标题分隔，标题文本为「视频 {序号}」（序号从 1 开始）
   - 标题下方为该视频的模型输出内容（`gemini_output`），原样保留，不做任何格式化处理
   - 各视频之间以水平分割线（`---`）分隔
6. THE MarkdownExporter SHALL 仅导出状态为「完成」的任务，跳过失败或取消的任务
7. WHEN 类目名称包含文件系统非法字符时，THE MarkdownExporter SHALL 将其替换为下划线 `_`
8. WHEN 导出完成后，THE Streamlit_App SHALL 提供打包下载功能（zip），将整个类目目录打包供用户下载

### 需求 18：Excel 导出兼容

**用户故事：** 作为运营同事，我希望在「按类目分析」模式下仍然可以导出 Excel 文件，以便满足不同的交付需求。

#### 验收标准

1. WHEN 运行模式为「按类目分析」时，THE Streamlit_App SHALL 同时提供「导出 Excel」和「导出 Markdown（按类目）」两个导出按钮
2. THE Excel 导出逻辑 SHALL 与 v1 保持一致，仅在任务表中新增「类目」列
3. THE 任务实时展示表格 SHALL 在「按类目分析」模式下新增「类目」列，显示每条任务的类目信息

### 需求 19：Markdown 文件内容格式

**用户故事：** 作为运营同事，我希望导出的 Markdown 文件结构清晰，方便人工浏览和下游 AI 解析。

#### 验收标准

1. 每个类目的 md 文件 SHALL 遵循以下模板：

```markdown
# {类目名称}

## 视频 1

{模型输出的视频脚本内容}

---

## 视频 2

{模型输出的视频脚本内容}

---
```

2. THE MarkdownExporter SHALL 保留模型输出中的原始换行和格式，不做 trim 或额外处理
3. WHEN 某个类目下只有一个视频时，THE MarkdownExporter SHALL 正常生成该类目的 md 文件，不做特殊处理

## 变更影响分析

### 需要修改的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/video2prompt/models.py` | 扩展 | 新增 `AppMode` 枚举；`TaskInput` / `Task` 增加 `category` 字段（默认空） |
| `src/video2prompt/validator.py` | 扩展 | 新增三列输入（pid + 链接 + 类目）的校验方法 |
| `src/video2prompt/markdown_exporter.py` | 新增 | 按类目分组导出 md 文件 |
| `app.py` | 修改 | 顶部加「运行模式」选择器；按模式切换输入区（2列/3列）；导出区新增「导出 Markdown」按钮 |

### 不需要修改的文件

| 文件 | 说明 |
|------|------|
| `src/video2prompt/task_scheduler.py` | 任务调度逻辑不变，`category` 仅透传 |
| `src/video2prompt/gemini_client.py` | Gemini 调用逻辑不变 |
| `src/video2prompt/volcengine_client.py` | 火山引擎调用逻辑不变 |
| `src/video2prompt/volcengine_*.py` | 所有火山引擎相关客户端不变 |
| `src/video2prompt/parser_client.py` | 视频解析逻辑不变 |
| `src/video2prompt/cache_store.py` | 缓存逻辑不变 |
| `src/video2prompt/circuit_breaker.py` | 熔断逻辑不变 |
| `src/video2prompt/excel_exporter.py` | 现有导出逻辑不变，仅 UI 层按模式决定是否新增类目列 |
| `src/video2prompt/config.py` | 配置管理不变 |
| `src/video2prompt/review_result.py` | 提示词不变 |
| `config.yaml` | 无需新增配置项 |

## 导出目录结构示例

```
exports/
  2026-03-01_143000/          ← 按时间戳创建的导出目录
    服饰.md                    ← 「服饰」类目下所有视频脚本
    美妆.md                    ← 「美妆」类目下所有视频脚本
    3C数码.md                  ← 「3C 数码」类目下所有视频脚本
    未分类.md                  ← 未标注类目的视频脚本
  video2prompt-20260301143000.xlsx  ← 同时可导出的 Excel 文件
```
