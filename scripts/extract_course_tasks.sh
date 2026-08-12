#!/bin/bash
# ── Harness 训练营 Wk3/Wk4 实操任务自动提取 ──
# 使用 osascript 驱动 Safari，提取每节课内容，生成缺漏报告
# crontab: 0 22 * * *

set -e
LOG="/tmp/harness_extract_$(date +%Y%m%d_%H%M).log"
exec > >(tee -a "$LOG") 2>&1

PROJECT_DIR="/Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy"
EXTRACT_DIR="$PROJECT_DIR/extracted_course"
mkdir -p "$EXTRACT_DIR"

echo "=== $(date) Harness Wk3/Wk4 提取开始 ==="

#######################################################
# Step 1: 确保 Safari 已打开课程页面
#######################################################
echo "Step 1: 确认 Safari 状态..."

SAFARI_OPEN=$(osascript -e 'tell application "System Events" to (name of processes) contains "Safari"' 2>/dev/null || echo "false")

if [ "$SAFARI_OPEN" != "true" ]; then
    echo "启动 Safari 并导航到课程页面..."
    open -a Safari "https://u.geekbang.org/subject/lesson/100138101"
    sleep 8
else
    echo "Safari 已运行"
    # 检查当前页面
    CURRENT_URL=$(osascript -e 'tell application "Safari" to URL of current tab of window 1' 2>/dev/null || echo "")
    echo "  当前 URL: $CURRENT_URL"
    if [[ ! "$CURRENT_URL" =~ u\.geekbang\.org ]]; then
        osascript -e 'tell application "Safari" to set URL of current tab of window 1 to "https://u.geekbang.org/subject/lesson/100138101"'
        sleep 6
    fi
fi

#######################################################
# Step 2: 展开 Week 3 + Week 4，提取所有课程标题
#######################################################
echo "Step 2: 展开课程大纲并提取标题..."

osascript -s o <<'ASEOF' 2>/dev/null
tell application "Safari"
  -- 点击展开 Week 3 和 Week 4
  set jsCode to "
(function() {
  // 找到并展开 \"Week 3\" 和 \"Week 4\" 
  var results = [];
  var allElements = document.querySelectorAll('*');
  for(var i = 0; i < allElements.length; i++) {
    var el = allElements[i];
    var txt = el.textContent.trim();
    if(txt === 'Week 3 多 Agent 协作' || txt === 'Week 4 产品上线') {
      el.click();
      results.push('clicked: ' + txt);
    }
  }
  
  // 等待展开后，提取所有课程项
  return new Promise(function(resolve) {
    setTimeout(function() {
      var items = [];
      var links = document.querySelectorAll('a');
      for(var j = 0; j < links.length; j++) {
        var a = links[j];
        var t = a.textContent.trim().replace(/\\s+/g, ' ');
        var h = a.getAttribute('href');
        if(t.length > 0 && t.length < 120 && h && h.indexOf('lesson') >= 0) {
          items.push(t + ' |->| ' + h);
        }
      }
      resolve(items.join('\\n'));
    }, 2000);
  });
})()
"
  try
    set lessonList to do JavaScript jsCode in current tab of window 1
    return lessonList
  on error errMsg
    return "JS_ERROR: " & errMsg
  end try
end tell
ASEOF

