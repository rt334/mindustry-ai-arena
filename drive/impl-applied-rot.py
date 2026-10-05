#!/usr/bin/env python3
"""条目 2 的剩余部分：/place 返回「实际生效的 rot」与多格方块的锚点。

复盘把这条列为**四份文档共同指认的头号时间黑洞**。现在 sendsTo 已经给了
「往哪几格推货」，剩下没给的是同一个 rot 为什么落点不同、方向也不同。

根因是坐标系：多格方块在引擎里按**左上角**定位，而接口一律给**中心**。
于是同一个 rot=2，2x2 与 1x1 的锚点差半格，输出格自然也不同 ——
从外面看就是「同样的参数，结果不一样」。

所以除了 appliedRot，还要把换回来的锚点一并给出，让 AI 不必自己推这个偏移。

这属于**纯增字段**（不改任何行为），风险低；但仍会进 §八 那份「只编译过」的账。
"""
import pathlib
import sys

A = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Actor.java")

ANCHOR = '          if (resolvedConfig != null) extra.put("config", describeConfig(resolvedConfig));'

NEW = '''          // 实际生效的朝向 + 多格方块换回锚点后的坐标。
          //
          // 复盘把这条列为头号时间黑洞：同一个 rot、同样的参数，落点与输出方向
          // 却不一样。根因是坐标系 —— 多格方块在引擎里按**左上角**定位，
          // 而接口一律给**中心**（block.sizeOffset = -((size-1)/2)）。
          // 与其让每个 AI 自己推这个偏移，不如把它换回来的结果直接给出。
          extra.put("appliedRot", rotation);
          extra.put("anchorX", x + (int) block.sizeOffset);
          extra.put("anchorY", y + (int) block.sizeOffset);
          extra.put("size", block.size);
          if (resolvedConfig != null) extra.put("config", describeConfig(resolvedConfig));'''


def main():
    t = A.read_text(encoding="utf-8")
    n = t.count(ANCHOR)
    if n != 1:
        print(f"  !! 锚点 {n} 次")
        return 1
    A.write_text(t.replace(ANCHOR, NEW, 1), encoding="utf-8")
    print("  ✓ Actor.place 返回体加 appliedRot / anchorX / anchorY / size")
    return 0


if __name__ == "__main__":
    sys.exit(main())
