# bots/ —— 常驻的毫秒级 bot

**给谁看**：写策略的人（或 LLM）。这份文档是**契约**，不是教程。

## 一条命令

```bash
python -m bots.run --agent beta            # 用 bots/strategy/demo.py
python -m bots.run --agent beta --dry-run  # 只决策，不发命令
```

`--decide-hz`（默认 5）、`--sense-hz`（默认 20）、`--max-cmds`（默认 20/秒）、
`--seconds`（0 = 一直跑）。轨迹写到 `_work/bot-trace-<agent>.jsonl`。

## 三层各管什么

| 层 | 在哪 | 节奏 | 谁改 |
|---|---|---|---|
| LLM | 编辑 `bots/strategy/*.py` | 秒到分钟 | 人 / LLM |
| **bot** | 本进程 | 决策 5 Hz、感知 20 Hz | 不改 |
| 引擎 | 服务端 | 60 tick/s | 不改 |

**LLM 不在决策回路里。** 它只改文件；本进程热加载后立刻生效，`mem` 不丢。
所以 reaction time 是 200 ms（决策周期），不是 LLM 的一次往返。

## 策略契约

```python
class Strategy:
    name = "whatever"

    def setup(self, world):        # 可选，第一次拿到世界时一次
        ...

    def decide(self, world, mem):  # 每拍调用
        return [actions.place(x, y, "conveyor", rot=0)]

    def teardown(self, world):     # 可选
        ...
```

硬约束：

1. **`decide` 里不许做 IO** —— 不许 HTTP、不许 `sleep`、不许读文件。要查东西用 `world`。
2. **只许读 `world`**。文件、环境变量、网络都是越界 —— 那会让你看到玩家看不到的信息。
3. **`mem` 是你的记忆**，dict，跨决策、跨热加载保留。进度、试过的坐标、失败计数放这里。
4. **同一个意图别每拍都发**。`/place` 是排队的，重复下单会塞满建造队列。
5. **返回意图，不是结果**。返回 `ok` 只代表入队。

改完文件**保存即生效**（`runner` 检查 mtime，重载后 `mem` 原样保留）。

## `world` 里有什么

| 属性 | 说明 |
|---|---|
| `tick` `playing` `paused` | 局面 |
| `team` `team_id` | 队名 / 队 id |
| `world_w` `world_h` | 世界尺寸 |
| `units` | 己方全部 + **当前视野内**的敌方（雾生效） |
| `buildings` | 己方全部 + 视野内敌方；**库存只给自己的队伍** |
| `factory` `drill` | 己方工厂 / 矿机状态 |
| `events` | 最近 40 条事件 |
| `rates_core` | `{item: 每秒净变化}`（**轮询来的**，1 Hz） |
| `stalls` | 产线警报（**轮询来的**，1 Hz） |
| `tiles` / `tile(x,y)` / `buildable(x,y)` | 地形缓存（启动时拉一次） |

方法：`cores()`、`own(arr)`、`builders()`、`unit_ids(pred)`、`block_at(x,y)`、
`rate(item)`、`stall_count()`、`age()`、`ready()`。

`rates` 与 `stalls` **也是推送的**（8 个通道同频），不再需要自己轮询。
`--poll-hz` 默认 0；只有在怀疑推送断了时才开它做兜底。

`rates` 是**固定 5 秒窗口**的净速率；要别的窗口用 REST `GET /rates?window=N`。
`stalls` 推的是数组（与 `GET /stalls` 的 `stalls` 同源），**不含 `stalledCount`** ——
条数自己数 `len(world.stalls)`。

**通道越多，每通道频率越低**：6 通道约 53 Hz/通道，8 通道约 40 Hz/通道
（总吞吐约 320 帧/秒是上限）。`--sense-hz` 默认 20，离上限很远。

## 动作

```python
from .. import actions

actions.place(x, y, "conveyor", rot=0, config=None, unit=None)
actions.break_(x, y)
actions.batch("p,x,y,block,rot;b,x,y")     # 一次请求做一批
actions.command("move", units, x=..., y=...)   # units 可传 "all"
actions.control("move", unit=id, x=..., y=...)
actions.config(x, y, value)
actions.chat("...")
```

`/place` 的 `rot` **必须给**（不给会被引擎拒绝）：

```
0 = 东 (x+1)   1 = 南 (y+1)   2 = 西 (x-1)   3 = 北 (y-1)
```

顺时针，且 **0 是东不是北**。

## 两个已实测的坑（都踩过）

**① 多格方块的 `x,y` 是中心，不是左上角。**
占位要用 `anchorX` / `anchorY` / `size` 算。拿中心 ±1 会全落在方块自己身上，
于是每一格都「建不了」——而那看起来像是地图没数据。

**② `liquid: "air"` 表示没有液体**，不是有液体。当成有液体会把整张图判成不可建。

## 方向一律反查，不要推算

铺传送带前先想清朝向，**铺完一定读 `sendsTo` 确认**：

```python
b["sendsTo"]    # [[x,y],...] 引擎记下的真实出货口
```

它与目标格对上了才算通。别用「中心点减坐标」之类的方法推方向 ——
多格方块旁边那一格到中心可能隔着好几格，推出来的朝向会偏一格，
**而接口不会报错**。`demo.py` 就是这么验的：建成 + 方向对上，两条都过才算过。

## 验证闭环

`/place` 返回 `ok` ≈ 入队，不是建成。建成与否要回读：

```python
b = world.block_at(x, y)            # None = 还没出现
b["block"] == "air"                 # 说明那儿是空地
b["sendsTo"]                        # [[x,y],...] 真实出货口
```

方向对不对，用 `sendsTo` 与目标格对比 —— 那是引擎记下的实际值，不是回显。
`demo.py` 就是这么验的（建成 + 方向进核心，两条都过才算过）。

## 还没有的东西

- **`/map` 不给 `solid` / `passable`** —— `buildable()` 只能保守排除
  （`block != air` / 水 / `deep` / 有液体），真正的可建判据仍在引擎手里。
- **没有复盘汇总器** —— `_work/bot-trace-<agent>.jsonl` 有每拍决策与每条 ack，
  但没有把它压成「这一局它在忙什么」。迭代策略时需要这个。
- **`rates` 的窗口写死 5 秒** —— 通道不给 `window` 参数；要长窗口得走 REST。