# 上面的 async/await 可能不行，改用同步方式
# 直接用 JavaScript 遍历 DOM 树
LESSONS_RAW=$(osascript -e "
tell application \"Safari\"
  try
    set jsCode to \"
(function() {
  var results = [];
  // 直接扫描所有包含 lesson id 的可点击元素
  var allEls = document.querySelectorAll('[class*=\\\"lesson\\\"], [class*=\\\"section\\\"], [class*=\\\"chapter\\\"], li, a');
  for(var i=0; i<allEls.length; i++) {
    var el = allEls[i];
    var txt = el.textContent.replace(/\\s+/g, ' ').trim();
    var href = el.getAttribute('href') || '';
    if(txt.length > 3 && txt.length < 200) {
      results.push(txt + ' #URL# ' + href);
    }
  }
  return results.slice(0, 100).join('\\n');
})()
\"
    return do JavaScript jsCode in current tab of window 1
  on error errMsg
    return \"JS_ERROR: \" & errMsg
  end try
end tell
" 2>/dev/null)

echo "$LESSONS_RAW" > "$EXTRACT_DIR/course_outline.txt"
echo "提取到 $(wc -l < "$EXTRACT_DIR/course_outline.txt") 行"

#######################################################
# Step 3: 点击每节课，提取实操任务详细描述
#######################################################
echo "Step 3: 逐课点击提取页面内容..."

# 从 outline 中提取课程链接
grep -i "lesson\|第.*课\|week\|Wk" "$EXTRACT_DIR/course_outline.txt" | grep -v "#URL# $" | head -30 > "$EXTRACT_DIR/lesson_list.txt"

COUNT=0
while IFS= read -r line; do
    TITLE=$(echo "$line" | sed 's/#URL#.*//' | xargs | sed 's/[^a-zA-Z0-9\u4e00-\u9fa5_-]/_/g' | head -c 60)
    [ -z "$TITLE" ] && continue
    COUNT=$((COUNT+1))
    echo "  [$COUNT] 点击: $TITLE"
    
    # 点击并等待加载
    LESSON_TEXT=$(osascript -e "
tell application \"Safari\"
  try
    -- 根据标题文本查找并点击
    set jsCode to \"
(function() {
  var target = '$line';
  var els = document.querySelectorAll('*');
  for(var i=0; i<els.length; i++) {
    if(els[i].textContent.trim().indexOf(target) >= 0 && els[i].tagName === 'LI' || els[i].tagName === 'A') {
      els[i].click();
      return 'clicked';
    }
  }
  return 'not found';
})()
\"
    do JavaScript jsCode in current tab of window 1
    delay 3
    return do JavaScript \"document.body.innerText\" in current tab of window 1
  on error errMsg
    return \"JS_ERROR: \" & errMsg
  end try
end tell
" 2>/dev/null)
    
    echo "$LESSON_TEXT" > "$EXTRACT_DIR/lesson_${COUNT}_${TITLE}.txt"
    echo "    保存 $(wc -c < "$EXTRACT_DIR/lesson_${COUNT}_${TITLE}.txt") 字节"
done < "$EXTRACT_DIR/lesson_list.txt"

echo "共提取 $COUNT 节课内容"

#######################################################
# Step 4: 分析所有提取内容，生成缺漏报告
#######################################################
echo "Step 4: 生成缺漏报告..."

python3 - "$EXTRACT_DIR" "$PROJECT_DIR" <<'PYEOF'
import os, sys, re, json
from pathlib import Path

extract_dir = sys.argv[1]
project_dir = sys.argv[2]

# ── 课程提取内容解析 ──
lessons_found = {}
tasks_found = {}

lesson_files = sorted(Path(extract_dir).glob("lesson_*.txt"))
for f in lesson_files:
    name = f.stem.replace("lesson_", "").split("_")[0]
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            text = fh.read()
    except:
        text = ""
    
    # 搜索任务关键词
    task_keywords = ['实操', '任务', '作业', '实验', '练习', '动手', '操作步骤', '产出要求', '课后', '提交']
    
    task_blocks = []
    lines = text.split('\n')
    in_task = False
    current_block = []
    
    for line in lines:
        s = line.strip()
        if not s:
            if in_task and current_block:
                task_blocks.append(' '.join(current_block))
                current_block = []
            in_task = False
            continue
        if any(kw in s for kw in task_keywords):
            in_task = True
        if in_task:
            current_block.append(s)
    
    if current_block:
        task_blocks.append(' '.join(current_block))
    
    tasks_found[f"lesson_{name}"] = {
        "file": str(f),
        "size": len(text),
        "has_tasks": len(task_blocks) > 0,
        "task_count": len(task_blocks),
        "tasks": task_blocks[:5]  # 最多5个任务块
    }

# ── 本地产出状态 ──
local_status = {
    # Wk3
    "wk3_langgraph_script": os.path.exists(f"{project_dir}/Wk3/experiments/langgraph-pipeline/langgraph_experiment.py"),
    "wk3_experiment_report": os.path.exists(f"{project_dir}/Wk3/experiments/langgraph-pipeline/EXPERIMENT_REPORT.md"),
    "wk3_experiment_reflection": os.path.exists(f"{project_dir}/Wk3/experiments/langgraph-pipeline/EXPERIMENT_REFLECTION.md"),
    "wk3_results": os.path.exists(f"{project_dir}/Wk3/experiments/langgraph-pipeline/results/"),
    "wk3_blog7": os.path.exists("/Users/huangcheng/blogs/geekbang-study/blogs/harness-study/blog7_langgraph_stategraph_实验报告_2026-07-29.md"),
    
    # Wk4
    "wk4_dir_exists": os.path.exists(f"{project_dir}/Wk4"),
    "wk4_any_output": False,
}

if local_status["wk4_dir_exists"]:
    wk4_contents = list(Path(f"{project_dir}/Wk4").glob("**/*"))
    local_status["wk4_any_output"] = len(wk4_contents) > 0
    local_status["wk4_files"] = [str(p.relative_to(f"{project_dir}/Wk4")) for p in wk4_contents[:20]]

# ── 第2节 SDD 强化训练 ──
sdd_remaining = {
    "specs_coding_standards": os.path.exists(f"{project_dir}/specs/coding-standards.md"),
    "agents_md_coding_section": False,
    "grill_me_skill": False,
}

# 检查 AGENTS.md 是否有编码规范段
agents_md = Path(f"{project_dir}/AGENTS.md")
if agents_md.exists():
    with open(agents_md, 'r') as f:
        content = f.read()
    if '编码规范' in content or 'coding standard' in content.lower():
        sdd_remaining['agents_md_coding_section'] = True

# ── 生成报告 ──
report = []
report.append("# Harness 训练营 Wk3 & Wk4 实操任务/作业缺漏报告")
report.append(f"> 自动生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
report.append(f"> 提取页数：{len(lesson_files)} 节课")
report.append("")

# Wk3 课程状态
report.append("## Week 3 — 多 Agent 协作")
report.append("")
report.append("### 📺 课程视频：全部已学完 ✅")
report.append("")
report.append("### 📝 各课实操任务提取结果")
report.append("")

wk3_tasks_lessons = [k for k in tasks_found if int(k.replace("lesson_","")) <= 15]
for lesson in sorted(wk3_tasks_lessons, key=lambda x: int(x.replace("lesson_",""))):
    info = tasks_found[lesson]
    report.append(f"#### 课节 {lesson.replace('lesson_', '')}")
    if info["has_tasks"]:
        report.append(f"- 📋 发现 {info['task_count']} 个任务/作业描述")
        for t in info['tasks'][:3]:
            preview = t[:150].replace('\n', ' ')
            report.append(f"  - {preview}...")
    else:
        report.append(f"- ⚠️ 未提取到任务描述（页面{info['size']}字符，可能不含关键词或提取失败）")
    report.append("")

report.append("### 📂 本地产出对照")
report.append("")
report.append("| 产出项 | 状态 | 备注 |")
report.append("|--------|:----:|------|")
report.append(f"| LangGraph 实验脚本 | {'✅' if local_status['wk3_langgraph_script'] else '❌'} | Wk3/experiments/langgraph-pipeline/langgraph_experiment.py |")
report.append(f"| 实验报告 | {'✅' if local_status['wk3_experiment_report'] else '❌'} | EXPERIMENT_REPORT.md |")
report.append(f"| 深度心得 | {'✅' if local_status['wk3_experiment_reflection'] else '❌'} | EXPERIMENT_REFLECTION.md (深度模型撰写) |")
report.append(f"| 实验结果文章 | {'✅' if local_status['wk3_results'] else '❌'} | results/experiment_1~3_article.md |")
report.append(f"| 博客 blog7 | {'✅' if local_status['wk3_blog7'] else '❌'} | LangGraph StateGraph 实验报告 |")
report.append("")

# Wk4 课程状态
report.append("## Week 4 — 产品上线")
report.append("")
report.append("### 📺 课程视频：全部未学习 ❌")
report.append("")

wk4_tasks_lessons = [k for k in tasks_found if int(k.replace("lesson_","")) > 15]
for lesson in sorted(wk4_tasks_lessons, key=lambda x: int(x.replace("lesson_",""))):
    info = tasks_found[lesson]
    report.append(f"#### 课节 {lesson.replace('lesson_', '')}")
    if info["has_tasks"]:
        report.append(f"- 📋 发现 {info['task_count']} 个任务/作业描述")
        for t in info['tasks'][:3]:
            preview = t[:150].replace('\n', ' ')
            report.append(f"  - {preview}...")
    else:
        report.append(f"- ⚠️ 未提取到任务描述")
    report.append("")

report.append("### 📂 本地产出对照")
report.append("")
report.append("| 产出项 | 状态 | 备注 |")
report.append("|--------|:----:|------|")
report.append(f"| Wk4/ 目录 | {'✅ 存在' if local_status['wk4_dir_exists'] else '❌ 不存在'} | {f\"含 {len(local_status.get('wk4_files', []))} 个文件\" if local_status['wk4_any_output'] else '无文件'} |")
report.append(f"| 实验产出 | {'✅' if local_status['wk4_any_output'] else '❌'} | 全部需要从零开始 |")
report.append("")

# Wk2 遗留 SDD 训练
report.append("## ⚠️ 遗留任务（跨周）")
report.append("")
report.append("### 第 2 节 SDD 强化训练（未完成）")
report.append("")
report.append("| 任务 | 状态 |")
report.append("|------|:----:|")
report.append(f"| specs/coding-standards.md | {'✅' if sdd_remaining['specs_coding_standards'] else '❌ 不存在'} |")
report.append(f"| AGENTS.md ## 编码规范 段 | {'✅' if sdd_remaining['agents_md_coding_section'] else '❌ 缺失'} |")
report.append(f"| grill-me skill 安装 | {'✅' if sdd_remaining['grill_me_skill'] else '❌ 未安装'} |")
report.append("")

# 总结
report.append("## 📊 总结")
report.append("")
report.append("| 模块 | 视频学习 | 实验/作业产出 | 待做事项 |")
report.append("|------|:---:|:---:|-----|")
report.append("| Wk3 | ✅ 全部学完 | ✅ LangGraph 实验完成 | 对照课程逐课确认是否遗漏子任务 |")
report.append("| Wk4 | ❌ 5节全未学 | ❌ 零产出 | 全部待学+待做 |")
report.append("| Wk2 SDD | ✅ 已学 | ❌ 未完成 | 编码规范 + grill-me skill |")
report.append("")
report.append("### 🎯 建议优先级")
report.append("")
report.append("1. **Wk4 视频** — 5节全未学，需优先观看（了解整体内容）")
report.append("2. **Wk4 实验** — 从零开始搭建 Wk4 实验")
report.append("3. **Wk2 SDD 遗留** — 编码规范 + grill-me skill（一直拖着）")
report.append("4. **Wk3 逐课核对** — 确认每节课的实操任务是否完全覆盖")
report.append("")
report.append("### ⚠️ 注意事项")
report.append("")
report.append("- 极客时间训练营 API 不可用（u.geekbang.org），本报告通过 Safari AppleScript 提取页面文本，可能有遗漏")
report.append("- 如果课程页面在提取时未正确加载，任务描述会缺失——需手动对照视频/课件补充")
report.append("- V1/V2 管线从未通过真正的 OpenCode sub-agent 模式跑过（仅 Python 模拟），这是重大遗留问题")

report_content = '\n'.join(report)

report_path = f"{project_dir}/wk3_wk4_gap_report.md"
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(report_content)

print(f"✅ 报告已生成: {report_path}")
print(f"📏 报告长度: {len(report_content)} 字符")
print(f"📄 提取了 {len(tasks_found)} 节课的任务数据")

# 同时输出 JSON 摘要
summary = {
    "lessons_extracted": len(lesson_files),
    "lessons_with_tasks": sum(1 for v in tasks_found.values() if v["has_tasks"]),
    "total_tasks_found": sum(v["task_count"] for v in tasks_found.values()),
    "wk3_local_complete": all([local_status[k] for k in ["wk3_langgraph_script", "wk3_experiment_report", "wk3_experiment_reflection", "wk3_results"]]),
    "wk4_local_complete": local_status["wk4_any_output"],
    "sdd_remaining": sum(1 for v in sdd_remaining.values() if not v),
}

with open(f"{project_dir}/wk3_wk4_summary.json", 'w') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(f"\n📊 JSON 摘要: {project_dir}/wk3_wk4_summary.json")
PYEOF

#######################################################
# Step 5: Git 提交
#######################################################
echo ""
echo "Step 5: Git 提交..."

cd "$PROJECT_DIR"

git add wk3_wk4_gap_report.md wk3_wk4_summary.json extracted_course/ scripts/extract_course_tasks.sh 2>/dev/null || true

if git diff --cached --quiet; then
    echo "没有新变更"
else
    git commit -m "自动提取: Wk3/Wk4 实操任务缺漏报告 ($(date +%Y-%m-%d))"
    git push origin main
    echo "✅ 已推送到 GitHub: HC-Gamer/HarnessSSDStudy"
fi

echo ""
echo "=== $(date) 完成 ==="
echo "报告: $PROJECT_DIR/wk3_wk4_gap_report.md"
echo "日志: $LOG"
