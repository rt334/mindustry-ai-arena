# AGENTS.md —— 在这个仓库里干活的 agent 从这里开始

> ## ⚠ 先分清你是谁
>
> **这个仓库的 `docs/`、`drive/`、`mod/`、`_work/` 里全是实测出来的游戏内情** ——
> 矿机公式、方块语义、矿脉分布、布局结论、地图地形。这是**维护者文档**。
>
> **参赛 AI 不要读它们。** 本项目的第一原则是公平竞技：
> AI 在任何时刻看到的，必须与一个真人玩家在同队时看到的完全一致。
> 把这些文档当知识库读，等于开局前就拿到玩家要靠试验才能得到的答案。
>
> 参赛 AI 该读的是 [`skill/`](skill/)（刻意不含任何游戏内情）与 [`docs/API.md`](docs/API.md)（接口手册）。

## 想做什么，读哪份

| 想做的事 | 读 |
|---|---|
| 改接口层 / 加端点 / 编译部署 | [`docs/DEVELOPING.md`](docs/DEVELOPING.md) |
| **动手排查之前**（必读） | [`docs/LESSONS.md`](docs/LESSONS.md) §二 —— 验证脚本自己会错，而且错得像功能坏了 |
| 知道还有什么没做、欠哪些验证 | [`docs/TODO.md`](docs/TODO.md) |
| 改对等模型 / 想知道边界怎么定的、出过什么事 | [`docs/DESIGN.md`](docs/DESIGN.md)、[`docs/CONDITIONS.md`](docs/CONDITIONS.md) |
| 排查「图纸对但实际不通」 | [`docs/ENGINE-NOTES.md`](docs/ENGINE-NOTES.md) |
| 全部文档的索引 | [`docs/README.md`](docs/README.md) |
| **按需取某一节**（别整份读） | `python drive/docs-index.py --grep <关键词>` → 再 `--read "文件.md#节标题"` |
| **审计某个参赛 AI 想了什么 / 调了什么 / 碰了哪些文件** | `python drive/agent-trail.py --list`，再 `--id <前缀>`（可加 `--thinking` / `--http` / `--files` / `--commands`；见 [TODO](docs/TODO.md) §14.7） |

## 铁律（都是违反过、吃过亏的）

1. **判据是状态，不是时长。** `poll_until(pred, timeout)`，不写裸 `sleep(N)`。
   `/place` 是**排队**的：返回成功只代表入队，下完必须轮询 `/buildings` 确认。
2. **别从渲染后的东西猜结构。** `Get-Content` 显示的空格数不等于实际缩进；
   往已有文件里插内容一律用 `^(\s*)` 整行正则匹配、把缩进捕获下来原样带回。
3. **清单要双向维护。** 做了要回填，过时要划掉 —— 否则下一个人会照旧账再核一遍。
4. **一次只改一个变量。** 铺一片再测，出问题无法归因。
5. **改 `mod/src/aiarena/*.java` 后必须重新编译部署 + 重启服务器**（不热加载）。
   编译命令见 `docs/DEVELOPING.md` §二；**jar 条目数应是 50**（46 class + `mod.hjson`
   + `MANIFEST.MF` + 2 目录项），数目变了说明有文件增删 —— **离线断言会替你查这个数**。
6. **凭据不进模型上下文。** 参赛客户端只用自己的 token —— 取法有三种，都只给**自己那一个**：
   `GET /v1/bridge/<agentId>`（无鉴权）、本地 `bridge-<agent>.json`（同源）、
   或 `arena.load_own_token(agent_id)`。
   **admin 凭据只从环境变量 `ARENA_ADMIN_TOKEN` 读** —— 配置文件里那条已被服务器忽略，
   读不到就不注册 admin（fail-closed），`/v1/bridge/referee` 也只给 `tokenHint` 不给 token。
   拿裁判的 `view=all` 看全图等于越过对等约束，**而且会被审计记下**（`privileged:true`）——
   见 `docs/CONDITIONS.md` 事故记录第 6 条。
   **权限分三档** `player` / `observer` / `referee`（旧 `admin:true` = referee）：
   `observer` 能 `view=all` 但不能改状态，**且 setup 不给它核心与单位**
   （给了它就不再是纯观察者 —— 引擎会给有核心的队伍塞单位）。
7. **改 `.ps1` 文件要小心 BOM。** 四个 `.ps1`（`start-arena` / `live-match` / `diagnose` /
   `stress-test`）都带 UTF-8 BOM，而 `.gitattributes` 声明 `*.ps1 -text` —— **BOM 是文件内容的一部分**。
   普通文本编辑会吃掉它，后果是 Windows PowerShell 5.1 按 GBK 解析中文。
   改完比对首三字节是不是 `EF BB BF`。
8. **改 `skill/` 之后必须跑 `python drive/check-boundary.py`。** 那个包面向参赛 AI，
   不许出现实测出的游戏内情（引擎公式、产率数字、地图名、方块参数、布局结论）。
   它自带 `--selftest`：**先证明规则真能命中，再谈「违规 0」** —— 否则那份报告是假绿。
9. **改端点 / 错误码 / `shape` / 文档里的端点清单之后，跑 `python drive/offline-checks.py`。**
   它把「文档与代码是否一致」变成可回归的检查（端点数量、错误码集合、`shape` 取值、jar 条目数、
   **死参数扫描** —— 读进来却没用到的请求参数），而且**不需要起游戏**。
   它自己也被验证过：写完先故意造错让它红，确认过不是假绿。

## 验证改动

```powershell
# 编译（不启游戏，2 秒）
$jc = 'C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\javac.exe'
$mj = 'C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar'
& $jc -encoding UTF-8 -cp $mj -d mod\classes (Get-ChildItem mod\src\aiarena\*.java).FullName
```

| 层次 | 手段 | 要不要起游戏 |
|---|---|---|
| 编译 / class 集合一致性 | 上面的 `javac` + `jar tf` 比对 | 不要 |
| **离线断言套件**（91 项：JSON 转义 / 响应信封 / 审计判定 / 状态码映射 / 端点数量 / 错误码集合 / `shape` 取值 / jar 条目 / 文档里写死的数字 / 死参数扫描 / `StallWatch` 快照同源） | `python drive/offline-checks.py`（`--src` 可跳过 JVM） | 不要 |
| **`skill/` 边界检查**（参赛者可见包有没有泄漏游戏内情） | `python drive/check-boundary.py`（先 `--selftest`） | 不要 |
| **文档按需检索**（取某一节，而不是整份读） | `python drive/docs-index.py --grep/-read` | 不要 |
| 全功能回归 | `.\stress-test.ps1`（62 用例，自起服务器） | 要 |
| 接口行为实测 | `python start.py play` 后跑 `drive/verify-*.py` | 要 |

**行尾**：`.gitattributes` 声明 `* text=auto eol=lf`（`*.ps1` 除外，见铁律 7）。
2026-10-06 已把工作树里 43 个 CRLF 文件统一为 LF —— `git ls-files --eol` 现在 `w/crlf` 应为 0。
按行匹配的锚点脚本有 101 个，行尾漂移会让它们**静默**失效，所以改完顺手跑一次：
`git ls-files --eol | Select-String 'w/crlf'`（输出应为空）。

**`git status` 会多报 M，那不是真改动。** `eol=lf` 是个 filter，凡是被改过行尾的文件
mtime 全变 → `status` 按 stat 报 M，而 `git diff` 是空的。用 `git add -u` 刷新索引即可
（内容相同，不会产生任何提交内容）。**下结论前先看 `git diff`，别看 `git status`。**
