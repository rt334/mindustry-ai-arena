#!/usr/bin/env python3
"""更新 Recorder.java 顶部的格式说明 —— 补上地图、rot、removed。"""
import pathlib
import sys

R = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Recorder.java")

OLD = """ * 记录类型：
 *   {"t":"meta", ...}                                    开局元数据（地图/尺寸/队伍/规则）
 *   {"t":"snap","tick":N,"units":[...],"builds":[...]}   周期快照（单位全量 + 方块增量）
 *   {"t":"ev", ...}                                      事件（来自 EventLog）
 *   {"t":"end", ...}                                     结束标记
 *
 * 方块只存增量（首次全量 + 后续变化），因为地图上多数方块长期不变。"""

NEW = """ * 记录类型：
 *   {"t":"meta", ...}    开局元数据：地图名/尺寸/队伍/规则 + **mapData（整张地图）**
 *   {"t":"snap", ...}    周期快照：units 全量、builds 增量、removed 本帧消失的方块
 *   {"t":"ev", ...}      事件（来自 EventLog）
 *   {"t":"end", ...}     结束标记
 *
 * 快照三条流的语义**不同**，别混：
 *   units    每帧全量 —— 单位少（几十个），全量比增量简单且不会漏
 *   builds   增量 —— 首次全量，之后只写「新增或变化的」
 *   removed  增量 —— 本帧消失的方块坐标。**必须单独报**：
 *            builds 只写出现的，拆掉的方块从集合里消失后不会出现在任何记录里，
 *            回放端会一直画着它
 *
 * mapData 也用一维 RLE（行优先展开，[名称, 段长, ...]，null 表示该段什么都没有）。
 * 实测 veins 图 350x200 = 70000 格：逐格写是 1.38 MB，RLE 后约 230 KB ——
 * 而整局录像才 300 KB，所以这一步不是可选的优化，是不做就没法用。
 * 地板细碎（11643 段），矿脉和岩壁成片（分别 2974 / 6770 段）。"""


def main():
    text = R.read_text(encoding="utf-8")
    n = text.count(OLD)
    if n != 1:
        print(f"!! {n} 次命中（应为 1），未写盘")
        return 1
    R.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("Recorder.java：格式说明已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
