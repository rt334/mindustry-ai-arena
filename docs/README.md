# 文档索引

项目级文档都收在这里，仓库根只留 `README.md` 一个入口。

> **想知道「还有什么没做」** → 直接看 [TODO.md](TODO.md)。那份盘点含原始目标、
> 功能缺口、验证债务，以及明确决定不做的条目与理由。

## 主文档

| 文件 | 内容 | 什么时候读 |
|---|---|---|
| [DESIGN.md](DESIGN.md) | 设计文档：架构、六项对等约束、九项引擎发现、P0~P7 分阶段设计、待验证清单 | 改接口或改对等模型之前 |
| [API.md](API.md) | 接口手册：起局、鉴权、端点表、参数与错误码、**信息可见性契约**、故障速查 | 写 AI 客户端时 |
| [CONDITIONS.md](CONDITIONS.md) | **条件与事故**：能力边界、对等约束的定义、发现过的越界路径与处理（含一处存在数周的瞬移后门） | 想知道「边界在哪、怎么定的、出过什么事」 |
| [TODO.md](TODO.md) | **未完成事项**：原始目标、功能缺口、验证债务、流程欠账，以及明确不做的条目与理由 | 接手时、想知道下一步做什么 |
| [ENGINE-NOTES.md](ENGINE-NOTES.md) | 引擎层事实：坐标系与朝向、方块语义、矿机公式、已修的引擎缺陷 | 排查「图纸对但实际不通」时 |
| [FEASIBILITY.md](FEASIBILITY.md) | 目标可行性：地质上限 vs 配方需求，含四次结论翻车的勘误 | 定产线目标之前 |
| [STRESS-TEST.md](STRESS-TEST.md) | 压力测试：62 用例、并发缺陷的定位过程、未覆盖项 | 动并发或线程模型时 |
| [PROMPTS.md](PROMPTS.md) | 提示词与工作流约定 | 多人/多 agent 协作时 |

## 分阶段实现报告 · [`phases/`](phases/)

| 文件 | 阶段 |
|---|---|
| [P0-VERIFICATION.md](phases/P0-VERIFICATION.md) | 技术验证（7 项原型，含影子 Player、`Core.app.post` 时延） |
| [P1-IMPLEMENTATION.md](phases/P1-IMPLEMENTATION.md) | 最简闭环：鉴权 → HTTP → 主线程 → 引擎流水线 |
| [P2-IMPLEMENTATION.md](phases/P2-IMPLEMENTATION.md) | 对等约束（11 条 + 指挥范围） |
| [P3-IMPLEMENTATION.md](phases/P3-IMPLEMENTATION.md) | 信息 API 与事件流 |
| [P4-IMPLEMENTATION.md](phases/P4-IMPLEMENTATION.md) | 操作 API：批量建造、spawn、chat |
| [P5-IMPLEMENTATION.md](phases/P5-IMPLEMENTATION.md) | 观战与裁判：`view` 参数、客户端观察者 Mod |
| [P7-IMPLEMENTATION.md](phases/P7-IMPLEMENTATION.md) | 编排与场景（第 7 节含 P6 录像摘要） |

P6（回放）没有独立文档，服务器侧已实现，客户端图形回放未做，摘要并在 P7。

## 实战复盘 · [`reviews/`](reviews/)

产线攻坚（目标是铜/铅/硅/钛/石墨各 +5/s）留下的四份记录，接口层的好几条改进都出自这里。

| 文件 | 内容 |
|---|---|
| [REPORT.md](reviews/REPORT.md) | 攻坚报告：7 轮实测产出、这张图的硬约束、打通的链路 |
| [DEBUG-LOG.md](reviews/DEBUG-LOG.md) | 调试复盘：撞到的坑、定位手段、沉淀的做法 |
| [FEATURE-REQUESTS.md](reviews/FEATURE-REQUESTS.md) | 接口层改进提案 A1~A8 / B1~B4，按痛点强度排序 |
| [REVIEW-ADDENDUM.md](reviews/REVIEW-ADDENDUM.md) | 对上面提案的核对：修正 2 条、新增 4 条、优先级重排 |

## 不在这个目录里的

- 项目入口与快速上手：仓库根 [`README.md`](../README.md)
- 可安装的 Skill 包：[`skill/`](../skill/) —— 会被拷到 `%USERPROFILE%\.dsh\skills\ai-arena\`，
  因此**刻意不含任何游戏内事实**（公平竞技约束，理由见 [DESIGN.md 第 0 节](DESIGN.md)）
