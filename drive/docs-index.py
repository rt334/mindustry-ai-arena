#!/usr/bin/env python3
"""文档索引与按节读取 —— 让 agent **按需取一节**，而不是把 9000 行全读进上下文。

    python drive/docs-index.py                       列出全部文档与章节
    python drive/docs-index.py --json                输出 JSON（供 agent 解析）
    python drive/docs-index.py --read API.md         取整份
    python drive/docs-index.py --read "API.md#信息可见性契约"   只取那一节
    python drive/docs-index.py --grep 阻塞           跨文档按标题找节

为什么这么做（见 docs/TODO.md §九 #8）：这个仓库的 docs/ 已经 25 份 / 近 9000 行，
此前只能靠"读索引再整份打开"。参考项目 `hanhe-mint/-ai-rimworld-ai-teammate` 的
做法是 `reference_index` + `reference_read`（按需检索），这里给一个本地等价物。

设计取舍：只解析标题行（`#` / `##` / `###`）来切节，不引入 markdown 库 ——
这些文档是自己写的、标题格式统一，够用；少一个依赖。

另注：docs/ 是**维护者文档**（含实测出的游戏内情）。参赛 AI 不该读它 ——
真要给 agent 用，请只把它当检索工具，别把整份塞进参赛者的上下文。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
HEADING = re.compile(r"^(#{1,3})\s+(.*?)\s*$")


def parse_file(path: Path) -> dict:
    """切出文件的标题与各节（级别 / 标题 / 起始行 / 行数）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    title = ""
    marks = []  # (行号0基, 级别, 标题)
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m:
            continue
        level, text = len(m.group(1)), m.group(2)
        if level == 1 and not title:
            title = text
            continue
        if level >= 2:
            marks.append((i, level, text))

    sections = []
    for idx, (start, level, text) in enumerate(marks):
        end = len(lines)
        for nxt_start, nxt_level, _ in marks[idx + 1:]:
            if nxt_level <= level:
                end = nxt_start
                break
        sections.append({
            "level": level,
            "title": text,
            "start": start + 1,          # 对外用 1 基行号
            "lines": end - start,
        })
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "title": title,
        "lines": len(lines),
        "sections": sections,
    }


def collect() -> list[dict]:
    return [parse_file(p) for p in sorted(DOCS.rglob("*.md"))]


def cmd_list(files: list[dict]) -> None:
    total_sections = sum(len(f["sections"]) for f in files)
    print(f"docs/ —— {len(files)} 份文档，{sum(f['lines'] for f in files)} 行，"
          f"{total_sections} 个二级/三级标题")
    print("（维护者文档：含实测出的游戏内情，参赛 AI 不读）\n")
    for f in files:
        print(f"{f['path']}  —  {f['title']}  ({f['lines']} 行)")
        for s in f["sections"]:
            pad = "  " if s["level"] == 2 else "    "
            print(f"{pad}{s['title']}   [L{s['start']}, {s['lines']} 行]")


def find_section(files: list[dict], spec: str) -> tuple[dict, dict | None]:
    """解析 `file.md` 或 `file.md#节标题`（节标题支持子串匹配）。"""
    if "#" in spec:
        name, want = spec.split("#", 1)
    else:
        name, want = spec, None
    name = name.strip()
    hit = None
    for f in files:
        if f["path"].endswith(name) or f["path"] == f"docs/{name}":
            hit = f
            break
    if hit is None:
        cands = [f["path"] for f in files if name.lower() in f["path"].lower()]
        raise SystemExit(f"找不到文档：{name}" + (f"\n相近的：{cands}" if cands else ""))
    if want is None:
        return hit, None
    matches = [s for s in hit["sections"] if want in s["title"]]
    if not matches:
        raise SystemExit(f"{hit['path']} 里没有标题含「{want}」的节")
    return hit, matches[0]


def cmd_read(files: list[dict], spec: str) -> None:
    f, sec = find_section(files, spec)
    lines = (ROOT / f["path"]).read_text(encoding="utf-8").splitlines()
    if sec is None:
        body = lines
        label = f"{f['path']}（整份 {len(lines)} 行）"
    else:
        body = lines[sec["start"] - 1: sec["start"] - 1 + sec["lines"]]
        label = f"{f['path']}  § {sec['title']}（L{sec['start']}，{sec['lines']} 行）"
    print(f"===== {label} =====")
    for i, line in enumerate(body, sec["start"] if sec else 1):
        print(f"{i:5d}| {line}")


def cmd_grep(files: list[dict], needle: str) -> None:
    hits = 0
    for f in files:
        for s in f["sections"]:
            if needle.lower() in s["title"].lower():
                print(f"{f['path']}#{s['title']}   [L{s['start']}, {s['lines']} 行]")
                hits += 1
    if not hits:
        print(f"没有标题含「{needle}」的节")


def main() -> int:
    ap = argparse.ArgumentParser(description="docs/ 索引与按节读取")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--read", metavar="FILE[#SECTION]", help="读整份或某一节")
    ap.add_argument("--grep", metavar="TEXT", help="按标题跨文档搜索")
    args = ap.parse_args()

    if not DOCS.is_dir():
        print(f"docs/ 不存在：{DOCS}", file=sys.stderr)
        return 1
    files = collect()

    if args.json:
        print(json.dumps({"root": "docs", "files": files}, ensure_ascii=False, indent=1))
    elif args.read:
        cmd_read(files, args.read)
    elif args.grep:
        cmd_grep(files, args.grep)
    else:
        cmd_list(files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
