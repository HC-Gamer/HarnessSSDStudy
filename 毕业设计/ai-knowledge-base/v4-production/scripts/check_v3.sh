#!/bin/bash
# V3 完整性检查 —— 课件 12-4 步骤 6 / 7 / 9 三张清单的可执行版本。
#
#   bash scripts/check_v3.sh
#
# 只做静态检查（文件存在 / 接入点 grep / 字段数），不花一分钱 token。
# 需要花钱的验收（端到端、熔断、三路分支）见 M1_COMPLETION.md 的实测记录。
set -uo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-$HOME/ai-knowledge-base/.venv/bin/python}"
FAILED=0

pass() { echo "  [OK] $1"; }
fail() { echo "  [!!] $1"; FAILED=$((FAILED + 1)); }

check_file() { [ -f "$1" ] && pass "$1" || fail "$1 (缺失)"; }

echo "=== V3 完整性检查 ==="

echo ""
echo "--- V1 基础 ---"
for f in AGENTS.md .opencode/agents/collector.md .opencode/agents/analyzer.md \
         .opencode/agents/organizer.md; do
    check_file "$f"
done
SKILL_COUNT=$(find .opencode/skills -name "SKILL.md" 2>/dev/null | wc -l | tr -d ' ')
[ "$SKILL_COUNT" -ge 2 ] && pass ".opencode/skills/ 有 $SKILL_COUNT 个 Skill (>=2)" \
                         || fail ".opencode/skills/ 只有 $SKILL_COUNT 个 Skill (需 >=2)"

echo ""
echo "--- V2 自动化 ---"
for f in pipeline/model_client.py pipeline/pipeline.py hooks/validate_json.py \
         hooks/check_quality.py .github/workflows/daily-collect.yml; do
    check_file "$f"
done

echo ""
echo "--- V3 多 Agent（12-4 步骤 7 的 14 个文件）---"
for f in patterns/router.py workflows/state.py workflows/planner.py \
         workflows/collector.py workflows/analyzer.py workflows/reviewer.py \
         workflows/reviser.py workflows/organizer.py workflows/human_flag.py \
         workflows/graph.py workflows/model_client.py \
         tests/cost_guard.py tests/security.py tests/eval_test.py; do
    check_file "$f"
done

echo ""
echo "--- V3 补充（脚本未列但课件/V4 会查）---"
for f in patterns/supervisor.py patterns/planner.py workflows/nodes.py \
         validate.py pytest.ini requirements.txt .env.example run.sh; do
    check_file "$f"
done
for d in knowledge/raw knowledge/articles knowledge/pending_review; do
    [ -d "$d" ] && pass "$d/" || fail "$d/ (缺失)"
done

echo ""
echo "--- 12-4 步骤 6：接入清单 ---"
grep -q "guard.record(" workflows/model_client.py \
    && pass "model_client.chat 调完自动 record" \
    || fail "model_client.chat 没有 record"
grep -q "guard.check()" workflows/model_client.py \
    && pass "model_client.chat 调完自动 check" \
    || fail "model_client.chat 没有 check"
grep -q "sanitize_input" workflows/collector.py \
    && pass "collect_node 入口调 sanitize_input" \
    || fail "collect_node 没接 sanitize_input"
grep -q "filter_output" workflows/organizer.py \
    && pass "organize_node 出口调 filter_output" \
    || fail "organize_node 没接 filter_output"
grep -q "cost_by_node" workflows/graph.py \
    && pass "工作流跑完打印按节点分组的成本报告" \
    || fail "graph 没打按节点成本"
grep -q "save_report" workflows/graph.py \
    && pass "graph 收尾写 knowledge/cost-report.json" \
    || fail "graph 没写 cost-report.json"
WIRED=$(grep -l "cost_guard\|sanitize_input\|filter_output" workflows/*.py | wc -l | tr -d ' ')
[ "$WIRED" -ge 3 ] && pass "grep 接入点命中 $WIRED 个 workflows 文件（非空）" \
                   || fail "接入点 grep 只命中 $WIRED 个文件"
grep -q "node_name=NODE_NAME" workflows/analyzer.py \
    && pass "节点透传 node_name（成本可按节点归因）" \
    || fail "节点没透传 node_name"

echo ""
echo "--- 关键契约 ---"
if [ -x "$PYTHON" ]; then
    FIELDS=$("$PYTHON" -c "from workflows.state import KBState; print(len(KBState.__annotations__))" 2>/dev/null)
    [ "$FIELDS" = "9" ] && pass "KBState 字段数 = 9" || fail "KBState 字段数 = ${FIELDS:-读取失败}（应为 9）"

    NODES=$("$PYTHON" -c "from workflows.graph import build_graph; print(len(build_graph().nodes))" 2>/dev/null)
    [ "$NODES" = "7" ] && pass "工作流节点数 = 7" || fail "工作流节点数 = ${NODES:-读取失败}（应为 7）"
else
    fail "找不到 venv Python ($PYTHON)，跳过运行时契约检查"
fi

echo ""
echo "--- 安全卫生 ---"
grep -q "^\.env$" .gitignore && pass ".gitignore 忽略 .env" || fail ".gitignore 没忽略 .env"
if grep -rlE "sk-[a-zA-Z0-9]{20,}" --include="*.py" --include="*.md" --include="*.yml" \
        --exclude=".env*" . 2>/dev/null | grep -q .; then
    fail "源码里疑似出现明文 API Key"
else
    pass "源码中无明文 API Key"
fi

echo ""
echo "=========================================="
if [ "$FAILED" -eq 0 ]; then
    echo "V3 完整性检查全部通过"
else
    echo "V3 完整性检查有 $FAILED 项未通过"
fi
echo "=========================================="
exit $((FAILED > 0))
