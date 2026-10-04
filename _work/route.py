#!/usr/bin/env python3
"""布线工具：给定折线路径生成 conveyor 规格（每格朝向下一格）。"""
import sys

ROT = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}


def route(pts, block="conveyor"):
    """pts: [(x,y), ...] 折线（首尾相接）。返回 [(x,y,block,rot)]，最后一格不铺。"""
    cells = []
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        dx = (x1 > x0) - (x1 < x0)
        dy = (y1 > y0) - (y1 < y0)
        if dx and dy:
            raise ValueError(f"非正交段: {pts[i]} -> {pts[i+1]}")
        steps = max(abs(x1 - x0), abs(y1 - y0))
        for s in range(steps):
            cells.append((x0 + dx * s, y0 + dy * s))
    out = []
    for i, c in enumerate(cells):
        n = cells[i + 1] if i + 1 < len(cells) else pts[-1]
        d = (n[0] - c[0], n[1] - c[1])
        if d == (0, 0):
            continue
        out.append((c[0], c[1], block, ROT[d]))
    return out


if __name__ == "__main__":
    print(route([(61, 104), (61, 120), (40, 120)]))
