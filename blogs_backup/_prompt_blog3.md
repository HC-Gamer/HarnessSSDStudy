你是一位资深的技术写作专家，同时也是 AI Agent 开发者和专业计算机工程师。你要为同样水平的读者写一篇技术博客。

## 原始素材

下面是原始的研究笔记/实验记录，请基于它进行深度扩展和升华，写成一篇有观点、有深度、有人味儿的技术博客。

## 写作要求

1. 文章定位：面向 AI Agent 开发学习者和专业计算机工程师
2. 风格：技术专栏风格，像一篇发表在 InfoQ、阿里技术、知乎专栏的文章
3. 结构：先讲清"为什么要读源码"，再逐层级深入架构、核心循环、事件处理、prompt 设计、并发机制、上下文压缩
4. 深度：不要只是翻译源码注释。要分析设计意图、trade-off、学到的东西
5. 人情味：表达阅读源码时的"aha moment"，对设计决策的个人评价
6. 格式：标准 Markdown，代码块用 Go 语法高亮
7. 标题格式：标题包含时间戳 2025-07-12
8. 输出：只输出文章正文，不要额外解释

## 需要覆盖的核心内容

- 源码地址：github.com/opencode-ai/opencode，Go 语言
- 核心目录：internal/llm/agent/ 和 internal/llm/prompt/
- 架构总览：Observe → Think → Act → Update State 模式 + 基于 channel 的事件驱动
- 主循环 processGeneration：for 循环 + continue 构成 Agent 的自循环
- 核心决策：FinishReason == ToolUse → 继续；否则结束
- 流处理 streamAndHandleEvents：eventChan 逐个处理
- 事件类型：EventThinkingDelta, EventContentDelta, EventToolUseStart/Stop, EventComplete
- System Prompt 定义思考框架（coder.go 中的两套 prompt）
- 子 Agent 机制 agentTool：spawn 子 Agent 做并行搜索
- 上下文压缩 Summarize：自动压缩长对话
- 个人评价：对"没有固定步数限制的循环"这个设计哲学的理解
