#!/usr/bin/env python3
"""策略能返回的动作，以及它们到 `cmd` 的编码。

策略**只描述意图**（「在这放个传送带」），不碰网络。编码与限流在 `runner`。
这样策略可以纯粹地被推理、被测试、被 LLM 读改。

动作是普通 dict，`{"op": ...}`。下面给的构造函数只是让写法短一点。

服务端参数形态（`HttpApi.java` 已核对）：
- `/place`   `x y block [rot] [config] [unit]`，**`rot` 不给就是 -1**（会被拒绝，
  因为 0 是「东」，默认给东几乎注定把线铺反）
- `/break`   `x y`
- `/batch`   `ops=p,x,y,block[,rot];b,x,y;c,x,y,config`
- `/command` `action` + `units=逗号分隔` + `x y [target] [queue] [cmd] [stance]`
- `/control` `op` + `unit` + `x y`
- `/config`  `x y value`
"""
from __future__ import annotations

# rot 的语义（skill 里给的，已实测核对过）：
#   0 = 东 (x+1)   1 = 南 (y+1)   2 = 西 (x-1)   3 = 北 (y-1)
# 顺时针，且 0 是东不是北 —— 别按「0 度朝上」的先验推。


def place(x, y, block, rot=None, config=None, unit=None):
    a = {"op": "place", "x": x, "y": y, "block": block}
    if rot is not None:
        a["rot"] = rot
    if config is not None:
        a["config"] = config
    if unit is not None:
        a["unit"] = unit
    return a


def break_(x, y):
    return {"op": "break", "x": x, "y": y}


def batch(ops):
    """`ops` 是 `p,x,y,block,rot;b,x,y` 这种字符串；也接受列表自动拼。"""
    if isinstance(ops, (list, tuple)):
        ops = ";".join(ops)
    return {"op": "batch", "ops": ops}


def command(action, units, **kw):
    """units 可以是单个 id、id 列表，或 `"all"`（展开成当前全部己方单位）。"""
    a = {"op": "command", "action": action, "units": units}
    a.update(kw)
    return a


def control(op, unit=None, **kw):
    a = {"op": "control", "op_name": op}
    if unit is not None:
        a["unit"] = unit
    a.update(kw)
    return a


def config(x, y, value):
    return {"op": "config", "x": x, "y": y, "value": value}


def chat(text):
    return {"op": "chat", "text": text}


# ---------------------------------------------------------------- 编码

_SIMPLE = {
    "place": "place",
    "break": "break",
    "batch": "batch",
    "command": "command",
    "control": "control",
    "config": "config",
    "chat": "chat",
}

# 这些键只是动作描述用的，不进 query
_META = {"op", "op_name"}


def encode(action: dict):
    """动作 → (endpoint, params)。无法识别时返回 (None, 错误说明)。"""
    op = action.get("op")
    endpoint = _SIMPLE.get(op)
    if endpoint is None:
        return None, f"unknown action op: {op!r}"

    params = {}
    for k, v in action.items():
        if k in _META:
            continue
        if v is None:
            continue
        if isinstance(v, bool):
            params[k] = "true" if v else "false"
        elif isinstance(v, (list, tuple)):
            params[k] = ",".join(str(x) for x in v)
        else:
            params[k] = v

    if op == "control":
        params["op"] = action["op_name"]

    return endpoint, params


def expand_units(action, world):
    """把 `units="all"` 展开成当前己方单位 id 列表。原地改副本。"""
    if action.get("op") != "command":
        return action
    if action.get("units") != "all":
        return action
    ids = world.unit_ids()
    if not ids:
        return None
    out = dict(action)
    out["units"] = ids
    return out
