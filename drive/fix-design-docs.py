#!/usr/bin/env python3
"""第 0 档：DESIGN.md 契约章节回写。

这批全是「前面的契约没跟上后面的实现」，逐条都有实现或源码依据：

1. 首行还写「待进入 P0 技术验证」，而 P0–P7 末尾全标 ✅
2. §6.1 端点表只列 11 个，实际路由里 33 个（mod/src/aiarena/HttpApi.java:125-158）
3. 错误约定写「命令级失败用 message」，实际全部错误路径走 Json.error(code, msg)
4. 错误码表缺 1401 / 1403
5. 分页写「按 1 MiB 阈值 + cursor_next」，实际是区域 4096 格硬上限 + 全图游标续传
6. 回放格式写「二进制 + zip」，实际是 JSON Lines
7. 术语表写「六项限制」，正文与汇总表都是 11 项
8. §10 风险表里 4 项有 2 项已闭环、1 项已绕开
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\DESIGN.md")

OLD_ENDPOINTS = """```
POST /v1/{agentId}/place      授权: Bearer <token>
GET  /v1/{agentId}/map?x=&y=&w=&h=&cursor=
GET  /v1/{agentId}/state
GET  /v1/{agentId}/units
GET  /v1/{agentId}/buildings
GET  /v1/{agentId}/content
GET  /v1/{agentId}/intel
GET  /v1/{agentId}/events?since=<seq>      或 SSE
POST /v1/{agentId}/break
POST /v1/{agentId}/config
POST /v1/{agentId}/command
```"""

NEW_ENDPOINTS = """**共 33 个端点**（早期版本这里只列了 11 个，实现长出去之后没回写）。
逐条的参数与响应见 [`API.md`](API.md)，唯一事实源是 `mod/src/aiarena/HttpApi.java` 的
路由 `switch`。

```
读（GET，Bearer token）
  /v1/{agentId}/state                     局面：tick、队伍、核心、单位、建筑
  /v1/{agentId}/map?x=&y=&w=&h=&cursor=   地形（区域上限 4096 格，全图用 cursor 续传）
  /v1/{agentId}/units                     己方单位
  /v1/{agentId}/buildings                 己方建筑（含未完工）
  /v1/{agentId}/block?x=&y=               单格详情
  /v1/{agentId}/content                   方块 / 物品 / 单位表
  /v1/{agentId}/ore                       矿脉统计
  /v1/{agentId}/rates?window=<秒>         核心与全队产率
  /v1/{agentId}/stalls                    产线异常警报
  /v1/{agentId}/drill                     矿机明细
  /v1/{agentId}/factory                   单位工厂
  /v1/{agentId}/queue                     建造队列
  /v1/{agentId}/intel                     核心数据确认状态
  /v1/{agentId}/events?since=<seq>        事件流（游标轮询）
  /v1/{agentId}/database                  汇总数据库
  /v1/{agentId}/maps                      可用地图

写（POST）
  /v1/{agentId}/place                     下建造计划
  /v1/{agentId}/break                     拆除
  /v1/{agentId}/config                    设置方块配置
  /v1/{agentId}/command                   指挥（8 种 action）
  /v1/{agentId}/control                   直接操纵
                                          op = pos order warp enter release fire stopmove orders
  /v1/{agentId}/spawn                     生成单位
  /v1/{agentId}/mine                      让单位挖指定格
  /v1/{agentId}/chat                      发言

裁判（admin = true）
  /v1/{referee}/diag                      服务端诊断计数器
  /v1/{referee}/observe                   视角切换
  /v1/{referee}/record                    录像开关
  /v1/{referee}/setup?map=                加载地图 + 放核心 + 生成建造单位
  /v1/{referee}/host                      打开游戏端口 6567
  /v1/{referee}/start                     解除暂停
  /v1/{referee}/fog                       迷雾开关
  /v1/{referee}/admin                     在线玩家管理

无鉴权
  /ping                                   健康检查
```"""

OLD_ERR = """**注意**：命令级失败的说明在 `message` 字段；只有未捕获异常才用 `error` + 5xx。（此约定来自 `eve-assistant` 的教训 —— 它的文档声称有 `error` 字段但代码里没有。）"""

NEW_ERR = """**失败一律用 `error` + `code`**，与成功响应的 `data` 对称：

```json
{"ok": false, "code": 1003, "error": "out of bounds: (700,700)"}
```

**实现与本节早期版本不一致，以实现为准。** 早期写「命令级失败用 `message`、
只有未捕获异常才用 `error`」—— 那是照搬 `eve-assistant` 的设计意图，而实际代码里
全部错误路径都走 `Json.error(code, msg)`。HTTP 状态码由 `statusFor` 从 `code` 推出来：

| code | HTTP | 含义 |
|---|---|---|
| 1001 / 1003 | 400 | 参数错 / 越界 |
| 1002 | 404 | 找不到 |
| 1004 | 429 | 队列或限流满 |
| 1005 / 1403 | 403 | 只读 / 权限不足 |
| 1006 | 410 | 游标过期 |
| 1007 | 504 | 主线程超时 |
| 1401 | 401 | 鉴权失败 |

