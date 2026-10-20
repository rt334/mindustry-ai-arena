"""策略契约 —— LLM 要写/改的就是这个包里的文件。

一个策略是一个普通的 Python 对象，只有三个可选方法：

```python
class Strategy:
    name = "demo"

    def setup(self, world):
        \"\"\"第一次拿到世界时调用一次（可省略）。\"\"\"

    def decide(self, world, mem) -> list:
        \"\"\"每个决策拍调用一次。返回动作列表（`bots.actions` 里的东西）。\"\"\"

    def teardown(self, world):
        \"\"\"退出时调用一次（可省略）。\"\"\"
```

规则（这些不是建议，是约束）：

1. **`decide` 必须快**。它每拍都跑（默认 5 Hz），里面不许做 HTTP、不许 sleep。
   要查东西就用 `world`（它已经是推来的快照）。
2. **不许读 `world` 以外的东西**。文件、环境变量、网络都算越界 ——
   那会让策略看到玩家看不到的信息，破坏对等约束。
3. **`mem` 是你的记忆**。一个 dict，跨决策、跨热加载都保留。
   把进度、尝试过的坐标、失败计数放这里，**不要**用模块级全局变量。
4. **返回意图，不返回结果**。你只负责说「要做什么」；能不能做、什么时候做，
   由引擎和 `runner` 决定。`/place` 是排队的，返回 ok 不代表建成。
5. **同一个意图别每拍都发**。把「已经下过单」记进 `mem`，否则每 200 ms
   重复排队同一格，会把建造队列塞满。

热加载：改完这个包里的文件保存即可，`runner` 会在下一次决策前重载，
**`mem` 不会丢**。这就是「LLM 局内改 bot」的通道 —— bot 不停、决策不中断。
"""


class Strategy:
    """示例基类。实际策略不必继承它，鸭子类型即可。"""

    name = "base"

    def setup(self, world):
        pass

    def decide(self, world, mem):
        return []

    def teardown(self, world):
        pass
