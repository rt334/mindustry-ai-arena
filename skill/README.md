# ai-arena Skill

把 Mindustry AI 竞技场的接口层做成可复用的 skill。

- `SKILL.md`          —— 入口：铁律、起局、速查、坑
- `references/api.md` —— 完整接口手册（也发布在项目仓库的 `API.md`）
- `scripts/arena.py`  —— Python 客户端库（连接/重试/轮询确认）
- `scripts/survey.py` —— 全图矿脉普查（自动 view=all）
- `scripts/place-line.py` —— 按坐标表批量下单并逐格确认

安装：把本目录放到 `%USERPROFILE%\.dsh\skills\ai-arena`。

仓库：https://github.com/rt334/mindustry-ai-arena
