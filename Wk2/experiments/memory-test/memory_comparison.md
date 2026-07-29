# Memory 对比实验记录

> 实验日期：2025-07-13
> 实验目的：验证 AGENTS.md（Memory）对 AI 生成代码质量的影响

---

## 实验方法

1. 在项目根目录存在 `AGENTS.md`（定义项目规范、编码标准）的情况下，向 AI 提问：*"帮我写一个 Python 函数，实现从 GitHub API 获取指定仓库的基本信息（Star 数、Fork 数、描述），保存为 utils/github_api.py"*
2. 临时移除 AGENTS.md，向 AI 提问**完全相同的问题**，保存为不同的文件名
3. 对比两个文件的差异

---

## 对比结果

| 检查项 | ✅ 有 Memory | ❌ 无 Memory |
|--------|------------|-------------|
| 命名风格 | snake_case（`get_repo_info`） | camelCase（`getGithubRepoInfo`） |
| 文档字符串 | Google 风格（Args/Returns/Raises） | 非标准风格（简短描述） |
| 日志方式 | `logging` 模块（可配置级别、输出） | 裸 `print()` |
| 错误处理 | 具体异常类型 + 指数退避重试（3次） | 裸 `except Exception`，无重试 |
| 超时控制 | 明确设置 `timeout=10` | 无超时设置 |
| 返回值设计 | 结构化返回 + 异常时为 None | 返回或 None，无一致性保证 |
| 类型注解 | 完整类型提示（`Optional[Dict[str, object]]`） | 无类型注解 |
| 常量管理 | 模块级常量（URL、超时、重试次数） | 硬编码字符串 |
| 文件位置 | 清晰的项目结构意识 | 无结构意识 |

---

## 核心结论

**有 Memory（AGENTS.md）的效果：**

AGENTS.md 就像给 AI 发了一本"员工手册"。它不会告诉 AI 每一行代码该怎么写，而是在 AI 做决策的每一个"模糊时刻"提供方向指引：

- 当 AI 犹豫函数名用 `get_repo_info` 还是 `getGithubRepoInfo` 时 → 手册说"snake_case"
- 当 AI 犹豫要不要写文档时 → 手册说"所有公开函数必须有 docstring"
- 当 AI 犹豫用 `print()` 还是 `logging` 时 → 手册说"禁止裸 print()"

**无 Memory 的效果：**

AI 回到了"出厂设置"——它仍然是强大的代码生成器，但没有了对项目的理解。每个 query 都是一次"第一次见面"：

- 命名风格随模型默认偏好（camelCase 居多）
- 错误处理随意（一把 `try/except Exception`）
- 日志用 `print()`（简单直接但不可管理）

---

## 启示

Memory（AGENTS.md）的本质不是"规定怎么做"，而是**消除不确定性**。在一个没有规范的项目中，AI 每次生成的风格都可能不同——这对个人项目影响不大，但一旦涉及团队协作或长期维护，这种不一致会迅速放大为技术债务。

这就是「声明式配置」的威力——用一个文件声明"要什么"，不用每次口头交代。
