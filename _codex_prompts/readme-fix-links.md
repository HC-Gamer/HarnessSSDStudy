编辑 /Users/huangcheng/blogs/geekbang-study/README.md 中"Agent 设计模式之美"表格的链接。

逐行检查 blog1 到 blog19 的链接是否与实际文件一一对应。文件都在 /Users/huangcheng/blogs/geekbang-study/blogs/agent-design-patterns/ 目录下。

先 ls 该目录获取所有 blog 文件精确文件名，然后逐一比对 README 里的链接路径。任何链接与实际文件名不匹配的，修正为正确文件名。

blog1 的链接逻辑作为标准模板：
```
| 1 | [显示标题](blogs/agent-design-patterns/精确文件名.md) | 日期 |
```

重点检查 blog6, blog7, blog8 — 用户反馈这三篇的链接逻辑有问题。如果发现不匹配，用精确文件名修正。

修正完用 git diff 展示改动。