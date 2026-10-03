package aiarena;

import arc.ApplicationListener;
import arc.Core;
import mindustry.mod.Mod;

/**
 * AI 竞技场 · 服务器 Mod 入口。
 *
 * 启动顺序：
 *   1. 读取/生成配置（config/ai-arena.json）
 *   2. 挂载引擎事件监听器（事件流）
 *   3. 注册主线程监听器 —— 每帧刷新只读快照
 *   4. 启动 HTTP 服务端
 *
 * 快照刷新放在 ApplicationListener.update() 里，确保它跑在游戏主线程上；
 * HTTP 线程只读取 Snapshot 替换出来的不可变对象，不触碰世界。
 */
public class AIArenaMod extends Mod {

    @Override
    public void init() {
        AIArena.log("init, headless=" + mindustry.Vars.headless);

        AIArena.load();

        EventLog.install();

        Core.app.addListener(new ApplicationListener() {
            @Override
            public void update() {
                Snapshot.update();
            }
        });

        HttpApi.start();

        AIArena.log("ready");
    }
}
