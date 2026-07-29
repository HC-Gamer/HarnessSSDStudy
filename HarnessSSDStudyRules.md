# HarnessSSDStudy — Agent 规章制度

## 一、项目定位

HarnessSSDStudy 是 OpenCode 学习与实践系列仓库。所有内容围绕 AI Agent 框架的实操经验整理为技术博客。

## 二、工作流程

### 2.1 标准处理流程
1. 接收原始资料（如「01资料包」）
2. 扫描并理解全部材料
3. 合并原始文件（如需）
4. 执行实验/分析并记录结果
5. 使用 `tech-blog-from-research` 生成博客
6. 创建/更新 README 索引
7. 发布到 GitHub

### 2.2 默认加载 Skill
在此项目下，每个新任务默认加载：
- `writing-plans` — 写实现计划
- `plan` — plan mode
- `subagent-driven-development` — 子 Agent 执行

其余 skill 按需加载。

## 三、输出规范

### 3.1 README 索引
- 纯编号列表：`1. Title (date)`
- 无 emoji、无工具图标、无装饰性前缀
- 每篇博客后跟一行 excerpt（blockquote 格式）

### 3.2 归属声明
- 使用通用语言：「由 AI 辅助生成」
- 不列出具体工具名称、模型或提供商

### 3.3 博客格式
- GitHub-flavored Markdown
- 标题含日期：`# Title (YYYY-MM-DD)`
- 从 "Why" 开始，再讲 "How"
- 包含作者观点、对比分析、最佳实践
- 无 AI 元评论，无 MEDIA:/path 标签

## 四、Git 规范

### 4.1 发布规则
- 每次发布 squash 为 1 个 clean commit
- commit message 简明描述本次内容
- 使用 force push 覆盖远程

### 4.2 授权身份
- 主账号：HC-Gamer (patrick.huangchengai@gmail.com)
- 发布前确认 git config user.email 正确

## 五、上下文管理

- 复杂任务超过 200 条消息时压缩上下文
- 压缩前确保关键状态已写入 MEMORY
- 压缩后不重复已完成的工作

## 六、技能维护

- 发现 skill 过时或不完善 → 立即 patch
- 发现新可复用流程 → 创建新 skill
- 不维护的 skill 标记为 deprecated
