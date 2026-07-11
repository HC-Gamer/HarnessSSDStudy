# 任务3：OpenCode 源码中的编排循环（Agent Loop）

> 源码地址：https://github.com/opencode-ai/opencode  
> 语言：Go  
> 核心目录：`internal/llm/agent/` 和 `internal/llm/prompt/`

---

## 一、架构总览

OpenCode 的编排循环遵循经典的 **Observe → Think → Act → Update State** 模式，实现为一个**基于 channel 的事件驱动流**。

```
                    ┌────────────────────┐
                    │    User Input      │
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │  processGeneration │  ← 主循环入口
                    └────────┬───────────┘
                             │
              ┌──────────────▼──────────────┐
              │   streamAndHandleEvents     │  ← "Observe + Think"
              │   (调用 LLM，流式处理事件)   │
              └──────────────┬──────────────┘
                             │
              ┌──────────────▼──────────────┐
              │   FinishReason == ToolUse?  │  ← "Act" 决策
              └──────┬──────────────┬───────┘
                     │ NO           │ YES
                     │              │
              ┌──────▼────┐  ┌──────▼──────────────┐
              │ 返回结果   │  │ 执行工具 → 结果追加  │
              │ Done=true  │  │ 到 msgHistory        │
              └───────────┘  └──────┬───────────────┘
                                    │
                     ┌──────────────▼──────────────┐
                     │     回到 for 循环顶部       │  ← 循环继续
                     └─────────────────────────────┘
```

---

## 二、核心代码片段

### 2.1 主循环 — `processGeneration`（agent.go:233-311）

```go
func (a *agent) processGeneration(ctx context.Context, sessionID, content string, ...) AgentEvent {
    // 1. 读取历史消息
    msgs, err := a.messages.List(ctx, sessionID)
    
    // 2. 创建用户消息，追加到历史
    userMsg, _ := a.createUserMessage(ctx, sessionID, content, attachmentParts)
    msgHistory := append(msgs, userMsg)

    // 3. 🟢 主循环：观察→思考→行动→更新
    for {
        // 3a. 检查取消
        select {
        case <-ctx.Done():
            return a.err(ctx.Err())
        default:
        }

        // 3b. 流式调用 LLM，处理事件（观察 + 思考）
        agentMessage, toolResults, err := a.streamAndHandleEvents(ctx, sessionID, msgHistory)

        // 3c. 如果 LLM 决定使用工具（Act）
        if (agentMessage.FinishReason() == message.FinishReasonToolUse) && toolResults != nil {
            // 追加助手消息 + 工具结果到历史（Update State）
            msgHistory = append(msgHistory, agentMessage, *toolResults)
            continue  // ← 回到循环顶部！
        }

        // 3d. LLM 认为任务完成，返回结果
        return AgentEvent{Type: AgentEventTypeResponse, Message: agentMessage, Done: true}
    }
}
```

**关键点**：`for` 循环 + `continue` 构成了 Agent 的**自循环**。每次 LLM 返回 `FinishReasonToolUse`，就表示它选择了工具调用，循环继续；否则表示它认为任务已完成，退出。

---

### 2.2 流的处理 — `streamAndHandleEvents`（agent.go:322-438）

```go
func (a *agent) streamAndHandleEvents(ctx context.Context, sessionID string, msgHistory []message.Message) (...) {
    // 1. 流式调用 LLM
    eventChan := a.provider.StreamResponse(ctx, msgHistory, a.tools)

    // 2. 逐个处理流事件
    for event := range eventChan {
        a.processEvent(ctx, sessionID, &assistantMsg, event)
    }

    // 3. LLM 流结束后，执行所有工具调用
    for i, toolCall := range toolCalls {
        toolResult, toolErr := tool.Run(ctx, tools.ToolCall{...})
        toolResults[i] = message.ToolResult{...}
    }

    return assistantMsg, &toolMsg, nil
}
```

**数据流**：`msgHistory → LLM Stream → 事件处理 → 工具调用 → toolResults`

---

### 2.3 事件类型 — `processEvent`（agent.go:445-492）