**判失败要看 body 里的 `code`，不是 HTTP 状态码** —— 状态码只是给代理和日志看的粗分类。"""

OLD_CODES = """1001 bad_request      1002 not_found         1003 out_of_bounds
1004 queue_full       1005 read_only         1006 cursor_expired
1007 op_expired       1500 internal_error"""

NEW_CODES = """1001 bad_request      1002 not_found         1003 out_of_bounds
1004 queue_full       1005 read_only         1006 cursor_expired
1007 op_expired       1401 unauthorized      1403 forbidden
1500 internal_error"""

OLD_PAGING = """**大响应必须分页** —— 250×250 地图的完整 tile 数据远超 1 MiB。建议阈值 1 MiB，游标 `cursor_next`。"""

NEW_PAGING = """**分页（实现与早期设计不同）** —— 早期建议「按 1 MiB 阈值切 + `cursor_next`」，
实际是两条互补路径：

- **区域查询有硬上限**：`/map?x=&y=&w=&h=` 单次最多 **4096 格**，超出返回 `400`
- **全图查询用游标**：不传 `x/y/w/h` 时服务端按 `cursor` 分块返回，客户端续传到 `done`

两者都叫 `cursor`，区别是前者「你自己切块」、后者「服务端帮你切块」。"""

OLD_REPLAY = """存储格式参考 `Ekrulan/replay-mod`：二进制 + zip，`Tick` 分隔帧。"""

NEW_REPLAY = """**实际实现是 JSON Lines**（`{"t":"meta"...}` / `{"t":"snap"...}` / `{"t":"ev"...}` / `{"t":"end"...}`）——
流式追加、崩溃时已写部分仍可解析、客户端用与实时同一套解析器逐行读；
方块只存增量（首次全量 + 后续变化）。

早先这里写「参考 `Ekrulan/replay-mod` 的二进制 + zip」是设计期的备选，实现时改了：
那个库本身 TODO 6 项未完成、无 LICENSE，且二进制格式会让实时与回放维护两套解析器。"""

OLD_GLOSSARY = """| **对等约束** | AI 的可见与可为必须等于同队人类玩家的六项限制 |"""

NEW_GLOSSARY = """| **对等约束** | AI 的可见与可为必须等于同队人类玩家的 11 条限制（逐条见第 4 节） |"""

OLD_RISK = """| 项 | 阶段 | 说明 |
|---|---|---|
| PvP 地图需自制 | P5/P7 | 内置 18 张地图都是生存地形（`spawns=0`、无 `pvp` tag）。`World.java:372` 强制要求 PvP 地图 ≥2 个核心，地图须自行制作 |
| `writeCustomEntitySnapshot` 与 `hiddenIds` 是否打架 | P5 | 若闪烁，裁判改走 HTTP 数据源 |
| 快照频率与体积的平衡 | P6 | 单位全量快照的合理间隔需实测 |
| 建造流水线的完整链路 | P1 | `addBuild → BuilderComp → ConstructBlock` 端到端（P0 因测试地形未跑通，属配置问题） |"""

NEW_RISK = """| 项 | 阶段 | 状态 |
|---|---|---|
| PvP 地图需自制 | P5/P7 | **已解决，不必自制** —— 实测直接用引擎硬编码的 `veins` / `glacier` / `passage`，配合 `findCoreSpot + layCoreZone` 自行放核心即可（[P7](phases/P7-IMPLEMENTATION.md) §3 四队就位实测通过）。早期「内置 18 张都是生存地形、须自制」的结论只对「直接用内置图的 spawn」成立 |
| `writeCustomEntitySnapshot` 与 `hiddenIds` 是否打架 | P5 | **已绕开** —— 裁判不走引擎实体同步，改走 HTTP 数据源（[P5](phases/P5-IMPLEMENTATION.md) §3），该风险不再相关 |
| 快照频率与体积的平衡 | P6 | **仍未测** —— 只有 10 秒 / 18 行的短测，「约 45 MB/小时」是按快照间隔估的，长局未验证 |
| 建造流水线的完整链路 | P1 | **已闭环** —— [P1](phases/P1-IMPLEMENTATION.md) §5.1 与 [P4](phases/P4-IMPLEMENTATION.md) 均已实测方块落地（含 40 格批量），此项已从风险降级 |"""

RULES = [
    ("> **状态**：设计阶段完成，待进入 P0 技术验证。",
     "> **状态**：P0–P7 已实现并实测。服务器侧 33 个端点、压测 62/62 通过；\n"
     "> 客户端观察者 Mod 编译通过但图形未实测，图形回放未做。余项见第 10 节。"),
    (OLD_ENDPOINTS, NEW_ENDPOINTS),
    (OLD_ERR, NEW_ERR),
    (OLD_CODES, NEW_CODES),
    (OLD_PAGING, NEW_PAGING),
    (OLD_REPLAY, NEW_REPLAY),
    (OLD_GLOSSARY, NEW_GLOSSARY),
    (OLD_RISK, NEW_RISK),
]


def main():
    text = P.read_text(encoding="utf-8")
    bad = []
    for old, new in RULES:
        n = text.count(old)
        label = old.splitlines()[0][:58]
        if n != 1:
            bad.append(f"{n} 次命中（应为 1）: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有规则不满足，未写盘：")
        for b in bad:
            print("  " + b)
        return 1
    P.write_text(text, encoding="utf-8")
    print(f"\nDESIGN.md 已更新，共 {len(RULES)} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
