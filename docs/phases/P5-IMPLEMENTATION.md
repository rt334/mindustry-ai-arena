# AI 竞技场 · P5 实现报告

> 对应 `../DESIGN.md` 第 9 节 P5。目标：人能看直播。
>
> **结论：服务器侧视角切换与裁判特权完整实测通过；客户端观察者 Mod 编译通过。**

---

## 1. 交付物

```
服务器侧（并入现有 Mod）
  HttpApi.java      resolveView() + /observe 端点
  所有只读端点支持 &view= 参数

客户端（独立 Mod）
  C:\dsh\ai-arena\observer\
    mod.hjson
    ai-observer.jar        5,621 B
    src\aiobserver\ObserverMod.java
```

---

## 2. 服务器侧：视角切换

### 2.1 `view` 参数

所有只读端点都支持：

```
GET /v1/{agent}/state?view=own          自己的队伍视角（默认）
GET /v1/{agent}/state?view=2            指定队伍视角
GET /v1/{agent}/state?view=all          上帝视角 —— 仅 admin
```

```java
private static int resolveView(AIArena.Agent agent, Params p) {
    Team own = agent.team();
    int ownId = own == null ? -1 : own.id;

    String v = p.get("view", null);
    if (v == null || v.isEmpty() || v.equalsIgnoreCase("own")) return ownId;

    if (v.equalsIgnoreCase("all")) return agent.admin ? -1 : ownId;

    try {
        int id = Integer.parseInt(v.trim());
        if (id < 0 || id >= Team.all.length) return ownId;
        if (!agent.admin && id != ownId) return ownId;
        return id;
    } catch (NumberFormatException e) { return ownId; }
}
```

**非 admin 请求别人的视角会被静默降级为自己的视角，而不是报错** —— 这样 AI 无法通过试错探测出自己无权访问哪些视角。

### 2.2 实测

```
referee /observe      → isReferee=true, canSeeAll=true,
                        teams: sharded(viewable=true), crux(viewable=true)
alpha /observe        → isReferee=false, canSeeAll=false,
                        teams: sharded(viewable=true), crux(viewable=false)

referee view=all      → team=-1，看到两个队的核心
alpha   view=all      → team=1，降级为 sharded（非 admin）
alpha   view=2        → team=1，降级
referee view=2        → team=2，只看到 crux 的核心（items 为空）
referee view=1        → team=1，只看到 sharded 的核心（2000×10）
referee /state view=all → view:"all"，两个队的单位和建筑全见
```

**库存也按视角隔离** —— `view=2` 时只看到 crux 的空核心，`view=1` 时只看到 sharded 的满载核心。

### 2.3 `/observe`

```
GET /v1/{agent}/observe
→ {"isReferee":true,"currentView":"all","canSeeAll":true,
   "teams":[{"id":1,"name":"sharded","cores":1,"viewable":true}, ...],
   "hint":"append &view=all for god view, or &view=<teamId> for a specific team"}
```

---

## 3. 为什么观战不走引擎实体同步

`../DESIGN.md` P5 里记的风险：

> 若试图让裁判走引擎的实体同步（`writeCustomEntitySnapshot`），可能与 `hiddenIds` 机制打架（先删后建导致闪烁）。**建议裁判直接走 HTTP 数据源**，绕开引擎同步。

本实现采纳了这个建议：**观战完全走 HTTP**，不占实体同步通道。

观察者因此**不需要在服务器上有队伍** —— 它只是一个带 admin token 的 HTTP 客户端。这顺带解决了 DESIGN 里提到的「观察者身份管理」：没有实体，就没有身份问题。

---

## 4. 客户端观察者 Mod

### 4.1 操作

| 按键 | 功能 |
|---|---|
| `WASD` / 方向键 | 平移相机 |
| 中键拖拽 | 平移相机 |
| 滚轮 | 缩放 |
| `Tab` | 在存活队伍间循环跳转 |
| `F1` | 显示/隐藏帮助 |

### 4.2 只读保证

Mod 只做三件事：读 `Groups.unit` / `Vars.state.teams` 用于显示、移动 `Core.camera`、画 UI。
**没有任何写操作** —— 不生成单位、不发 `Call.*`、不改世界。

### 4.3 复用引擎的缩放入口

```java
// DesktopInput.java:481 —— 引擎自己的缩放调用
renderer.scaleCamera(Core.input.axisTap(Binding.zoom));

// 本 Mod 直接复用，保证范围限制与玩家操作一致
float scroll = input.axisTap(mindustry.input.Binding.zoom);
if (Math.abs(scroll) > 0f) Vars.renderer.scaleCamera(scroll);
```

这样缩放范围自动跟随引擎的 `minZoomInGame` / `maxZoomInGame` 与玩家设置，不需要自己维护一套 clamp。

### 4.4 编译期踩到的四个 API 细节

| 误用 | 正确 |
|---|---|
| `Core.camera.zoom` | **不存在** —— 缩放走 `Vars.renderer.scaleCamera(float)` / `getDisplayScale()` |
| `KeyCode.middle` | `KeyCode.mouseMiddle` |
| `input.mouseX`（字段） | `input.mouseX()`（**方法**） |
| `arc.util.Scl` | **不存在** —— 用 `Vars.renderer.getDisplayScale()` |

---

## 5. 验收状态

| 项 | 状态 |
|---|---|
| 服务器侧按队视角 | ✅ 完整实测 |
| 服务器侧上帝视角（仅 admin） | ✅ 完整实测 |
| 非 admin 越权访问被降级 | ✅ 完整实测 |
| `/observe` 端点 | ✅ 完整实测 |
| 客户端 Mod 编译打包 | ✅ 通过 |
| 客户端 Mod 图形实测 | ⚠️ **未做** —— 需要图形环境启动 Mindustry 客户端 |

**图形实测未做的原因**：本环境的验证手段是 headless 服务器 + HTTP，客户端 Mod 的实际观感（相机手感、UI 布局、拖拽灵敏度）需要人在图形界面里操作才能评估。

**已通过编译与结构验证的部分**：jar 结构正确（`mod.hjson` + `aiobserver/ObserverMod.class`）、全部 API 调用对照源码确认存在、无写操作路径。

---

## 6. 对 `../DESIGN.md` 的修正

| 项 | 修正 |
|---|---|
| P5 服务器侧 | 落地为 `view` 参数 + `/observe`，非 admin 静默降级 |
| P5 观察者身份 | **不需要** —— 观战走 HTTP，观察者无实体 |
| **新增** | **引擎缩放的正确入口是 `Vars.renderer.scaleCamera()`**，`Core.camera` 没有 `zoom` 字段 |
| **新增** | **arc 的鼠标坐标是方法**（`mouseX()` / `mouseY()`），不是字段 |