```go
func (a *agent) processEvent(ctx context.Context, ...) error {
    switch event.Type {
    case provider.EventThinkingDelta:
        assistantMsg.AppendReasoningContent(event.Content)   // 思考过程
    case provider.EventContentDelta:
        assistantMsg.AppendContent(event.Content)             // 文字输出
    case provider.EventToolUseStart:
        assistantMsg.AddToolCall(*event.ToolCall)             // 工具调用开始
    case provider.EventToolUseStop:
        assistantMsg.FinishToolCall(event.ToolCall.ID)        // 工具调用结束
    case provider.EventComplete:
        assistantMsg.AddFinish(event.Response.FinishReason)   // 完成
    case provider.EventError:
        return event.Error
    }
}
```

这是**观察（Observe）** 的实现：从 LLM 流中解析思考文本、文字输出、工具调用和结束信号。

---

### 2.4 System Prompt — 定义"思考方式"（prompt/coder.go）

开源版中有两套 prompt：Anthropic 风格（base）和 OpenAI 风格。以 Anthropic 为例：

```
You are OpenCode, an interactive CLI tool that helps users with
software engineering tasks.

# Doing tasks
1. Use search tools to understand the codebase
2. Implement the solution
3. Verify with tests
4. Run lint and typecheck

# Tool usage policy
- Launch multiple agents concurrently whenever possible
- If you call multiple independent tools, do it in one block
```

Prompt 定义了 Agent 的"思考框架"——什么时候搜索、什么时候执行、什么时候验证。

---

### 2.5 子 Agent 工具 — `agentTool`（agent-tool.go:43-97）

```go
func (b *agentTool) Run(ctx context.Context, call tools.ToolCall) (tools.ToolResponse, error) {
    // 1. 创建一个新的 Task Agent
    agent, _ := NewAgent(config.AgentTask, b.sessions, b.messages, TaskAgentTools(b.lspClients))
    
    // 2. 创建子 session
    session, _ := b.sessions.CreateTaskSession(ctx, call.ID, parentSessionID, "New Agent Session")
    
    // 3. 运行子 Agent（阻塞等待结果）
    done, _ := agent.Run(ctx, session.ID, params.Prompt)
    result := <-done
    
    // 4. 费用合并到父 session
    parentSession.Cost += updatedSession.Cost
}
```

这是 OpenCode 实现**层次化编排**的关键——Agent 可以 spawn 子 Agent 做并行搜索，然后汇总结果。

---

### 2.6 上下文压缩 — `Summarize`（agent.go:535-704）

```go
// 当对话太长时，后台自动压缩
summarizePrompt := "Provide a detailed but concise summary of our conversation..."
response, _ := a.summarizeProvider.SendMessages(summarizeCtx, msgsWithPrompt, ...)

// 将摘要作为第一条消息写回 session
msg, _ := a.messages.Create(summarizeCtx, oldSession.ID, message.CreateMessageParams{
    Role:  message.Assistant,
    Parts: []message.ContentPart{message.TextContent{Text: summary}},
})
oldSession.SummaryMessageID = msg.ID
```

**实现了"有状态"的关键机制**：对话太长时自动压缩历史，保留精华作为上下文继续对话。

---

## 三、编排循环总结

| 步骤 | 对应源码 | 描述 |
|------|----------|------|
| **Observe**（观察） | `processEvent` 循环 | 从 LLM 流中接收文本、思考、工具调用事件 |
| **Think**（思考） | `StreamResponse` → LLM | 把 msgHistory 发给 LLM，让模型选择回复或工具 |
| **Act**（行动） | `streamAndHandleEvents` 中的工具执行 | 遍历所有 toolCalls，逐一执行并收集结果 |
| **Update State**（更新状态） | 追加 `agentMessage + toolResults` 到 msgHistory | 把"做了什么+结果"写回会话历史，供下一轮思考 |

**循环条件**：只要 LLM 的 `FinishReason == ToolUse`，循环继续；否则结束。

**核心设计哲学**：  
OpenCode 把 Agent 的每一次交互建模为**一个无限循环**，LLM 每次响应要么是"我需要用个工具"（继续），要么是"任务完成了"（结束）。这种**没有固定步数限制的循环**，让 Agent 可以反复推理直到自认为完成——这正是"有状态编排"的精髓。
