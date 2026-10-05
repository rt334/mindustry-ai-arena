#!/usr/bin/env python3
"""修「成功的响应被回成 HTTP 400」。

现象（实测）：
    POST /v1/beta/place  block=shock-mine（核心 0 硅）
    → HTTP 400，body = {"ok":true,"data":{... "message":"queued shock-mine ..."}}

计划**确实排上了**，却带着 400。客户端按状态码分流就会把成功当失败；
arena.py 更是直接抛异常，AI 连 materials 分解都看不到。

原因：
    HttpApi 判定「这是不是错误响应」用的是全文子串匹配
        json.contains("\\"ok\\":false")
    而 /place 的成功响应里，materials.requirements 每一项都带
        {"item":"silicon","need":12,"have":0,"ok":false,"short":12}
    于是材料不足时（正是 missingMaterials 那个场景）成功响应被判成错误，
    再经 statusFor() 找不到 "code" → 落到 default → 400。

讽刺的是 statusFor 的注释专门写了「用解析而不是 contains 子串匹配 ——
子串匹配会把消息里偶然出现的 code 当成分错码」。同一个坑在另一处又踩了一次。

修法：错误响应一律由 Json.error 产出，必然以 `{"ok":false` 开头；
成功响应以 `{"ok":true` 开头。只看前缀即可，不必全文搜索。
"""
import pathlib
import sys

API = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

OLD = '            boolean isError = json != null && json.contains("\\"ok\\":false");'

NEW = """            // 只认开头，不能全文搜。成功响应里也会出现 "ok":false ——
            // /place 在材料不足时，materials.requirements 每一项都带着
            // {"ok":false,"short":N}，全文匹配会把「计划已排上」判成错误，
            // 回出 HTTP 400 配 body {"ok":true,...}，调用方按状态码分流就中招。
            boolean isError = json != null && json.startsWith("{\\"ok\\":false");"""


def main():
    t = API.read_text(encoding="utf-8")
    n = t.count(OLD)
    print(f"锚点命中 {n} 处（期望 2）")
    if n != 2:
        print("!! 数目不符，未写盘")
        return 1
    API.write_text(t.replace(OLD, NEW), encoding="utf-8")
    print("HttpApi：错误判定改为前缀匹配")
    return 0


if __name__ == "__main__":
    sys.exit(main())
