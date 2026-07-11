# 任务2：对比实验报告 — 裸 API 调用 vs OpenCode 编排

## 实验设定

- **任务**：分析一段 Python 代码（Fibonacci 生成函数）的功能、优缺点和改进建议
- **模型**：DeepSeek Chat（裸 API）/ DeepSeek V4 Pro（OpenCode）
- **被测代码**：`/tmp/task2_sample.py`

---

## 方式一：裸 API 调用（Python requests）

### 代码

```python
import requests, json

API_KEY = "sk-xxx"
URL = "https://api.deepseek.com/v1/chat/completions"

code = open("/tmp/task2_sample.py").read()
prompt = f"请分析以下 Python 代码的功能、优缺点和改进建议：\n\n```python\n{code}\n```"

resp = requests.post(URL, headers={
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}, json={
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 800
})

result = resp.json()
print(result["choices"][0]["message"]["content"])
```

### 特征

| 维度 | 表现 |
|------|------|
| **请求** | 手动构造 HTTP POST，设置 headers、body |
| **上下文** | 无，每次调用都必须重复传入全部上下文 |
| **文件读取** | 手动 `open()` 读文件，手动拼进 prompt |
| **状态管理** | 无，每次调用完全独立 |
| **toke 用量** | 需要手动追踪 `usage` 字段 |
| **错误处理** | 需要自己写 try/except 处理网络错误和 API 错误 |
| **输出** | 原始 JSON，需要解析 |

---

## 方式二：OpenCode 编排

### 命令

```bash
opencode run "请分析 /tmp/task2_sample.py 这个文件的功能、优缺点和改进建议" \
  --model deepseek/deepseek-v4-pro
```

### 特征

| 维度 | 表现 |
|------|------|
| **请求** | 一句话，CLI 帮你构建完整请求 |
| **上下文** | 之前的对话历史自动保留为上下文 |
| **文件读取** | 自动识别文件路径，读取后注入 prompt（输出日志可见 `→ Read /tmp/task2_sample.py`） |
| **状态管理** | 全自动，每次对话后状态更新，新对话继承历史 |
| **token 用量** | CLI 自动追踪和报告 |
| **错误处理** | 内置重试和错误提示 |
| **输出** | 格式化 markdown，直接可用 |

---

## 核心差异：无状态 vs 有状态

### 裸 API 的感受（无状态）

调用裸 API 就像**每次给陌生人写一封完整的信**。即使我问的是同一个话题，我也必须：

1. 重新告诉它我是谁
2. 重新提供全部背景信息
3. 重新附上代码全文
4. 重新声明我想要的分析格式
5. 等待它从零开始回答

每个请求都是**原子的、独立的、无记忆的**。Token 浪费在反复传输已交代过的上下文上。如果需要追问，我得手动把之前的对话历史塞进 `messages` 数组——而这正是我在上面的代码中没做的事，因为**太麻烦了**。

### OpenCode 的感受（有状态）

用 OpenCode 就像**和一个驻场的分析师合作**：

1. 我只说了一句话，它自动发现我要分析的文件并读取
2. 它记住了对话上下文——如果我问"再深入分析性能"，它知道我在说什么
3. 它管理了自己的 token 预算和请求格式
4. 错误出现时它会重试，不需要我操心

OpenCode 不是在做"请求-响应"，而是在**维持一个持续的协作会话**。我并不关心 HTTP 状态码、JSON 解析、token 计数——这些被抽象掉了。我只关心任务本身。

### 一句话总结

> **无状态是你每次都要把地球背在身上；有状态是你只要说"继续"就够了。**  
> 裸 API 让你当接线员，OpenCode 让你当指挥官。

---

## 附：输出对比摘要

| 项目 | 裸 API（DeepSeek Chat） | OpenCode（DeepSeek V4 Pro） |
|------|------------------------|----------------------------|
| 功能分析 | ✓ 详细列出 | ✓ 结构化表格 |
| 优缺点 | ✓ 5条缺点 | ✓ 8项分类建议 |
| 改进代码 | ✓ 4个版本（生成器、矩阵幂等） | ✓ 表格式快速建议 |
| 展示形式 | 纯 Markdown 段落 | 按类别分组的 Markdown 表格 |
| 人类操作步骤 | 写脚本→填 key→运行→解析输出 | 一句话命令 |
| 总耗时（含思考） | ~6秒 API + 5分钟写脚本 | ~10秒 CLI |
