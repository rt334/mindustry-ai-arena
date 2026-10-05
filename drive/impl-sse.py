#!/usr/bin/env python3
"""实现 SSE 推送 —— DESIGN.md 41/731/853 三处承诺「SSE 推给观察者」，
但此前只交付了游标轮询，SSE 一行实现都没有。

上一轮我搁下它是因为「没确认 events 的序列化 API」。现在读了：
    EventLog.since(since, limit, viewer) → Seq<Ev>，ev.toJson()
    EventLog.cursorExpired(since) / EventLog.lastSeq()

设计：
  · 与轮询**共用同一套游标语义**（since / nextSince / cursorExpired），
    所以客户端从轮询切到 SSE 不用改状态机
  · 为什么值得做：轮询要 AI 自己定频率 —— 定高了烧限流配额（本轮实测
    700 次裸请求就触发 1429），定低了漏事件；而且与写请求抢同一个令牌桶
  · 心跳用 SSE 注释行（`:hb`），不占事件序号
  · **并发有上限**：SSE handler 会一直占着 HTTP 线程，不设限就等于给自己
    开了个拒绝服务的口子
  · 生存期有上限，到点主动收尾 —— 客户端不辞而别时线程不会被永久占住
"""
import pathlib
import sys

API = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

CASE_OLD = '                case "events"    -> handleEvents(ex, agent);'
CASE_NEW = ('                case "events"    -> handleEvents(ex, agent);\n'
            '                case "stream"    -> handleStream(ex, agent);')

METHOD = r'''
    /** 同时在流的 SSE 连接数上限。每个 handler 占一个 HTTP 线程。 */
    private static final java.util.concurrent.atomic.AtomicInteger liveStreams =
        new java.util.concurrent.atomic.AtomicInteger();
    private static final int MAX_LIVE_STREAMS = 8;

    /**
     * SSE 事件推送（DESIGN.md 41/731/853）。
     *
     * GET /v1/{agent}/stream?since=<seq>&limit=<n>&seconds=<s>
     *
     * 与 /events 轮询**共用同一套游标语义** —— since / nextSince /
     * cursor_expired(1006) 完全一致，所以客户端从轮询切过来不必改状态机。
     *
     * 事件的 JSON 直接复用 EventLog.Ev.toJson()，不另写一份序列化 ——
     * 两份序列化迟早会漂移，而 SSE 与轮询说的必须是同一件事。
     */
    private static void handleStream(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        long since = p.getLong("since", 0L);
        int limit = Math.min(Math.max(p.getInt("limit", 256), 1), 1024);
        double seconds = Math.max(1.0, Math.min(p.getFloat("seconds", 60f), 600f));

        int live = liveStreams.incrementAndGet();
        if (live > MAX_LIVE_STREAMS) {
            liveStreams.decrementAndGet();
            respond(ex, 503, Json.error(1007, "too many live streams (" + MAX_LIVE_STREAMS
                + " max); use /events polling instead"));
            return;
        }

        Team team = agent.team();
        Params vp = Params.of(ex);
        int viewId = resolveView(agent, vp);
        Team viewer = viewId < 0 ? null : Team.get(viewId);

        java.io.OutputStream os = null;
        try {
            ex.getResponseHeaders().set("Content-Type", "text/event-stream; charset=utf-8");
            ex.getResponseHeaders().set("Cache-Control", "no-cache");
            ex.sendResponseHeaders(200, 0);          // 0 = chunked，长度未知
            os = ex.getResponseBody();

            send(os, ":ok\n\n");
            send(os, "event: hello\ndata: {\"since\":" + since
                + ",\"agent\":" + Json.str(agent.id) + "}\n\n");

            long deadline = System.currentTimeMillis() + (long) (seconds * 1000);
            long lastBeat = System.currentTimeMillis();

            while (System.currentTimeMillis() < deadline) {
                // 游标过期：和轮询同样回 1006，并提示 resync —— 只是走流内事件
                if (EventLog.cursorExpired(since)) {
                    send(os, "event: error\ndata: {\"code\":1006,\"error\":"
                        + Json.str("cursor expired: events before seq " + since
                            + " have been discarded; resync with since=0") + "}\n\n");
                    since = 0;
                }

                var evs = EventLog.since(since, limit, viewer);
                if (evs.size > 0) {
                    for (int i = 0; i < evs.size; i++) {
                        var ev = evs.get(i);
                        send(os, "event: ev\ndata: " + ev.toJson() + "\n\n");
                        if (ev.seq > since) since = ev.seq;
                    }
                    send(os, "event: cursor\ndata: {\"nextSince\":" + since
                        + ",\"buffered\":" + EventLog.size() + "}\n\n");
                    lastBeat = System.currentTimeMillis();
                } else if (System.currentTimeMillis() - lastBeat > 10_000) {
                    send(os, ":hb\n\n");             // 保活，不占序号
                    lastBeat = System.currentTimeMillis();
                }
                Thread.sleep(120);                   // 采样间隔，不是「等待」
            }
            send(os, "event: end\ndata: {\"reason\":\"lifetime reached\","
                + "\"nextSince\":" + since + "}\n\n");
        } catch (Throwable t) {
            // 客户端断开是常态，不记日志
        } finally {
            liveStreams.decrementAndGet();
            try { if (os != null) os.close(); } catch (Throwable ignored) { }
            try { ex.close(); } catch (Throwable ignored) { }
        }
    }

    private static void send(java.io.OutputStream os, String s) throws java.io.IOException {
        os.write(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        os.flush();
    }
'''


def main():
    t = API.read_text(encoding="utf-8")
    if t.count(CASE_OLD) != 1:
        print(f"!! case 锚点 {t.count(CASE_OLD)} 次")
        return 1
    t = t.replace(CASE_OLD, CASE_NEW, 1)
    print("  ✓ 1 处  加 case \"stream\"")

    # 方法追加到 handleMaps 之前（那块区域确定在类体内）
    anchor = "    /**\n     * 列出所有地图的真实属性。"
    if t.count(anchor) != 1:
        print(f"!! 方法锚点 {t.count(anchor)} 次，未写盘")
        return 1
    t = t.replace(anchor, METHOD.rstrip() + "\n\n" + anchor, 1)
    print("  ✓ 1 处  插入 handleStream / send")
    API.write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
