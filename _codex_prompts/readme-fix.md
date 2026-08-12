编辑 README.md 文件做两件事：

1. 删除"规范与配置"整个 section（从 `## 规范与配置` 到其下所有表格行，直到下一个 `---` 分隔线之前），包括中间的空行。

2. 修复前 3 篇博客的链接——它们当前指向错误的路径：
   - 博客1：`blogs/blog1_安装配置实战指南_2025-07-12.md` → 改为 `blogs/harness-study/blog1_安装配置实战指南_2026-07-12.md`
   - 博客2：`blogs/blog2_无状态vs有状态_对比实验报告_2025-07-12.md` → 改为 `blogs/harness-study/blog2_无状态vs有状态_对比实验报告_2026-07-12.md`
   - 博客3：`blogs/blog3_源码深度解析_编排循环_2025-07-12.md` → 改为 `blogs/harness-study/blog3_源码深度解析_编排循环_2026-07-12.md`

注意：博客 4-8 的链接已经是正确的 `blogs/harness-study/blogN_...` 格式，不要改动它们。

编辑完成后验证：
- "规范与配置" 字符串不再出现在 README.md 中
- 所有 8 篇博客链接都以 `blogs/harness-study/` 开头