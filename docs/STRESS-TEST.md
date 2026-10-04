# AI 竞技场 · 全功能压力测试报告

> 工具：`stress-test.ps1`（五个阶段，62 个用例）
> 环境：Windows / PowerShell 5.1 / AMD Ryzen 9 7945HX（16 核 32 线程）/ 15.7 GB 内存
>
> **结论：62/62 全部通过。过程中发现并修复了一个真实的并发缺陷。**

---

## 1. 最终结果

```
总用例  62   通过 62   失败 0

按阶段:
  cover         29 用例   通过  29   失败   0
  concurrent     1 用例   通过   1   失败   0
  write          4 用例   通过   4   失败   0
  edge          26 用例   通过  26   失败   0
  stability      2 用例   通过   2   失败   0

单次请求延迟:  min 1ms   中位 30ms   max 45ms
```

---

## 2. 五个阶段

### 阶段 1 · 功能覆盖（29 用例）

当时全部 18 个端点顺序验证，覆盖读、写、裁判三类。

> **注意**：端点后来长到了 33 个（见 [DESIGN.md](DESIGN.md) §6.1），
> 新增的那些**没有被这次压测覆盖** —— 并发与边界问题要重跑才作数。

```
读端点 13 个:  /ping /state /units /buildings /map(区域) /map(全图)
              /content /intel /events /observe /queue /maps /record
写端点 16 个:  /place(单点+4种形状) /break /config /spawn /chat
              /command(3种) /control(3种) /queue?clear
```

### 阶段 2 · 并发读

`RunspacePool` 多线程同时轮询，模拟 N 个 AI 同时读局面。

```
24 线程 × 40 次 = 960 请求
成功/失败  960 / 0
耗时       0.20 秒  (4,752 req/s)
延迟       avg 1ms  p50 0ms  p95 2ms  p99 41ms
```

### 阶段 3 · 高频写

```
20 次批量建造 (3x3)   成功 20  失败 0
30 次生成单位          成功 21  人口拦截 9    ← 上限生效
20 次多单位指挥        成功 20  失败 0
15 次事件轮询          成功 15  累计事件 100  游标正常推进
```

### 阶段 4 · 边界与错误路径（26 用例）

```
坐标与范围   越界 400 / 负坐标 400 / 视野外建造 403 / 视野外指挥 403
参数校验     未知方块 404 / 未知 shape 400 / 未知单位 404 / 未知 command 400
             未知 control op 400 / 未知 stance 404 / 缺参数 400 / 空 units 404
配额上限     批量超限 429 / map 区域超限 400 / map 负尺寸 400
鉴权越权     无 token 401 / 错 token 401 / 跨 agent 403 / 非 admin setup 403
             非 admin record 403
视角降级     view=all 静默降级为 sharded（不报错）
裁判特权     view=all 200 / view=2 200 / 录像路径穿越 400
```

### 阶段 5 · 稳定性

```
25 秒持续轮询
请求       398 成功 / 0 失败
服务器内存  163 MB → 199 MB   (波动，无单调增长)
tick 推进   472 → 1963  (+1491，约 59.6 tick/s)   ← 满帧
日志       无异常
```

---

## 3. 压测发现并修复的并发缺陷

**这是本次压测最大的收获。**

### 症状

高并发下约 1–3% 的请求返回 500，失败率与并发数成正比：

```
12 线程  →   8 / 480  失败  (1.7%)
24 线程  →  28 / 960  失败  (2.9%)
```

服务器日志只显示 `route error: java.util.NoSuchElementException: 5` —— 异常消息只是个数字索引，看不出抛出位置。

### 定位过程

第一次把堆栈打到 stdout，什么也没看到 —— 因为 `printStackTrace()` 走的是 **stderr**，而我一直看的是 stdout。改看 stderr 后一次定位：

```
java.util.NoSuchElementException: 5
    at arc.struct.Seq$SeqIterable$SeqIterator.next(Seq.java:1171)
    at aiarena.AIArena.authenticate(AIArena.java:215)     ← 鉴权！
    at aiarena.HttpApi.route(HttpApi.java:115)
```

**不是视野计算，是 agent 遍历。**

### 根因

```java
// 错误：agents 是 arc.struct.Seq
public static final Seq<Agent> agents = new Seq<>();

// authenticate 里每个请求都遍历它
for (Agent a : agents) {
    if (MessageDigest.isEqual(a.tokenBytes, presented)) found = a;
}
```

`arc.struct.Seq` 的迭代器**在多线程并发遍历时会互相踩状态**。每个请求都要过鉴权，所以失败率与并发数成正比。

### 修复

```java
// 正确：CopyOnWriteArrayList
// agents 只在启动时写入一次、之后纯读 —— CopyOnWriteArrayList 的读路径
// 完全无锁，正好匹配这个访问模式。
public static final java.util.List<Agent> agents = new java.util.concurrent.CopyOnWriteArrayList<>();
```

修复后 24 线程下 960/960 全过。

### 附带改进

| 项 | 改动 | 原因 |
|---|---|---|
| HTTP 线程池 | 4 → 16（可配置） | 4 个线程在 12 并发下成为瓶颈 |
| HttpServer backlog | 0 → 128（可配置） | 应对连接突发 |
| 视野查询 | 加 `safeVisible` / `safeVisibleTile` / `safeDiscovered` | `FogControl` 也非线程安全，兜底方向是「宁可少看，不可多看」 |

配置项：

```json
{
  "http": { "threads": 16, "backlog": 128 }
}
```

---

## 4. 一个值得记下的排查教训

**异常堆栈可能不在你以为的那条流上。**

`t.printStackTrace()` 输出到 `System.err`，而 `Log.info` / `System.out` 输出到 stdout。测试脚本把两者分别重定向到 `stress-out.log` 和 `stress-err.log`，我前几轮只看 stdout，所以只看到异常消息（`NoSuchElementException: 5`）而看不到调用链，导致连续几轮都在错误的方向上猜测（先后怀疑 `FogControl`、`TeamData`、`Seq.get` 越界）。

**改看 stderr 后一次定位。**

同理，`NoSuchElementException` 的消息只是索引值（`5`），单独看毫无信息量 —— 这类异常**必须**配堆栈。

---

## 5. 复现方式

```powershell
# 默认：12 线程 / 40 次每线程 / 45 秒稳定性
.\stress-test.ps1

# 更高并发
.\stress-test.ps1 -Threads 24 -PerThread 40 -Seconds 60

# 跳过稳定性阶段（快速回归）
.\stress-test.ps1 -SkipStability
```

脚本会自行拉起服务器、初始化对局、跑完五个阶段、输出汇总、保存 `stress-report.json`、然后关闭服务器。
任一用例失败时退出码为 1。

---

## 6. 未覆盖的部分

| 项 | 说明 |
|---|---|
| 客户端观察者 Mod 的图形观感 | 需要图形界面实际操作，headless 环境无法评估 |
| 长时间运行（小时级） | 本次最长 60 秒；内存未见单调增长，但不足以断言无泄漏 |
| 真实 AI 对局 | 测试用的是脚本化的 HTTP 调用，不是真的 AI 决策循环 |
| 录像完整性回放 | 录像文件的写入已验证；客户端图形回放未实现 |
