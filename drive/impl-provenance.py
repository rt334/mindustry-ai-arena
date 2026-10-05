#!/usr/bin/env python3
"""§2.3 溯源命名：让对局记录带上接口版本号，并把命名约定写下来。

复盘说「bot 目录 `模型@工具#编号`，表格带 SHA-256；对局记录不带版本号」。
上一轮刚加了接口版本号，正好接上 —— 记录里带上它，「这局的成绩是哪个
接口测出来的」就不再是悬案。

只做记录侧（服务端能做的部分）：meta 头加 apiVersion。
bot 目录命名与 SHA-256 是 AI 客户端的约定，写进 DEVELOPING.md 即可。
"""
import pathlib
import sys

MOD = pathlib.Path(r"C:\dsh\ai-arena")
REC = MOD / "mod" / "src" / "aiarena" / "Recorder.java"
DEV = MOD / "docs" / "DEVELOPING.md"

REC_OLD = '              .put("version", 2)'
REC_NEW = ('              .put("version", 2)\n'
           '              // 接口版本：跨版本的成绩不可比，成绩与录像必须带得上它。\n'
           '              // 见 docs/API.md「接口版本号」。\n'
           '              .put("apiVersion", AIArena.API_VERSION)')

DEV_SECTION = """

---

## 溯源命名

**这是 AI 客户端侧的约定，服务端只负责把接口版本号写进录像。**

### bot 目录

```
模型@工具#编号
```

例：`claude@arena_ops#12`、`deepseek@acc4#03`。三段缺一不可 ——
换模型、换工具、换编号都会影响成绩，只写「claude」等于没写。

每个 bot 目录里放一份 `MANIFEST.json`：

```json
{"model": "claude-sonnet-4.5", "tool": "arena_ops",
 "number": 12, "sha256": "<脚本目录的哈希>", "apiVersion": "1.4"}
```

### 成绩表

成绩表必须带 `sha256` 与 `apiVersion` 两列：

- `sha256` —— 确认两批成绩跑的是同一份代码
- `apiVersion` —— 确认两件事：**接口没变**（变了字段语义就不可比），
  以及**记录里有什么字段**（老客户端跑出的成绩少了新字段的信息，
  与新版本的成绩不是同一批可比数据）

`apiVersion` 由 `GET /ping` 取（无鉴权），也写在录像的 `meta` 头里，
所以对不上的时候能直接查。

### 录像

`meta` 头带 `apiVersion`，与 `version`（录像格式版本）是两个东西：

| 字段 | 含义 | 谁改 |
|---|---|---|
| `version` | **录像格式**版本（现在是 2） | 改 JSONL 结构时 +1 |
| `apiVersion` | **接口**版本（现在是 1.4） | 改端点/字段时 +1 |

回放端只用 `version`；做成绩对比时才看 `apiVersion`。
"""


def main():
    ok = True

    t = REC.read_text(encoding="utf-8")
    n = t.count(REC_OLD)
    if n == 1:
        REC.write_text(t.replace(REC_OLD, REC_NEW, 1), encoding="utf-8")
        print("  ✓ Recorder meta 加 apiVersion")
    else:
        print(f"  !! Recorder 锚点 {n} 次")
        ok = False

    d = DEV.read_text(encoding="utf-8")
    if "## 溯源命名" in d:
        print("  · DEVELOPING.md 已有该节")
    else:
        DEV.write_text(d.rstrip() + DEV_SECTION, encoding="utf-8")
        print("  ✓ DEVELOPING.md 追加「溯源命名」")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
