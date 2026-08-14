# 任务书 v4-13: OpenClaw 安装验证 + onboard + Telegram 渠道接入（第一轮：onboard）

你是执行者。本机 macOS。所有命令必须带环境前缀（本机硬性要求）：
  PATH=/Users/huangcheng/.local/node25/bin:$PATH HOME=/Users/huangcheng openclaw ...

## 背景事实（已核实，不要重复调查）
- OpenClaw 已安装: /opt/homebrew/lib/node_modules/openclaw, 版本 2026.7.1-2
- 系统 node (/opt/homebrew/bin/node = 26.4.0) 内嵌 SQLite 3.49.2 太旧，OpenClaw 拒绝写 SQLite —— 不可用
- 必须用独立 node: /Users/huangcheng/.local/node25/bin/node (25.9.0)，命令前 PATH 前置
- workspace 已存在并初始化: ~/ai-knowledge-base/v4-production/openclaw（含 AGENTS.md/IDENTITY.md/SOUL.md/USER.md/TOOLS.md 等）
- ~/.openclaw/ 配置目录尚不存在（未 onboard 或已清）
- 本机无 `openclaw auth` 子命令；验证用 `agents list` / `channels list` / `status`
- DeepSeek API key 在 ~/.hermes/profiles/deepseekco/home/.config/opencode/secrets.env（DEEPSEEK_API_KEY）

## 本轮任务（onboard 阶段，Telegram 另轮）
1. 检查 `~/.openclaw/openclaw.json` 是否存在；若已存在，先报告其内容再决定是否跳过 onboard
2. 若不存在，执行 onboard：
   source ~/.hermes/profiles/deepseekco/home/.config/opencode/secrets.env
   PATH=/Users/huangcheng/.local/node25/bin:$PATH HOME=/Users/huangcheng \
     openclaw onboard --skip-health --non-interactive --accept-risk --mode local \
     --auth-choice deepseek-api-key --deepseek-api-key "$DEEPSEEK_API_KEY" \
     --workspace /Users/huangcheng/ai-knowledge-base/v4-production/openclaw \
     --skip-channels --skip-search --skip-skills --no-install-daemon --skip-ui --json
   - 不装 daemon 时 gateway 健康检查必然失败 → 必须 --skip-health，否则 EXIT=1
   - 若报 "auth store lock may be busy" 之类包装错误 → 用 openclaw --log-level trace 挖真实错误，grep sqlite/lock；不要重复盲目重试
3. 验证：
   - openclaw agents list → 应显示 main agent + Model（deepseek/deepseek-v4-flash）
   - openclaw channels list → 报告当前渠道
   - openclaw status → 报告 gateway/健康状态
4. 报告：每一步实际命令 + 输出要点 + 最终状态（agent 名/模型/渠道列表）

## 边界
- 本轮不要创建 Telegram bot（token 未提供，由用户另行提供后第二轮接入）
- 不要改 workspace 里已有的 AGENTS.md/SOUL.md 等文件
- 失败时给出根因分析和确切修复命令，不要猜测

完成后输出简洁中文总结（≤15 行）。
