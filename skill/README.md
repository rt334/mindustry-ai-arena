# ai-arena Skill

Mindustry AI 竞技场的**接口说明书**。只说怎么调用接口，不含任何游戏内容。

- `SKILL.md` —— 入口：铁律（禁止等待）、起局、鉴权、接口表、观战端、排查入口
- `scripts/arena.py` —— Python 客户端库（连接、退避重试、轮询确认）
- `scripts/survey.py` —— 全图普查
- `scripts/place-line.py` —— 按坐标表批量下单并逐格确认

## 边界

本 skill **刻意不写**矿脉分布、方块参数、配方、地图结构等游戏内事实。

理由：本项目的第一原则是公平竞技 —— AI 在任何时刻看到的，必须与一个真人玩家
在同队时看到的完全一致。而 skill 是 agent 启动时就会读到的文件，往里塞游戏内情
等于让它在开局前就拿到答案。

需要的东西去游戏里查：`/content` 给方块与物品表，`/map` 给地形，
`/place` 的 `rot` 语义放一个方块看着走一遍就知道了。

引擎与接口实现层的说明在仓库的 `docs/ENGINE-NOTES.md`（维护者文档，非 agent 读物）。

## 安装

把本目录内容放到 `%USERPROFILE%\.dsh\skills\ai-arena\`。

仓库：https://github.com/rt334/mindustry-ai-arena
