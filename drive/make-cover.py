#!/usr/bin/env python3
"""生成 AI 竞技场封面（第二版）。

第一版的问题：地图只占左边一块，大片空地板；传送带暗到看不见；图例和地图重叠。
参考图的封面画面是铺满的 —— 这版把地图铺满全幅，右侧压一层深色渐变放文字。

用 bundled python 跑（系统 python 没装 Pillow）。
"""
import math
import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
OUT = r"C:\dsh\ai-arena\docs\images\cover.png"
FONT_BD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_RG = r"C:\Windows\Fonts\msyh.ttc"

TILE_A, TILE_B = (30, 42, 56), (24, 34, 45)
ORE = {
    "copper": (216, 138, 66),
    "lead": (146, 132, 182),
    "coal": (108, 108, 126),
    "titanium": (86, 186, 204),
}
CORE_OUT, CORE_IN = (206, 180, 110), (162, 138, 78)
BELT = (92, 122, 146)
DRILL = (168, 170, 180)
YELLOW = (255, 216, 77)
WHITE = (255, 255, 255)

CELL = 26
COLS, ROWS = W // CELL + 2, H // CELL + 2


def font(path, size):
    return ImageFont.truetype(path, size)


def draw_world(d, seed=11):
    """铺满全幅的像素地图。"""
    rnd = random.Random(seed)

    for r in range(ROWS):
        for c in range(COLS):
            x, y = c * CELL, r * CELL
            d.rectangle([x, y, x + CELL - 1, y + CELL - 1],
                        fill=TILE_A if (r + c) % 2 == 0 else TILE_B)

    def vein(name, cx, cy, n, spread, ragged=0.55):
        col = ORE[name]
        lit = tuple(min(255, v + 30) for v in col)
        for _ in range(n):
            a = rnd.uniform(0, math.tau)
            rr = rnd.uniform(0, spread)
            c = int(cx + math.cos(a) * rr)
            r = int(cy + math.sin(a) * rr * ragged)
            if not (0 <= c < COLS and 0 <= r < ROWS):
                continue
            x, y = c * CELL, r * CELL
            d.rectangle([x + 2, y + 2, x + CELL - 3, y + CELL - 3], fill=col)
            d.rectangle([x + 4, y + 4, x + CELL // 2 + 2, y + CELL // 2 + 2], fill=lit)

    # 更密、更成片的矿脉
    for name, cx, cy, n, sp in [
        ("copper", 7.5, 6.5, 40, 3.4),
        ("copper", 3.0, 15.0, 26, 2.6),
        ("copper", 33.0, 9.0, 30, 3.0),
        ("lead", 13.0, 20.0, 30, 2.9),
        ("lead", 35.5, 21.5, 24, 2.6),
        ("coal", 24.0, 4.0, 26, 2.8),
        ("coal", 30.0, 15.5, 20, 2.4),
        ("titanium", 18.5, 12.0, 22, 2.4),
        ("titanium", 39.0, 5.0, 20, 2.5),
        ("titanium", 10.0, 23.5, 18, 2.2),
    ]:
        vein(name, cx, cy, n, sp)

    def belt(pts):
        for i in range(len(pts) - 1):
            (c0, r0), (c1, r1) = pts[i], pts[i + 1]
            steps = max(abs(c1 - c0), abs(r1 - r0))
            for s in range(steps + 1):
                t = s / max(1, steps)
                c = int(round(c0 + (c1 - c0) * t))
                r = int(round(r0 + (r1 - r0) * t))
                x, y = c * CELL, r * CELL
                d.rectangle([x + 2, y + CELL // 2 - 5, x + CELL - 3, y + CELL // 2 + 4],
                            fill=BELT)
                d.rectangle([x + 2, y + CELL // 2 - 5, x + CELL - 3, y + CELL // 2 - 3],
                            fill=tuple(min(255, v + 36) for v in BELT))

    # 核心（5x5），放偏左中，别占画面中心
    cc, cr = 9, 12
    cx, cy = cc * CELL, cr * CELL
    d.rectangle([cx - 3, cy - 3, cx + CELL * 5 + 2, cy + CELL * 5 + 2], fill=(16, 24, 32))
    d.rectangle([cx, cy, cx + CELL * 5 - 1, cy + CELL * 5 - 1], fill=CORE_OUT)
    d.rectangle([cx + CELL, cy + CELL, cx + CELL * 4 - 1, cy + CELL * 4 - 1], fill=CORE_IN)
    d.rectangle([cx + CELL * 2, cy + CELL * 2, cx + CELL * 3 - 1, cy + CELL * 3 - 1],
                fill=tuple(min(255, v + 40) for v in CORE_OUT))

    belt([(6, 7), (6, 12), (8, 12)])
    belt([(3, 16), (3, 14), (8, 14)])
    belt([(11, 20), (11, 15), (10, 15)])
    belt([(18, 13), (18, 12), (14, 12)])

    for dc, dr in ((5, 6), (2, 15), (17, 11), (10, 19), (27, 2), (33, 8)):
        x, y = dc * CELL, dr * CELL
        # 别挡住右侧文字的眉标位置
        if 520 < x < 900 and y < 190:
            continue
        d.rectangle([x + 2, y + 2, x + CELL * 2 - 3, y + CELL * 2 - 3], fill=DRILL)
        d.ellipse([x + CELL // 2 + 2, y + CELL // 2 + 2,
                   x + CELL + CELL // 2 - 2, y + CELL + CELL // 2 - 2],
                  fill=(74, 76, 86))


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    img = Image.new("RGB", (W, H), (10, 16, 22))
    d = ImageDraw.Draw(img)
    draw_world(d)

    # ---- 右侧压深色渐变，给文字留底 ----
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for x in range(W):
        t = max(0.0, min(1.0, (x - 396) / 470.0))
        v = int(255 * (t ** 1.1) * 0.97)
        md.line([(x, 0), (x, H)], fill=v)
    dark = Image.new("RGB", (W, H), (7, 11, 17))
    img = Image.composite(dark, img, mask)

    # 左下角也压一点，让图例读得清
    mask2 = Image.new("L", (W, H), 0)
    m2 = ImageDraw.Draw(mask2)
    for y in range(H):
        t = max(0.0, min(1.0, (y - 600) / 120.0))
        m2.line([(0, y), (420, y)], fill=int(255 * t * 0.8))
    img = Image.composite(Image.new("RGB", (W, H), (7, 11, 17)), img, mask2)

    d = ImageDraw.Draw(img)

    f_eyebrow = font(FONT_RG, 25)
    f_title = font(FONT_BD, 98)
    f_sub = font(FONT_BD, 42)
    f_q = font(FONT_BD, 44)
    f_small = font(FONT_RG, 24)
    f_tag = font(FONT_BD, 26)

    tx = 566

    d.text((tx, 118), "MINDUSTRY  ·  AI 竞技场", font=f_eyebrow, fill=(126, 158, 186))

    def big(text, xy, fnt, fill=YELLOW, stroke=6, shadow=9):
        x, y = xy
        d.text((x + shadow, y + shadow), text, font=fnt, fill=(0, 0, 0),
               stroke_width=stroke, stroke_fill=(0, 0, 0))
        d.text((x, y), text, font=fnt, fill=fill,
               stroke_width=stroke, stroke_fill=WHITE)

    big("4 个 AI", (tx, 172), f_title)
    big("抢造产线", (tx, 292), f_title)

    d.text((tx + 3, 424), "同一张图 · 同一个起点", font=f_sub, fill=(226, 234, 244))
    big("谁先把核心堆满？", (tx + 3, 496), f_q, stroke=5, shadow=7)

    tag = "实机对战 · HTTP 接口"
    tw = d.textlength(tag, font=f_tag)
    d.rounded_rectangle([W - tw - 66, 38, W - 32, 90], radius=10, fill=(30, 44, 62))
    d.text((W - tw - 49, 48), tag, font=f_tag, fill=(146, 198, 240))

    lx, ly = 34, H - 52
    for i, (label, col) in enumerate((("铜", ORE["copper"]), ("铅", ORE["lead"]),
                                      ("煤", (150, 150, 168)), ("钛", ORE["titanium"]),
                                      ("硅", (192, 192, 204)))):
        d.text((lx + i * 46, ly), label, font=f_small, fill=col)
    d.text((lx + 248, ly), "5 种资源 · 4 条产线", font=f_small, fill=(104, 128, 152))

    img.save(OUT, "PNG")
    print(f"已生成 {OUT}  {img.size[0]}x{img.size[1]}  {os.path.getsize(OUT)//1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
