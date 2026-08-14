# 任务书 v4-16: 第16节 上线 Checklist + README + 23张截图 + 提交毕业项目（委派 Opus）

你是执行者。本机 macOS（Mac mini）。所有命令必须带环境前缀（本机硬性要求）：
  HOME=/Users/huangcheng claude ...   （Claude Code 订阅凭证在真实 home，Hermes 终端 ~ 会展开到 profile home，必须用绝对路径）

## 环境硬性要求（本机）
- Claude Code 用 `HOME=/Users/huangcheng` 前缀启动（否则订阅凭证找不到）
- 项目实体路径: /Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/毕业设计/ai-knowledge-base（软链 /Users/huangcheng/ai-knowledge-base）
- 不要用 `~` 展开——全部写绝对路径
- git 凭证: 默认账号 HC-Gamer（git@github.com:HC-Gamer/HarnessSSDStudy.git）

## 背景事实（已核实，不要重复调查）
- 课件 16 节 md 在: /Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/Wk4/courseware/Week 4课件&实操任务合集-新/16资料包/md版/
  - 第 16 节 实操任务 1：上线前 Checklist 验证.md
  - 第 16 节 实操任务 2：提交毕业项目.md
- 总体规划（含 16-1 Checklist 10 项、16-2 完整性 18 文件清单、README 7 部分结构）在:
  /Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/PLANNING-WK3-WK4-CAPSTONE.md（第 213-263 行附近）
- 项目结构: v4-production/ 含 pipeline/, workflows/, patterns/, bot/, distribution/, openclaw/, tests/, scripts/, data/, logs/, docs/, daily_digest.py, run.sh, requirements.txt, pytest.ini
- 当前 git: main 分支，remote=HC-Gamer/HarnessSSDStudy，最近 commit 0663af4（chore: gitignore 忽略课程版权 rtf）
- 任务要求: 截图 23 张（任务清单明确），课件要求 ≥3 张（截图1管线运行成功/截图2 Telegram推送/截图3日志成本）——按任务清单 23 张执行，覆盖 16 节各功能点，文件名自解释
- Telegram bot token 尚未提供（另一任务 v4-13b 待办）——Telegram 实推截图不可用，用「配置就绪 + 运行日志 + 说明」降级，不得伪造
- 真实 .env 含密钥（DINGTALK/DEEPSEEK），已 gitignore；README 用 .env.example 口径
- 钉钉 bridge 正在后台运行（PID 67907），管线跑通有真实数据在 logs/ 和 data/

## 本轮任务
1. 先读 16 资料包两份 md + PLANNING 第 213-263 行，整理出精确的 Checklist 与交付物清单
2. 执行 16-1 上线前 Checklist（10 项），逐项验证并留证（输出到 v4-production/docs/evidence/ 或根目录 checklist 文件）
3. 执行 16-2 完整性检查（18 个文件全 [OK]，Docker 两文件若不存在则降级说明以 launchd/cron 替代并标 [!!]）
4. 写根目录 README.md（7 部分：架构图(文本框可读) / 快速开始 / 目录结构表 / 技术栈 / 版本历史 / 月度成本 / MIT License），陌生人 clone 后三步可跑
5. 生成 ≥23 张运行截图存 screenshots/ 目录（文件名自解释如 01-pipeline-run.png）：
   - 跑管线（run.sh 或 daily_digest.py）截真实运行证据
   - 截 workflow 图/状态、日志/成本统计、各 V1-V4 关键产出
   - macOS 截屏用 `screencapture -x -l <windowid>` 或对产物文件截图；终端窗口截图要含真实输出
   - 每张图配一行说明写进 README 截图段或单独截图清单文件
6. git 提交（有意义的 commit 信息，可分多条），push 到 origin main

## 验证
- git push 成功（git log 有新 commit，origin/main 同步）
- screenshots/ 存在且 ≥23 张有效 png（非 0 字节）
- README.md 七部分齐全
- Checklist 10 项逐项有验证记录（pass/降级说明）

## 边界（本轮不做）
- 不创建 Telegram bot（token 未提供，v4-13b 另轮）
- 不修改真实 .env 密钥内容；不改 v4-production 业务代码逻辑（除非 Checklist 发现必须修的 bug，修完注明）
- 不做 Docker 部署（PLANNING 已列为 M4 加分项，本机无 Docker）
- 不把课程版权文件（rtf/pdf）提交进仓库

## 失败处理
- 截屏权限问题（Screen Recording TCC）→ 用 screencapture 失败则改用对文件产物截图（HTML/图片文件本身），或 qlmanage -t 生成缩略图；不要卡在窗口截屏
- git push 认证失败 → 检查 ssh -T git@github.com（HC-Gamer 默认 key）；不要改 remote
- 管线跑挂 → 读 logs/ 最新日志定位，只修阻塞性的环境问题，业务 bug 记录到 checklist 备注

完成后输出简洁中文总结（≤15 行）：实际命令要点 + Checklist 结果 + 截图数量 + README 状态 + push 结果。
