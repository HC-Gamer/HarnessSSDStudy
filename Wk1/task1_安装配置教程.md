# OpenCode 安装与配置教程

> 一句话：OpenCode 是一个终端 Agent 框架，让你用自然语言跟 AI 协作写代码。

---

## 1. 安装

### macOS（Homebrew）

```bash
brew install opencode
```

### 其他系统（npm）

```bash
npm install -g @opencodeai/opencode
```

### 验证

```bash
opencode --version
# 输出示例: 1.17.10
```

---

## 2. 配置国产模型 API（以 DeepSeek 为例）

OpenCode 用 `@ai-sdk/openai-compatible` 适配器对接任意 OpenAI 兼容 API。配国产模型只需要改 `baseURL` 即可。

### 2.1 创建配置目录

```bash
mkdir -p ~/.config/opencode
```

### 2.2 主配置文件 `~/.config/opencode/opencode.json`

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "deepseek": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "DeepSeek",
      "options": {
        "baseURL": "https://api.deepseek.com",
        "apiKey": "{env:DEEPSEEK_API_KEY}"
      },
      "models": {
        "deepseek-v4-pro": { "name": "DeepSeek V4 Pro" },
        "deepseek-v4-flash": { "name": "DeepSeek V4 Flash" },
        "deepseek-chat": { "name": "DeepSeek Chat" },
        "deepseek-reasoner": { "name": "DeepSeek Reasoner" }
      }
    }
  },
  "model": "deepseek/deepseek-v4-pro"
}
```

### 2.3 API Key 文件 `~/.config/opencode/secrets.env`

```bash
DEEPSEEK_API_KEY=sk-你的key
```

> OpenCode 启动时自动 source 这个文件，所以 `{env:DEEPSEEK_API_KEY}` 能读到。

---

## 3. 其他国产模型配置示例

格式完全一样，只改 `baseURL` 和模型名：

| 模型 | baseURL | 备注 |
|------|---------|------|
| **阿里 Qwen** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `@ai-sdk/openai-compatible` |
| **智谱 GLM** | `https://open.bigmodel.cn/api/paas/v4` | 同上 |
| **月之暗面 Kimi** | `https://api.moonshot.cn/v1` | 同上 |

在 `opencode.json` 的 `provider` 里加一个同结构的对象，secrets.env 加对应环境变量即可。

---

## 4. 验证对话

```bash
DEEPSEEK_API_KEY="sk-你的key" opencode run "你好，请回复：配置成功" --model deepseek/deepseek-v4-pro
```

成功输出：
```
> build · deepseek-v4-pro
配置成功
```

---

## 5. 常用命令

| 命令 | 说明 |
|------|------|
| `opencode run "..."` | 单次对话模式 |
| `opencode`（无参数） | 交互式 TUI 模式 |
| `opencode --model deepseek/deepseek-v4-pro` | 指定模型 |
| `--dangerously-skip-permissions` | 跳过权限确认（谨慎使用） |

---

## 6. 架构概览（一句话）

```
用户输入 → OpenCode CLI → 读取系统 prompt（含 tool 定义）
  → 调用 LLM API → 解析流式响应
    → 如果 LLM 要求用工具 → 执行工具（读写文件/跑命令）→ 结果喂回 LLM
    → 如果 LLM 认为完成 → 输出结果
```

这就是"编排循环"——LLM 不断决策是"继续用工具"还是"我答完了"，直到任务完成。
