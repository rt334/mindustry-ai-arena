#!/usr/bin/env python3
"""修验证中暴露的三个接口缺陷。

来源是 drive/verify-debt-1.py 那轮实测：

  1. 批量的接受数只藏在 message 的散文里。
     响应结构里的 tiles 是 **请求数**（HttpApi.java:526 用的 pp.points.size），
     而 placeBatch 在累计到 MAX_PLANS_PER_UNIT=60 时会**静默 break**。
     实测：70 格批量返回 ok、tiles=70，实际只接受 60。
     AI 读 tiles 会以为 70 条都排上了。
     → 让 placeBatch/breakBatch 用 Actor.Result.extra 带出结构化计数。

  2. /queue?clear=true 的清除条数只出现在 message 里。
     实测清掉了 60 条，但响应里只有 {"message":"cleared 60 pending plan(s)"}，
     没有可读字段。我自己的验证脚本就读错了，以为「仍是 0」。
     → clearQueue 带出 cleared 字段。

  3. 客户端把持续 429 报成 -1。
     arena.py 会退避重试 429，但重试耗尽后统一抛
     ArenaError(-1, "unreachable after retries")。调用方看到 -1 会以为是网络
     不通，而真正该做的是降频。实测我自己的验证脚本就被这个误导过。
     → 最后一次是 429 时如实抛 1429。
"""
import pathlib
import sys

OPS = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Operations.java")
API = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")
CLI = pathlib.Path(r"C:\dsh\ai-arena\skill\scripts\arena.py")

# ── Operations.java ────────────────────────────────────────────────────
OPS_HELPER_ANCHOR = "    /** 清空队伍所有建造单位的待办计划。 */"
OPS_HELPER = """    /**
     * 批量的结构化结果。
     *
     * message 里那串「requested=N accepted=M skipped[...]」是给人看的散文；
     * 这里给出同义字段供程序读。**必须有** —— 否则响应里的 tiles（请求数）
     * 会被读成「这么多条都排上了」，而超过 MAX_PLANS_PER_UNIT 的部分
     * 是**静默丢弃**的：实测 70 格批量返回 ok、tiles=70，实际只接受了 60。
     */
    private static Json.Obj summaryJson(BatchResult r) {
        return new Json.Obj()
            .put("requested", r.requested)
            .put("accepted", r.accepted)
            .putRaw("skipped", new Json.Obj()
                .put("invalid", r.skippedInvalid)
                .put("invisible", r.skippedInvisible)
                .put("noUnit", r.skippedNoUnit)
                .toString())
            .put("limitReached", r.accepted >= MAX_PLANS_PER_UNIT)
            .put("plansPerUnit", MAX_PLANS_PER_UNIT);
    }

    /** 清空队伍所有建造单位的待办计划。 */"""

OPS_ERR_OLD = '        return Actor.Result.err(1005, "batch rejected: " + r.summary() + " — " + why);'
OPS_ERR_NEW = ('        return Actor.Result.err(1005, "batch rejected: " + r.summary() + " — " + why,\n'
               '                                   summaryJson(r));')

OPS_OK_OLD = '        return Actor.Result.ok("batch " + r.summary());'
OPS_OK_NEW = '        return Actor.Result.ok("batch " + r.summary(), summaryJson(r));'

OPS_CLEAR_OLD = '        return Actor.Result.ok("cleared " + n + " pending plan(s)");'
OPS_CLEAR_NEW = ('        return Actor.Result.ok("cleared " + n + " pending plan(s)",\n'
                 '                               new Json.Obj().put("cleared", n));')

# ── HttpApi.java ───────────────────────────────────────────────────────
API_PATH_OLD = """                Actor.Result r = Operations.placeBatch(team, pp.points, pp.rotations,
                                                       block, rot, config);
                if (!r.ok) return Json.error(r.code, r.message);
                return Json.ok(new Json.Obj()
                    .put("shape", "path")
                    .put("tiles", pp.points.size)
                    .putRaw("rotations", rotationsJson(pp))
                    .put("message", r.message)
                    .toString());"""

API_PATH_NEW = """                Actor.Result r = Operations.placeBatch(team, pp.points, pp.rotations,
                                                       block, rot, config);
                Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
                body.put("shape", "path")
                    .put("tiles", pp.points.size)
                    .putRaw("rotations", rotationsJson(pp))
                    .put("message", r.message);
                // 失败时也把 body 带上：skipped 分解就在里面，丢了只剩一句散文
                return r.ok ? Json.ok(body.toString()) : Json.error(r.code, r.message, body);"""

