#!/usr/bin/env python3
"""修正进度速率：采样点必须「进度」与「时刻」配套。

原实现的 bug：
    prev   = planProgress.get(key)   ← 每帧都更新
    prevMs = planSampleMs.get(key)   ← 每 100ms 才更新
两者不在同一时刻，于是 (prog - prev) 是**一帧**的进度差，除以**100ms**，
速率被低估约 6 倍（100ms / 16.7ms）。

实测印证：scatter 理论施工 1.23s（约 0.81 进度/秒），
反推出来却是 7.69s（约 0.13 进度/秒），正好差 6 倍。

改成一个成对的采样表：{key -> [progress, millis]}，两个值同进同出。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\StallWatch.java")

FIELD_OLD = """    /** key -> 上次算速率时的毫秒时刻。用来把「进度差」变成「进度/秒」。 */
    private static final Map<String, Long> planSampleMs = new HashMap<>();"""

FIELD_NEW = """    /**
     * key -> [progress, millis]，**配套**保存上一次算速率的采样点。
     *
     * 必须成对：进度取一帧前的、时刻取 100ms 前的，速率就会差好几个数量级
     * （实测差 6 倍 —— 因为 100ms 里有 6 帧）。
     */
    private static final Map<String, float[]> planSample = new HashMap<>();"""

RATE_OLD = """                // 顺带算进度变化率 —— 同样是两次采样的差，不额外增加观测成本。
                // 这是「盯着进度条看它涨多快」，真人抬眼就能做。
                Long prevMs = planSampleMs.get(key);
                if (prev != null && prevMs != null) {
                    long dt = now - prevMs;
                    if (dt >= 100L) {              // 太短噪声大，太长又跟不上快方块（conveyor 只建 0.01s）
                        float r = (prog - prev) / (dt / 1000f);
                        if (r > 0f) planRate.put(key, r);
                        else planRate.remove(key);
                        planSampleMs.put(key, now);
                    }
                } else {
                    planSampleMs.put(key, now);
                }"""

RATE_NEW = """                // 顺带算进度变化率 —— 同样是两次采样的差，不额外增加观测成本。
                // 这是「盯着进度条看它涨多快」，真人抬眼就能做。
                //
                // 采样点必须成对取：进度和时刻来自同一次记录，否则分子分母错配。
                float[] s = planSample.get(key);
                if (s != null) {
                    long dt = now - (long) s[1];
                    if (dt >= 100L) {          // 太短噪声大，太长又跟不上快方块
                        float r = (prog - s[0]) / (dt / 1000f);
                        if (r > 1e-5f) planRate.put(key, r);
                        else planRate.remove(key);
                        planSample.put(key, new float[]{prog, now});
                    }
                } else {
                    planSample.put(key, new float[]{prog, now});
                }"""

CLEAN_OLD = """        planSampleMs.keySet().removeIf(k -> !seen.contains(k));"""
CLEAN_NEW = """        planSample.keySet().removeIf(k -> !seen.contains(k));"""

CLEAR_OLD = """        planSampleMs.clear();"""
CLEAR_NEW = """        planSample.clear();"""

RULES = [
    (FIELD_OLD, FIELD_NEW, "字段改成配套采样表"),
    (RATE_OLD, RATE_NEW, "速率计算用成对的采样点"),
    (CLEAN_OLD, CLEAN_NEW, "清理"),
    (CLEAR_OLD, CLEAR_NEW, "clear"),
]


def main():
    text = S.read_text(encoding="utf-8")
    bad = []
    for old, new, label in RULES:
        n = text.count(old)
        if n != 1:
            bad.append(f"{n} 次命中: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有问题，未写盘")
        return 1
    S.write_text(text, encoding="utf-8")
    print("\nStallWatch.java 已修正")
    return 0


if __name__ == "__main__":
    sys.exit(main())
