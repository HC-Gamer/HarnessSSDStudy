"""mkshot.py — 把真实命令输出渲染成终端风格 PNG（第 16 节交付截图工具）。

为什么不用窗口截屏：本机以无头会话执行验收，`screencapture -l <windowid>` 拿不到
终端窗口；直接截全屏会把无关桌面内容一起带进交付物。因此改为「跑真命令 → 落原始
stdout → 渲染成终端样式图片」，图里每一行都是命令的真实输出，不做任何编造。

用法：
    python3 scripts/mkshot.py <manifest.json> <outdir>

manifest.json 结构：
    [{"file": "01-xxx.png", "title": "标题", "cmd": "跑过的命令", "txt": "输出文件路径"}]

依赖：Pillow（仅用于裁掉底部空白）、macOS 自带 qlmanage（HTML → PNG，走 WebKit，
中文与 emoji 字形都能正确落地）。
"""

from __future__ import annotations

import html as html_mod
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

# 渲染画布宽度（px）。qlmanage 输出正方形缩略图，高度后面按内容裁掉。
CANVAS = 1600
# 单张图最多保留的输出行数，超出部分中间截断并显式标注省略了多少行。
MAX_LINES = 46
BG = (29, 31, 33)  # #1d1f21，与 HTML body 背景一致，用于判定空白行

HTML_TMPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; padding: 0; background: #1d1f21; }}
  body {{ font-family: Menlo, "SF Mono", monospace; font-size: 13px; line-height: 1.45; }}
  .bar {{ background: #2b2f31; padding: 8px 14px; color: #c5c8c6; font-size: 13px;
          border-bottom: 1px solid #3a3f41; }}
  .dot {{ display: inline-block; width: 11px; height: 11px; border-radius: 50%;
          margin-right: 6px; vertical-align: middle; }}
  .r {{ background: #ff5f56; }} .y {{ background: #ffbd2e; }} .g {{ background: #27c93f; }}
  .title {{ margin-left: 10px; color: #e0e3e5; font-weight: 600; }}
  .body {{ padding: 12px 16px 18px; color: #c5c8c6; white-space: pre-wrap;
           word-break: break-word; }}
  .cmd {{ color: #b5bd68; }}
  .foot {{ padding: 0 16px 14px; color: #6c7378; font-size: 11px; }}
</style></head><body>
<div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
<span class="title">{title}</span></div>
<div class="body"><span class="cmd">$ {cmd}</span>
{out}</div>
<div class="foot">{foot}</div>
</body></html>
"""


def clip(text: str) -> str:
    """行数超限时保留头尾，中间标注省略行数（不静默截断）。"""
    lines = text.rstrip("\n").split("\n")
    if len(lines) <= MAX_LINES:
        return "\n".join(lines)
    head, tail = MAX_LINES * 2 // 3, MAX_LINES // 3
    omitted = len(lines) - head - tail
    return "\n".join(lines[:head] + [f"… 〔中间省略 {omitted} 行，完整输出见 docs/evidence/〕"] + lines[-tail:])


def render(item: dict, outdir: Path, foot: str) -> Path:
    """渲染一条 manifest 记录为 PNG，返回输出路径。"""
    raw = Path(item["txt"]).read_text(encoding="utf-8", errors="replace")
    page = HTML_TMPL.format(
        title=html_mod.escape(item["title"]),
        cmd=html_mod.escape(item["cmd"]),
        out=html_mod.escape(clip(raw)),
        foot=html_mod.escape(foot),
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        src = tmp_p / "shot.html"
        src.write_text(page, encoding="utf-8")
        subprocess.run(
            ["qlmanage", "-t", "-s", str(CANVAS), "-o", str(tmp_p), str(src)],
            check=True, capture_output=True,
        )
        produced = tmp_p / "shot.html.png"
        img = Image.open(produced).convert("RGB")
        # 自底向上找到最后一行有内容的像素，裁掉下方大片空白
        w, h = img.size
        px = img.load()
        last = h - 1
        while last > 0:
            if any(px[x, last] != BG for x in range(0, w, 3)):
                break
            last -= 1
        img = img.crop((0, 0, w, min(h, last + 24)))
        dest = outdir / item["file"]
        img.save(dest)
    return dest


def main() -> int:
    manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    outdir = Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    foot = subprocess.run(
        ["date", "+%Y-%m-%d %H:%M %Z"], capture_output=True, text=True, check=True
    ).stdout.strip()
    foot = f"Mac mini (Apple Silicon) · macOS · {foot} · ai-knowledge-base/v4-production"
    if not shutil.which("qlmanage"):
        print("需要 macOS 的 qlmanage", file=sys.stderr)
        return 2
    for item in manifest:
        dest = render(item, outdir, foot)
        print(f"  [OK] {dest.name}  ({dest.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