API_SHAPE_OLD = """            Actor.Result r = Operations.placeBatch(team, pts, block, rot, config);
            return r.ok ? Json.ok(new Json.Obj()
                              .put("message", r.message)
                              .put("shape", shape.name())
                              .put("tiles", pts.size).toString())
                        : Json.error(r.code, r.message);"""

API_SHAPE_NEW = """            Actor.Result r = Operations.placeBatch(team, pts, block, rot, config);
            Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
            body.put("message", r.message).put("shape", shape.name()).put("tiles", pts.size);
            return r.ok ? Json.ok(body.toString()) : Json.error(r.code, r.message, body);"""

API_BREAK_OLD = """            Actor.Result r = Operations.breakBatch(team, pts);
            return r.ok ? Json.ok(new Json.Obj()
                              .put("message", r.message)
                              .put("shape", shape.name())
                              .put("tiles", pts.size).toString())
                        : Json.error(r.code, r.message);"""

API_BREAK_NEW = """            Actor.Result r = Operations.breakBatch(team, pts);
            Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
            body.put("message", r.message).put("shape", shape.name()).put("tiles", pts.size);
            return r.ok ? Json.ok(body.toString()) : Json.error(r.code, r.message, body);"""

API_CLEAR_OLD = """            if (clear) {
                Actor.Result r = Operations.clearQueue(team);
                return Json.ok(new Json.Obj().put("message", r.message).toString());
            }"""

API_CLEAR_NEW = """            if (clear) {
                Actor.Result r = Operations.clearQueue(team);
                Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
                body.put("message", r.message);
                return Json.ok(body.toString());
            }"""

# ── arena.py ───────────────────────────────────────────────────────────
CLI_OLD = """        raise ArenaError(-1, f"unreachable after retries: {last}")"""
CLI_NEW = """        # 退避重试用尽。若最后一次是 429，就如实报限流码 ——
        # 统一报成 -1（连不上）会让调用方去查网络，而真正该做的是降频。
        # 实测：一波密集请求被打回 429，脚本却显示 "unreachable"，白查了半天。
        if isinstance(last, urllib.error.HTTPError) and last.code == 429:
            raise ArenaError(1429, f"rate limited (retries exhausted): {last}")
        raise ArenaError(-1, f"unreachable after retries: {last}")"""

RULES = [
    (OPS, OPS_HELPER_ANCHOR, OPS_HELPER, 1, "Operations: summaryJson 辅助"),
    (OPS, OPS_ERR_OLD, OPS_ERR_NEW, 2, "Operations: err 带 extra"),
    (OPS, OPS_OK_OLD, OPS_OK_NEW, 2, "Operations: ok 带 extra"),
    (OPS, OPS_CLEAR_OLD, OPS_CLEAR_NEW, 1, "Operations: clearQueue 带 cleared"),
    (API, API_PATH_OLD, API_PATH_NEW, 1, "HttpApi: path 分支合并 extra"),
    (API, API_SHAPE_OLD, API_SHAPE_NEW, 1, "HttpApi: shape 分支合并 extra"),
    (API, API_BREAK_OLD, API_BREAK_NEW, 1, "HttpApi: break 分支合并 extra"),
    (API, API_CLEAR_OLD, API_CLEAR_NEW, 1, "HttpApi: clear 分支合并 extra"),
    (CLI, CLI_OLD, CLI_NEW, 1, "arena.py: 429 → 1429"),
]


def main():
    texts = {p: p.read_text(encoding="utf-8") for p in (OPS, API, CLI)}
    bad = []
    for path, old, new, want, label in RULES:
        t = texts[path]
        n = t.count(old)
        if n != want:
            bad.append(f"{path.name}: {n} 次命中（期望 {want}）→ {label}")
            print(f"  !! {n}/{want}  {label}")
            continue
        texts[path] = t.replace(old, new)
        print(f"  ✓ {n} 处  {label}")
    if bad:
        print("\n有问题，未写盘：")
        for b in bad:
            print("   " + b)
        return 1
    for p, t in texts.items():
        p.write_text(t, encoding="utf-8")
    print("\n三个缺陷已修")
    return 0


if __name__ == "__main__":
    sys.exit(main())
