#!/usr/bin/env python3
"""
AI 竞技场 · 零依赖 WebSocket 客户端。

只用标准库 —— 这台机器上没有 websockets / aiohttp / requests，
所以 RFC 6455 的握手和分帧自己实现。代码不多，而且过程完全透明。

用法：
    python ws-client.py --agent alpha --token <token>
    python ws-client.py --agent alpha --token <token> --hz 10 --seconds 30

它做的事：
    1. 握手（token 走 query string —— 浏览器也没法给 WS 握手设自定义头）
    2. 订阅频道
    3. 收帧并按频道打印摘要
    4. 发一条命令（place），验证双向通路
"""

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import time

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WsError(Exception):
    pass


class WsClient:
    """最小可用的 WebSocket 客户端（文本帧）。"""

    def __init__(self, host, port, path, timeout=10.0):
        self.host = host
        self.port = port
        self.path = path
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._buf = b""
        self._handshake()

    # ---------------------------------------------------------------- 握手

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(req.encode())

        # 读到 \r\n\r\n 为止
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WsError("握手时连接被关闭")
            head += chunk
        head, _, rest = head.partition(b"\r\n\r\n")
        self._buf = rest

        text = head.decode("latin-1")
        status = text.split("\r\n")[0]
        if "101" not in status:
            raise WsError(f"握手失败: {status}")

        # 校验 Sec-WebSocket-Accept（协议要求客户端验证）
        expect = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        got = ""
        for line in text.split("\r\n")[1:]:
            if line.lower().startswith("sec-websocket-accept:"):
                got = line.split(":", 1)[1].strip()
        if got != expect:
            raise WsError(f"Sec-WebSocket-Accept 不匹配: 期望 {expect}, 收到 {got}")

    # ---------------------------------------------------------------- 收

    def _read_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WsError("连接已关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
        """读一帧，返回 (opcode, payload bytes)。"""
        b0, b1 = self._read_exact(2)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F

        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]

        mask = self._read_exact(4) if masked else None
        payload = self._read_exact(length)
        if mask:
            payload = bytes(c ^ mask[i & 3] for i, c in enumerate(payload))
        return opcode, payload

    def recv_text(self):
        """收一条文本消息；自动回 pong。返回 None 表示连接结束。"""
        while True:
            op, payload = self.recv()
            if op == OP_CLOSE:
                return None
            if op == OP_PING:
                self.send_raw(OP_PONG, payload)
                continue
            if op == OP_PONG:
                continue
            if op in (OP_TEXT, OP_BIN):
                return payload.decode("utf-8", "replace")

    # ---------------------------------------------------------------- 发

    def send_raw(self, opcode, payload=b""):
        """客户端发的帧**必须**带掩码（RFC 6455 5.1）。"""
        header = bytearray()
        header.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(c ^ mask[i & 3] for i, c in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def send_json(self, obj):
        self.send_raw(OP_TEXT, json.dumps(obj).encode("utf-8"))

    def close(self):
        try:
            self.send_raw(OP_CLOSE)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def connect_with_retry(host, port, url_path, max_retries, base_delay, max_delay):
    """建立连接，失败按指数退避重试。返回 (client, attempts)。"""
    attempt = 0
    while True:
        try:
            c = WsClient(host, port, url_path)
            return c, attempt
        except Exception as e:
            if attempt >= max_retries:
                raise
            wait = min(base_delay * (2 ** attempt), max_delay)
            print(f"[ws] 连接失败: {e}；{wait:.1f}s 后重试 "
                  f"(第 {attempt + 1}/{max_retries} 次)")
            time.sleep(wait)
            attempt += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7200)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--hz", type=int, default=5)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--channels",
                    default="state,units,buildings,factory,drill,events")
    ap.add_argument("--test-command", action="store_true",
                    help="发一条 place 命令验证双向通路")
    ap.add_argument("--max-retries", type=int, default=8,
                    help="单次连接失败的重试上限（每次退避翻倍）")
    ap.add_argument("--base-delay", type=float, default=0.5)
    ap.add_argument("--max-delay", type=float, default=10.0)
    args = ap.parse_args()

    url_path = f"/ws?token={args.token}"
    print(f"[ws] 连接 ws://{args.host}:{args.port}{url_path[:32]}…")
    c, attempts = connect_with_retry(args.host, args.port, url_path,
                                     args.max_retries, args.base_delay,
                                     args.max_delay)
    print(f"[ws] 握手成功 (101 + Sec-WebSocket-Accept 已校验)"
          + (f"  重试 {attempts} 次" if attempts else ""))

    def subscribe(client):
        client.send_json({"op": "sub",
                          "channels": args.channels.split(","),
                          "hz": args.hz})
        if args.test_command:
            client.send_json({"op": "cmd", "id": 1, "endpoint": "state",
                              "params": {}})

    subscribe(c)

    counts = {}
    deadline = time.time() + args.seconds
    total = 0
    started = time.time()
    reconnects = 0

    while time.time() < deadline:
        try:
            msg = c.recv_text()
        except (socket.timeout, WsError) as e:
            # 服务端重启（改 mod 后很常见）不该结束会话 —— 重连并重新订阅
            print(f"[ws] 断线: {e}；重连…")
            try:
                c.close()
            except Exception:
                pass
            try:
                c, attempts = connect_with_retry(
                    args.host, args.port, url_path,
                    args.max_retries, args.base_delay, args.max_delay)
            except Exception as ce:
                print(f"[ws] 重连失败，结束: {ce}")
                break
            reconnects += 1
            counts.clear()          # 重连后频道会重发，计数从头来
            subscribe(c)
            print(f"[ws] 已重连（第 {reconnects} 次），已重新订阅")
            continue
        if msg is None:
            print("[ws] 服务端关闭连接；重连…")
            try:
                c.close()
            except Exception:
                pass
            try:
                c, attempts = connect_with_retry(
                    args.host, args.port, url_path,
                    args.max_retries, args.base_delay, args.max_delay)
            except Exception as ce:
                print(f"[ws] 重连失败，结束: {ce}")
                break
            reconnects += 1
            counts.clear()
            subscribe(c)
            print(f"[ws] 已重连（第 {reconnects} 次），已重新订阅")
            continue

        total += 1
        try:
            obj = json.loads(msg)
        except json.JSONDecodeError:
            print(f"[ws] 非 JSON: {msg[:120]}")
            continue

        op = obj.get("op")
        if op == "hello":
            print(f"[ws] hello: agent={obj.get('agent')} team={obj.get('team')} "
                  f"wsPort={obj.get('wsPort')} apiPort={obj.get('apiPort')}")
            continue
        if op == "subok":
            print(f"[ws] 订阅成功: {obj.get('channels')} @ {obj.get('hz')}Hz")
            continue
        if op == "pong":
            continue
        if op == "err":
            print(f"[ws] 服务端错误: {obj.get('message')}")
            continue
        if op == "ack":
            body = obj.get("body")
            print(f"[ws] ack id={obj.get('id')} status={obj.get('status')} "
                  f"body={json.dumps(body, ensure_ascii=False)[:160]}")
            continue

        ch = obj.get("ch")
        if ch:
            counts[ch] = counts.get(ch, 0) + 1
            if counts[ch] == 1:
                data = obj.get("data")
                n = len(data) if isinstance(data, list) else 1
                print(f"[ws] 首次收到 {ch} 频道: {n} 项  "
                      f"{json.dumps(data, ensure_ascii=False)[:140]}")

    elapsed = max(0.001, time.time() - started)
    print()
    print(f"[ws] {elapsed:.1f} 秒共收 {total} 帧  ({total/elapsed:.1f} 帧/秒)"
          + (f"  重连 {reconnects} 次" if reconnects else ""))
    for ch in sorted(counts):
        print(f"       {ch:<12} {counts[ch]:>5} 帧  {counts[ch]/elapsed:>6.1f}/秒")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
