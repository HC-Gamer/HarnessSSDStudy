"""render_shots.py — 把 docs/evidence/ 的真实运行输出渲染成终端风格 PNG。

为什么不是窗口截屏：验收在无头会话里跑，`screencapture -l <windowid>` 拿不到终端
窗口，截全屏又会把无关桌面内容带进交付物。所以走「跑真命令 → 落原始 stdout →
渲染成终端样式图片」，图里每一行都是命令的真实输出，不编造。

与同目录 mkshot.py 的分工：mkshot.py 走 qlmanage(WebKit) 渲染 HTML，中文字形好但
依赖 macOS；本脚本纯 Pillow + 系统等宽字体，可控性更高（分页、行宽、配色都是显式
参数），是第 16 节交付截图的最终产线。

用法：
    python3 scripts/render_shots.py <evidence_dir> <outdir>

输出命名：单页 `01-pipeline-run.png`，多页 `01a-...png` / `01b-...png`（不静默截断）。
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# —— 画布与排版参数 ——
WIDTH = 1200          # 单张图宽度上限（px）
PAD_X, PAD_Y = 18, 14
FONT_SIZE = 12
LINE_H = 17
BAR_H = 34            # 顶部标题栏高度
MAX_LINES = 50        # 单页正文行数上限，超出自动翻页
WRAP_COLS = 148       # 超长行按此列宽软换行（12px Menlo ≈ 7.2px/字符）

# —— 配色（VS Code Dark+ 口径）——
BG = "#1e1e1e"
BAR_BG = "#2d2d2d"
BAR_LINE = "#3c3c3c"
FG = "#d4d4d4"
TITLE_FG = "#e8e8e8"
CMD_FG = "#9cdcfe"     # `$ 命令` 行
OK_FG = "#6a9955"      # 含 [OK]/passed/✅ 的行
ERR_FG = "#f48771"     # 含 [!!]/FAILED/Error 的行
DIM_FG = "#808080"     # 页脚与分页提示

# 主字体必须等宽（决定字符格宽），后面几个是中文/符号回退——Menlo 没有 CJK 字形，
# 直接用它渲染中文会满屏豆腐块。逐字符按覆盖情况选字体，见 pick_font()。
MONO_CANDIDATES = [
    ("/System/Library/Fonts/Menlo.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Courier New.ttf", 0),
]
FALLBACK_CANDIDATES = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),
]
TOFU_PROBE = "\ue000"  # 私用区码位，任何字体都没有字形 → 拿它的位图当「豆腐块」样本
# ✅ ⚠ 📚 这类 emoji 三只回退字体都没有。Apple Color Emoji 是位图字体，只接受固定
# 磅数，所以单独渲染成 RGBA 小图再缩放贴回去，不走 draw.text 主路径。
EMOJI_FONT_PATH = "/System/Library/Fonts/Apple Color Emoji.ttc"
EMOJI_RENDER_SIZE = 20

# 检查点标题：对应 16-1 Checklist / 各节交付物。命令取自 run.sh 与各模块的
# `if __name__ == "__main__"` 入口，均为真实可复跑的命令。
META: dict[str, tuple[str, str]] = {
    "01-pipeline-run":            ("检查点 01 · 采集管线端到端跑通（GitHub+RSS 40 条；LLM 401，规则降级 40 条）", "python3 -m pipeline.pipeline"),
    "02-langgraph-workflow-run":  ("检查点 02 · LangGraph 七节点工作流全流程（LLM 401，重试 3 次后降级链路生效）", "./run.sh run   # python3 -m workflows.graph"),
    "04-pytest-all-green":        ("检查点 04 · pytest 全绿（16-1 检查 7 测试通道）", "python3 -m pytest tests/"),
    "05-cost-guard-selftest":     ("检查点 05 · CostGuard 成本追踪自测", "python3 tests/cost_guard.py"),
    "06-security-three-defenses": ("检查点 06 · Security 三道防线（清洗 / 限流 / 脱敏）", "python3 tests/security.py"),
    "07-eval-test-report":        ("检查点 07 · Eval 评估报告", "python3 tests/eval_test.py"),
    "08-pattern-router":          ("检查点 08 · Router 三路分支 3/3 正确（2 条关键词零成本命中，1 条 LLM 401 后兜底）", "python3 -m patterns.router"),
    "09-router-unit-tests":       ("检查点 09 · Router 单元测试 18 项全过", "python3 -m pytest tests/test_router.py"),
    "10-pattern-planner":         ("检查点 10 · Planner 三档策略（lite / standard / full）", "python3 -m patterns.planner"),
    "11-reviewer-5dim":           ("检查点 11 · Reviewer 五维加权评分", "python3 -m workflows.reviewer"),
    "12-human-flag":              ("检查点 12 · HumanFlag 转人工闸门", "python3 -m workflows.human_flag"),
    "13-validate-schema-gate":    ("检查点 13 · 段间 schema 校验闸门（加分项）", "python3 validate.py"),
    "14-formatter-two-formats":   ("检查点 14 · Formatter 双格式输出（Markdown / Telegram）", "python3 -m distribution.formatter"),
    "15-publisher-dryrun":        ("检查点 15 · Publisher dry-run（无凭证不崩溃）", "python3 -m distribution.publisher"),
    "16-daily-digest-dryrun":     ("检查点 16 · 每日日报 dry-run", "python3 daily_digest.py"),
    "17-knowledge-bot-intent":    ("检查点 17 · KnowledgeBot 意图识别 6 例", "python3 -m bot.knowledge_bot"),
    "18-costguard-breaker":       ("检查点 18 · CostGuard 预算 ¥0.001 整链路（本次 0 计费调用，熔断判定实证见 05）", "./run.sh breaker   # BUDGET_YUAN=0.001"),
    "19-env-keys-permissions":    ("检查点 19 · 上线 Checklist 1：API Keys 与 .env 权限", ""),
    "20-skills-least-privilege":  ("检查点 20 · 上线 Checklist 2：Skill 最小权限", ""),
    "21-requirements-pinned":     ("检查点 21 · 上线 Checklist 6：依赖版本全部钉死", ""),
    "22-knowledge-store-stats":   ("检查点 22 · 上线 Checklist 3：知识库产出与备份", ""),
    "23-openclaw-model-live":     ("检查点 23 · 上线 Checklist 9：OpenClaw 网关与模型实调", ""),
    "24-dingtalk-bridge-live":    ("检查点 24 · 钉钉 Bot 桥接实跑（Telegram 的国内替代通道）", ""),
}

FOOT = "ai-knowledge-base / v4-production · macOS (Apple Silicon) · 原始输出见 docs/evidence/"


class FontChain:
    """一条「等宽主字体 + 中文/符号回退」的字体链，按字符逐个挑能画出字形的那只。

    覆盖判定不靠码位表（本机没有 fontTools），而是拿私用区码位 U+E000 在该字体下的
    位图当「豆腐块」样本：某字符渲染结果与豆腐块一致，就认为这只字体没有它的字形，
    继续往后回退。结果做缓存，一张图几千个字符也只判几十次。
    """

    def __init__(self, size: int) -> None:
        self.fonts: list[ImageFont.FreeTypeFont] = []
        for path, index in MONO_CANDIDATES:
            if Path(path).exists():
                try:
                    self.fonts.append(ImageFont.truetype(path, size, index=index))
                    break
                except OSError:
                    continue
        if not self.fonts:
            raise SystemExit(f"[!!] 没有可用的等宽字体，试过：{[p for p, _ in MONO_CANDIDATES]}")
        # 回退字体放大到约两个字符格宽，让 CJK 视觉大小与终端里的全角字一致
        for path, index in FALLBACK_CANDIDATES:
            if Path(path).exists():
                try:
                    self.fonts.append(ImageFont.truetype(path, size + 2, index=index))
                except OSError:
                    continue
        self.emoji: ImageFont.FreeTypeFont | None = None
        if Path(EMOJI_FONT_PATH).exists():
            try:
                self.emoji = ImageFont.truetype(EMOJI_FONT_PATH, EMOJI_RENDER_SIZE)
            except OSError:
                self.emoji = None
        self.cell = self.fonts[0].getlength("M")  # 单字符格宽（px）
        self._probe_box = (size * 3, size * 3)
        self._tofu = {id(f): self._glyph(f, TOFU_PROBE) for f in self.fonts}
        self._cache: dict[str, ImageFont.FreeTypeFont] = {}

    def _glyph(self, font: ImageFont.FreeTypeFont, ch: str) -> bytes:
        """把单个字符画到灰度小图上取原始字节——ImagingCore 不支持直接取字节。"""
        probe = Image.new("L", self._probe_box, 0)
        ImageDraw.Draw(probe).text((2, 2), ch, font=font, fill=255)
        return probe.tobytes()

    def pick(self, ch: str) -> ImageFont.FreeTypeFont | None:
        """返回覆盖该字符的字体；返回 None 表示这些字体都没有它、应走 emoji 路径。"""
        if ch in self._cache:
            return self._cache[ch]
        chosen: ImageFont.FreeTypeFont | None = None
        for font in self.fonts:
            try:
                bitmap = self._glyph(font, ch)
            except OSError:
                continue
            # 空白（如空格）和豆腐块都不算「有字形」，前者留给调用方按格跳过
            if bitmap != self._tofu[id(font)] and any(bitmap):
                chosen = font
                break
        self._cache[ch] = chosen
        return chosen

    def paste_emoji(self, img: Image.Image, ch: str, x: float, y: float) -> bool:
        """把 emoji 渲染成 RGBA 小图缩到两格宽再贴上去；字体不可用或没这个字形返回 False。"""
        if self.emoji is None:
            return False
        box = EMOJI_RENDER_SIZE * 2
        tile = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        try:
            ImageDraw.Draw(tile).text((0, 0), ch, font=self.emoji, embedded_color=True)
        except (OSError, ValueError):
            return False
        bbox = tile.getbbox()
        if bbox is None:
            return False
        target = int(self.cell * 2)
        tile = tile.crop(bbox).resize((target, target), Image.LANCZOS)
        img.paste(tile, (int(x), int(y)), tile)
        return True


def line_color(text: str) -> str:
    """按行内容上色，让「通过 / 失败」在截图里一眼可辨。"""
    stripped = text.lstrip()
    if stripped.startswith("$ ") or stripped.startswith("### "):
        return CMD_FG
    if any(k in text for k in ("[!!]", "FAILED", "Traceback", "错误", "失败")):
        return ERR_FG
    if any(k in text for k in ("[OK]", "passed", "✅", "成功", "PASS")):
        return OK_FG
    return FG


def cell_width(ch: str) -> int:
    """字符占几个终端字符格：CJK / emoji 占 2，变体选择符等零宽字符占 0，其余占 1。"""
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F000:
        return 2
    return 1


def wrap_lines(raw: str) -> list[str]:
    """把原始输出按显示列宽软换行；空行保留，制表符按 4 空格展开。

    按显示宽度而非字符数换行——一行 148 个汉字实际占 296 列，按字符数算会溢出画布。
    """
    out: list[str] = []
    for line in raw.expandtabs(4).rstrip("\n").split("\n"):
        cur, width = "", 0
        for ch in line:
            w = cell_width(ch)
            if width + w > WRAP_COLS:
                out.append(cur)
                cur, width = "", 0
            cur += ch
            width += w
        out.append(cur)
    return out


def paginate(lines: list[str]) -> list[list[str]]:
    return [lines[i:i + MAX_LINES] for i in range(0, len(lines), MAX_LINES)] or [[""]]


def draw_line(img: Image.Image, d: ImageDraw.ImageDraw, x: float, y: float,
              text: str, chain: FontChain, fill: str) -> None:
    """按字符格逐字绘制：ASCII 走等宽主字体，中文/符号回落到覆盖它的那只字体。

    不用一次性 d.text(整行)，因为一行里混着好几种字体，只有按格推进才能保住列对齐
    （pytest 的进度条、check 脚本的 [OK] 列都靠它）。
    """
    for ch in text:
        if not ch.isspace():
            font = chain.pick(ch)
            if font is None:
                # 三只文字字体都没有 → 当 emoji 贴图；再不行就留空，不画豆腐块
                chain.paste_emoji(img, ch, x, y - 1)
            else:
                # 回退字体比主字体大 2px，垂直方向往上提一点让基线对齐
                d.text((x, y + (0 if font is chain.fonts[0] else -2)), ch, font=font, fill=fill)
        x += chain.cell * cell_width(ch)


def render_page(lines: list[str], title: str, cmd: str, dest: Path,
                body: FontChain, title_chain: FontChain) -> None:
    header = ([f"$ {cmd}"] if cmd else []) + lines
    height = BAR_H + PAD_Y * 2 + LINE_H * len(header) + 20
    img = Image.new("RGB", (WIDTH, height), BG)
    d = ImageDraw.Draw(img)

    # 标题栏：三个圆点 + 检查点名，模拟终端窗口
    d.rectangle([0, 0, WIDTH, BAR_H], fill=BAR_BG)
    d.line([0, BAR_H, WIDTH, BAR_H], fill=BAR_LINE)
    for i, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        cx = 16 + i * 18
        d.ellipse([cx, BAR_H // 2 - 5, cx + 10, BAR_H // 2 + 5], fill=color)
    draw_line(img, d,78, BAR_H // 2 - 8, title, title_chain, TITLE_FG)

    y = BAR_H + PAD_Y
    for line in header:
        draw_line(img, d,PAD_X, y, line, body, line_color(line))
        y += LINE_H
    draw_line(img, d,PAD_X, y + 4, FOOT, body, DIM_FG)
    img.save(dest)


def main() -> int:
    evidence_dir, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    body, title_chain = FontChain(FONT_SIZE), FontChain(FONT_SIZE + 1)

    made, failed = [], []
    for txt in sorted(evidence_dir.glob("*.txt")):
        stem = txt.stem
        title, cmd = META.get(stem, (stem, ""))
        try:
            pages = paginate(wrap_lines(txt.read_text(encoding="utf-8", errors="replace")))
            for idx, page in enumerate(pages):
                if len(pages) > 1:
                    # 01-pipeline-run → 01a-pipeline-run / 01b-...；页码写进标题栏
                    num, rest = stem.split("-", 1)
                    name = f"{num}{chr(ord('a') + idx)}-{rest}.png"
                    page_title = f"{title}  〔{idx + 1}/{len(pages)}〕"
                else:
                    name, page_title = f"{stem}.png", title
                dest = outdir / name
                render_page(page, page_title, cmd if idx == 0 else "", dest, body, title_chain)
                made.append(dest)
        except Exception as exc:  # 单张失败不拖垮整批，明确报出是哪张
            failed.append((txt.name, repr(exc)))

    for dest in made:
        print(f"  [OK] {dest.name:<34} {dest.stat().st_size // 1024:>4} KB")
    for name, err in failed:
        print(f"  [!!] {name}: {err}")
    print(f"\n共 {len(made)} 张，失败 {len(failed)} 张")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
