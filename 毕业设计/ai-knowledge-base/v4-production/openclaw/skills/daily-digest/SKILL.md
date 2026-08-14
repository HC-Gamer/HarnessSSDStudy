---
name: daily-digest
description: 用户要今日/每日简报、daily digest、今日推送、今天有什么新内容时使用。触发词：简报、摘要、今日、今天、daily、digest、briefing、推送一下。
allowed-tools:
  - Bash
  - Read
---

# 每日简报技能

## 触发条件

当用户想看今日 / 最近的 AI 技术汇总，或想手动触发一次每日推送时激活。
典型触发词：简报、摘要、今日、今天、daily、digest、briefing、推送一下、发一下今天的。

## 执行步骤

### Step 1：运行 dry-run 推送

在项目根目录 `v4-production/` 下运行：

```bash
python3 daily_digest.py --dry-run
```

`--dry-run` 保证不会真的发消息出去（即便已经配置了 `TELEGRAM_BOT_TOKEN`），
只生成简报内容并打印预览，适合在 Bot 会话里安全触发。

### Step 2：把结果发给用户

把命令输出里「Telegram 推送预览」和「推送结果」两段整理后回复给用户：
本次简报的文章数量、每条渠道是否成功（dry-run 恒为 ✅）。
不要照抄原始日志格式，转成简洁的自然语言 + 列表。

### Step 3：失败时给出原因

如果命令非零退出或打印 `⚠️ 无高质量文章`：
- 无高质量文章：如实告知用户「今天没有 relevance_score >= 0.6 的新条目」，不要编造内容。
- 命令报错（如 `ModuleNotFoundError`）：把报错原文贴给用户，并提示检查是否在 `v4-production/` 根目录、
  是否用了项目 venv（`~/ai-knowledge-base/.venv/bin/python3`）运行。

## 禁止

- 不要跳过 `--dry-run` 直接触发真实推送（真实推送只在用户明确要求"真的发出去"时才做）。
- 不要编造文章内容或推送结果，一切以命令实际输出为准。
