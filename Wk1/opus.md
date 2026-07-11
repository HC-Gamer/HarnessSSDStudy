# 🎯 第 1 节 · AI 编程范式转换 · 实操全集 (Opus)

> 由三份 MD 任务合并而成：
> 1. 任务 1 — 安装 OpenCode + 配置国产模型
> 2. 任务 2 — 裸 API 调用 vs OpenCode 编排对比实验
> 3. 任务 3（SDD 强化训练）— SDD 本质 + 手写第一份 spec

---

# 第 1 节 实操任务1：安装 OpenCode 并配置国产模型

**目标**：OpenCode 启动成功 + AI 对话测试通过

---

## 1.1 安装 Node.js

OpenCode 基于 Node.js，首先通过 `node --version` 确认你的系统已安装 Node.js 18+。

**macOS 用户：**
```plain
# 使用 Homebrew 安装
brew install node

# 验证版本
node --version
```
**Linux / WSL 用户：**
```plain
# Ubuntu / Debian
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# 验证版本
node --version
```
**Windows 用户：**
推荐使用 WSL2 环境。如果不想用 WSL，也可从 [Node.js 官网](https://nodejs.org/zh-cn) 下载安装包。

> **提示**：一般 Linux 已有 Node，如果没有，去[官网](https://nodejs.org/en)查看最新安装步骤。

---

## 1.2 安装 OpenCode

[OpenCode](https://github.com/anomalyco/opencode) 是开源 AI 编程终端工具（MIT 协议），兼容 Claude Code 扩展机制。

**方法 1：npm 全局安装（推荐）**
```plain
npm install -g opencode-ai@latest
```
**方法 2：一键安装脚本**
```plain
curl -fsSL https://opencode.ai/install | bash
```
如果遇到权限问题，macOS/Linux 用户可以加 `sudo`：
```plain
sudo npm install -g opencode-ai@latest
```
安装完成后验证：
```plain
opencode --version
```

**参考资源：**
- OpenCode 官方文档：[https://opencode.ai/docs/](https://opencode.ai/docs/)
- OpenCode GitHub 仓库：[https://github.com/nicepkg/opencode](https://github.com/nicepkg/opencode)
- 安装问题排查：[https://opencode.ai/docs/troubleshooting](https://opencode.ai/docs/troubleshooting)

---

## 1.3 注册国产模型 API Key

### 方案 A：DeepSeek（推荐）

**价格**：¥1/百万 tokens（约 ¥0.001/千 tokens），最便宜的高质量模型。

1. 打开 [https://platform.deepseek.com/](https://platform.deepseek.com/)
2. 点击「注册」，使用手机号注册账号
3. 注册成功后进入控制台，点击左侧「API Keys」
4. 点击「创建 API Key」，给 Key 起名（如 `opencode`）
5. **立即复制**生成的 API Key（格式：`sk-xxxxxxxx`）
6. 充值：左侧「费用」→「充值」，充 ¥5-10 即可用很久

> ⚠️ API Key 只会显示一次，务必立即复制保存！

**参考资源：**
- DeepSeek API 文档：[https://api-docs.deepseek.com/](https://api-docs.deepseek.com/)

### 方案 B：智谱 GLM（有免费额度）
1. 打开 [https://open.bigmodel.cn/](https://open.bigmodel.cn/)
2. 注册账号（手机号），新用户有免费额度
3. 进入「API Keys」→ 创建并复制 API Key

### 方案 C：阿里云 Qwen
1. 打开 [https://bailian.console.aliyun.com/](https://bailian.console.aliyun.com/)
2. 注册/登录阿里云账号，开通百炼服务
3. 获取 DashScope API Key

---

## 1.4 配置环境变量

```plain
# zsh（macOS 默认）
echo 'export DEEPSEEK_API_KEY="sk-你的key"' >> ~/.zshrc
source ~/.zshrc

# bash（Linux 默认）
echo 'export DEEPSEEK_API_KEY="sk-你的key"' >> ~/.bashrc
source ~/.bashrc
```
验证：
```plain
echo $DEEPSEEK_API_KEY
```

---

## 1.5 首次启动 OpenCode

```plain
mkdir ~/opencode-test && cd ~/opencode-test
opencode
```
启动后在对话框中输入：
```plain
你好，请回复 OK 确认连通
```
如果 AI 回复了 OK，环境配置成功！

> **注意**：OpenCode 是比较容易安装成功的。但如果安装真遇到问题，可以使用 Cursor、通义灵码、Trae、Claude Code、Cline 等任意工具来完成本行动营。

---

## 1.6 环境配置自查清单

```plain
☐ Node.js 18+ 已安装（node --version 有输出）
☐ OpenCode 已安装（opencode --version 有输出）
☐ 国产模型 API Key 已获取
☐ 环境变量已配置（echo $DEEPSEEK_API_KEY 有输出）
☐ OpenCode 首次启动成功
☐ AI 对话测试通过（回复了 OK）
```

---

# 第 1 节 实操任务2：裸 API 调用 vs OpenCode 编排对比实验

**目标**：对比实验完成 + 200 字体会文档

---

## 2.1 准备工作

确认 Python 3 可用：
```plain
python3 --version
# 需要 3.10+
```

---

## 2.2 裸 API 调用（无状态推理）

创建测试脚本 `raw_api_test.py`（可放在 `~/opencode-test/`）：
```python
"""
裸 API 调用测试 — 直接调用 DeepSeek API
体验「无状态推理」：模型不知道项目背景，不能读写文件
"""
import os
import json
import urllib.request

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
API_URL = "https://api.deepseek.com/chat/completions"

def call_api(prompt: str) -> str:
    data = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode())
        return result["choices"][0]["message"]["content"]

if __name__ == "__main__":
    print("=" * 60)
    print("测试：让 AI 分析当前项目的代码结构")
    print("=" * 60)

    response = call_api(
        "请分析当前项目的目录结构和代码质量，给出改进建议。"
    )
    print(response)

    print("\n" + "=" * 60)
    print("观察：AI 能看到你的项目文件吗？")
    print("=" * 60)
```
运行：
```plain
python3 raw_api_test.py
```
**观察要点：**
- AI 能看到你的项目文件吗？ → **不能**
- AI 知道你用什么技术栈吗？ → **不知道**
- AI 能执行命令、读写文件吗？ → **不能**

这就是「无状态推理」——模型是一个孤立的函数，输入文本，输出文本。

---

## 2.3 OpenCode 编排（有状态）

现在用 OpenCode 问**完全相同的问题**：
```plain
cd ~/opencode-test
opencode
```
在 OpenCode 对话框中输入：
```plain
请分析当前项目的目录结构和代码质量，给出改进建议。
```

**观察要点：**
- AI 能看到你的项目文件吗？ → **能**（它会用 Glob/Read 工具扫描目录）
- AI 知道文件内容吗？ → **知道**（它会读取文件内容）
- AI 能给出具体建议吗？ → **能**（基于实际文件内容）

这就是「有状态编排」——同一个模型，加了编排器之后，它能读文件、能搜索、能分析，变成了一个有感知能力的系统。

---

## 2.4 写对比体会

创建文件 `comparison.md`，写 200 字的对比体会。参考模板：
```plain
# 裸 API vs OpenCode 对比体会

## 实验过程
- 裸 API 调用：[描述你观察到的现象]
- OpenCode 编排：[描述你观察到的现象]

## 关键差异
- [差异 1：是否能读文件]
- [差异 2：是否有上下文感知]
- [差异 3：建议是否具体]

## 我对「无状态推理」和「有状态编排」的理解
[用自己的话总结]
```

> **作业**：请提交你写的对比体会文档

---

## 核心收获

| | 裸 API 调用 | OpenCode 编排 |
|:----|:----|:----|
| 本质 | 无状态推理 | 有状态编排 |
| 能否看文件 | ❌ | ✅ |
| 能否执行命令 | ❌ | ✅ |
| 上下文感知 | ❌ | ✅ |
| 类比 | 打电话问路 | 开着导航走 |

**关键洞察**：模型是同一个模型（DeepSeek），差别在于编排器赋予了它「感知」和「行动」的能力。

---

# 第 1 节（SDD强化训练）：SDD 本质 + 手写第一份 spec

AI 编程范式的三级跃迁：Prompt → Context → Harness。

> 这一节不装任何工具，只用 Claude Code / OpenCode 本身，手写一份能跑的 spec。

## 预备阅读

- [SDD 的 95/5 原则](https://github.com/huangjia2019/sdd-in-action/blob/master/week1/advance/01-SDD%E7%9A%8495-5%E5%8E%9F%E5%88%99.md)
  （打不开需科学上网）

## 本节目标

给 [ai-knowledge-base/v1-skeleton](https://github.com/huangjia2019/ai-knowledge-base) 写一份项目愿景 spec，决定这个知识库到底要做什么、不做什么、怎么判断成功。这份 spec 最终会变成 `AGENTS.md` 的"项目定义"段。

## 环境准备

```plain
claude --version     # Claude Code
opencode --version   # OpenCode（开源推荐）
```

## 双路并行

### A 路 · Vibe · 5 分钟

复制给 AI：
```plain
你是一位技术产品经理。我在做一个 AI 知识库系统，
自动抓 GitHub Trending / Hacker News / arXiv 的 AI 相关内容，
用 Agent 协作完成采集→分析→整理→发布。
请帮我写一份项目愿景文档。
```

### B 路 · SDD 闭环 · 30 分钟

按三阶段走：**Specify → Clarify → Implement**。

#### 阶段 1 · Specify（10 分钟）

不开 AI。先在 `specs/project-vision.md` 按 4 个 H2 手写：
```plain
# AI 知识库 · 项目愿景 v0.1

## 要做什么
- 每天抓取 GitHub Trending（? 多少条 · 只 AI 相关？）
- 用 Agent 分析内容（? 分析什么 · 输出啥）
- 输出知识条目（? JSON 还是 Markdown · 字段有哪些）

## 不做什么

## 边界 & 验收

## 怎么验证
```
故意留 3-5 个 `?`，作为下阶段给 AI 质询的靶子。

#### 阶段 2 · Clarify（10 分钟）

模拟 Step by Step 的 AI 辅助 SDD 设计。AI 的每个追问都会给"推荐答案"。你可以接受、改成自己的，或说"你决定"放权给 AI。

#### 阶段 3 · Implement（10 分钟）

用 AI 把 clarify 后的 spec 生成最终版本。

## A vs B 对比

| 维度 | A 路线 | B 路线 |
|:----|:----|:----|
| 时间 | 5 min | 30 min |
| 产出 | 一份散文 | spec + AGENTS.md + verify 报告 |
| 走偏概率 | 高 | 低 |
| 两周后记得 | 难 | 易（spec 在 git 里） |

B 路多花的 25 分钟不是"额外开销"，是把调试 2000 行代码的成本，提前投入在了澄清需求的阶段。

## 完成了啥？

- `specs/project-vision.md`（完成版）
- `AGENTS.md` 初稿（可合并进 ai-knowledge-base/v1-skeleton/）
- 一次完整的 Specify → Clarify → Implement 闭环经历

## 下一节

第 2 节 Memory 工程，引入 **grill-me**，把 AGENTS.md 从"能用"升级到"AI 能严格执行"。

---

*Opus 合并完成 · 三个任务原文完整保留 · 2025-07-12*
