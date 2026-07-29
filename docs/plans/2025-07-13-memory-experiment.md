# Memory 对比实验方案

> **目标：** 有 Memory (AGENTS.md) vs 无 Memory 场景下，AI 生成代码的差异验证

**实验地点：** `/Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/`

**已有基础设施：**
- AGENTS.md 已存在（定义了项目规范、技术栈、编码规范、Agent 角色）
- OpenCode 已配置（deepseek-chat 模型）
- Git 已初始化

**实验输出：** `Wk2/blogs/blog4_memory对比实验报告_2025-07-13.md`

---

## Task 1：为实验创建独立目录

创建 `Wk2\experiments\memory-test/` 并在其中存放实验相关文件。

## Task 2：Phase 1 — 有 Memory 状态下生成代码

1. 确保 AGENTS.md 在项目根目录存在
2. 用 OpenCode 生成一个 Python 函数：`utils/github_api.py`，功能是从 GitHub API 获取指定仓库信息（Star 数、Fork 数、描述）
3. 记录 AI 输出，检查维度：命名风格、docstring 有无、日志方式、错误处理、文件位置

## Task 3：Phase 2 — 临时移除 Memory

1. `mv AGENTS.md AGENTS.md.bak`
2. 删除或重命名 `utils/github_api.py`
3. 重新启动 OpenCode，输入相同提示词，生成 `utils/github_api_new.py`

## Task 4：Phase 3 — 恢复 Memory 并对比

1. `mv AGENTS.md.bak AGENTS.md`
2. 对比两个文件的差异
3. 生成 `memory_comparison.md` 记录对比结果

## Task 5：产出博客 blog4

使用 `tech-blog-from-research` 技能生成博客，输出到 `Wk2/blogs/blog4_memory对比实验报告_2025-07-13.md`

## Task 6：更新 README 索引

在 `README.md` 中添加 blog4 条目。
