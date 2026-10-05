#!/usr/bin/env python3
"""用正则整行匹配插入（缩进捕获后原样带回去）。

**这是同一条教训第三次出现**：凭 Get-Content 的显示猜缩进，锚点必然对不上。
凡是往已有代码里插东西，一律用 `^(\\s*)` 整行匹配，不要手写缩进。
"""
import pathlib
import re
import sys

A = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Actor.java")

RE_ = re.compile(r'^(\s*)if \(resolvedConfig != null\) extra\.put\("config", describeConfig\(resolvedConfig\)\);$', re.M)

BODY = r'''\1// 实际生效的朝向 + 多格方块换回锚点后的坐标。
\1//
\1// 复盘把这条列为头号时间黑洞：同一个 rot、同样的参数，落点与输出方向
\1// 却不一样。根因是坐标系 —— 多格方块在引擎里按**左上角**定位，
\1// 而接口一律给**中心**（block.sizeOffset = -((size-1)/2)）。
\1// 与其让每个 AI 自己推这个偏移，不如把它换回来的结果直接给出。
\1extra.put("appliedRot", rotation);
\1extra.put("anchorX", x + (int) block.sizeOffset);
\1extra.put("anchorY", y + (int) block.sizeOffset);
\1extra.put("size", block.size);
\1if (resolvedConfig != null) extra.put("config", describeConfig(resolvedConfig));'''


def main():
    t = A.read_text(encoding="utf-8")
    hits = RE_.findall(t)
    if len(hits) != 1:
        print(f"  !! 整行命中 {len(hits)} 次（期望 1）")
        return 1
    A.write_text(RE_.sub(BODY, t, count=1), encoding="utf-8")
    print(f"  ✓ 已插入（缩进 {' '*len(hits[0])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
