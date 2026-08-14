# 任务书 v4-16b: 毕业交付收尾 — README + 23张截图 + git push（第二轮：Opus 执行）

你是执行者。本机 macOS。所有命令必须带环境前缀：
  HOME=/Users/huangcheng ...   （Claude Code 订阅凭证在真实 home，不要用 ~）

## 环境硬性要求（本机）
- 项目实体路径: /Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/毕业设计/ai-knowledge-base
- Python: /Users/huangcheng/ai-knowledge-base/.venv/bin/python（PIL 若缺失用 `$PY -m pip install pillow`）
- git 凭证: HC-Gamer 默认 key（git@github.com:HC-Gamer/HarnessSSDStudy.git）
- 不要用 `~` 展开；全部绝对路径

## 背景事实（已核实，不要重复调查，不要重新跑管线）
- 上一轮 Opus 已生成 24 个运行证据（检查点 01-24，txt 格式）在 /tmp/shots/：
  01-pipeline-run.txt 02-langgraph-workflow-run.txt 04-pytest-all-green.txt 05-cost-guard-selftest.txt
  06-security-three-defenses.txt 07-eval-test-report.txt 08-pattern-router.txt 09-router-unit-tests.txt
  10-pattern-planner.txt 11-reviewer-5dim.txt 12-human-flag.txt 13-validate-schema-gate.txt
  14-formatter-two-formats.txt 15-publisher-dryrun.txt 16-daily-digest-dryrun.txt 17-knowledge-bot-intent.txt
  18-costguard-breaker.txt 19-env-keys-permissions.txt 20-skills-least-privilege.txt 21-requirements-pinned.txt
  22-knowledge-store-stats.txt 23-openclaw-model-live.txt 24-dingtalk-bridge-live.txt
- 注意：09/10 曾出现 exit=1 的尝试（supervisor/planner 模式验证），但 09-router-unit-tests.txt 和 10-pattern-planner.txt 已含通过证据；若 09/10 内容是空/失败，重试一次该检查点（真实 DeepSeek API 调用，可能网络抖动），仍失败则写入 checklist 备注（降级说明），不伪造通过
- 16-2 完整性 18 文件清单 + README 7 部分结构在 PLANNING 第 213-263 行:
  /Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/PLANNING-WK3-WK4-CAPSTONE.md
- 任务要求截图 ≥23 张（文件名自解释，如 01-pipeline-run.png）
- 真实 .env 含密钥已 gitignore；README 用 .env.example 口径
- git 当前: main 分支，无未提交业务改动（plans/ 与 v4-production/ 是未跟踪目录，属正常——它们会作为交付内容提交）

## 本轮任务
1. 先读 PLANNING 第 213-263 行，确认 Checklist 10 项与 18 文件清单的确切口径
2. 把 /tmp/shots/ 全部证据文件复制到 docs/evidence/（保留原文件名），作为 16-1 Checklist 留证
3. 生成 ≥23 张截图存 screenshots/（目录已存在，空）：
   - 用 $PY + PIL（Pillow）把每个证据 txt 渲染成终端风格 PNG（深色背景 #1e1e1e + 等宽字体 12px，标题行注明检查点名），文件名与证据对应（01-pipeline-run.png ...）
   - 字体: /System/Library/Fonts/Menlo.ttc 或 /System/Library/Fonts/Supplemental/Courier New.ttf；PIL 用 ImageFont.truetype
   - 文本超长自动换行/分页（每页上限 ~50 行，超过则多页 01a/01b 或截断加省略说明）；单张不超 1200px 宽
   - 渲染完逐一验证: 每个 png 非 0 字节、可打开（用 $PY PIL Image.open 校验）
4. 写根目录 README.md（7 部分）：
   - ① 项目简介 + 架构图（文本框制，终端可读）
   - ② 快速开始（陌生人 clone → cp .env.example .env 填 key → 三步跑出结果，不含 Telegram 部分）
   - ③ 目录结构表
   - ④ 技术栈
   - ⑤ 版本历史（V1→V4）
   - ⑥ 月度成本估算
   - ⑦ MIT License
   - 另加"运行截图"段引用 screenshots/ 文件名
5. 检查 .env.example 是否存在且完整（缺失则按 requirements.txt + 代码里的环境变量名补齐，不含真实密钥值）
6. git add + 有意义 commit（可分 2-3 条：docs(README+evidence) / feat(screenshots) 等）+ push 到 origin main

## 验证
- git push 成功，git log 有新 commit，origin/main 同步
- screenshots/ ≥23 张有效 png（PIL 全部能打开）
- docs/evidence/ 含全部证据
- README.md 七部分齐全 + 截图段
- Checklist 10 项在 README 或 docs 里有验证记录

## 边界（本轮不做）
- 不创建 Telegram bot（token 未提供，另轮）
- 不修改 v4-production 业务代码（除非有致命阻塞 bug；supervisor 运行时错误走降级记录）
- 不做 Docker 部署（M4 加分项，本机无 Docker）
- 不提交课程版权文件（rtf/pdf）
- 不在 README 写真实密钥/内网地址

## 失败处理
- PIL 缺失 → `$PY -m pip install pillow`；字体缺失 → 用系统内其他 .ttf/.ttc（fc-list 或 ls /System/Library/Fonts）
- git push 认证失败 → `ssh -T git@github.com` 验证（HC-Gamer 默认 key）；不要改 remote
- 渲染 PNG 出错 → 逐张捕获异常，报告具体哪张失败+原因，不整体放弃

完成后输出简洁中文总结（≤15 行）：截图数量 + README 状态 + evidence 数量 + push 结果 + 降级项。
