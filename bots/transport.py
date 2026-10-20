#!/usr/bin/env python3
"""bot 的传输层：WebSocket 连接、订阅、命令流水线、自动重连。

**为什么 bot 走 WS 而不是 HTTP 轮询**（`docs/TODO.md` §十六实测）：
- 下行：WS 六通道约 52 帧/秒/通道，一轮全通道约 19 ms；
        而 HTTP 串行轮询同样五个端点 P50 47.8 ms（约 21 Hz 上限）。
- 上行：WS 的 `cmd` 是**异步**的（带 id，回 `ack`），可以连续发多条不等回复；
        HTTP 必须一发一收。
  ⚠ 但 `cmd` 在服务端会转成一次本机 HTTP 调用（`WsServer.java:383`），
  所以它省的是**客户端等待**，不是链路 —— 别指望它比本地 HTTP 快多少。

这个类是从仓库根的 `ws-client.py`（演示脚本）正式化来的。两份的差别：
demo 只打印摘要；这里把帧分发给 `World`，把 `ack` 交给调用方，并负责重连。

### 订阅频率的实际上限（实测，见 TODO §16.2）

`hz=60` 实得约 52 帧/秒；`hz<=10` 基本精确。bot 默认用 20，够用且不浪费。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import socket
import struct
import threading
import time
import urllib.request

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WsError(Exception):
    pass


class WsClient:
    """零依赖 WebSocket 客户端（文本帧，RFC 6455）。"""

    def __init__(self, host, port, path, timeout=10.0):
        self.host = host
        self.port = port
        self.path = path
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._buf = b""
        self._handshake()

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

        expect = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        got = ""
        for line in text.split("\r\n")[1:]:
            if line.lower().startswith("sec-websocket-accept:"):
                got = line.split(":", 1)[1].strip()
        if got != expect:
            raise WsError(f"Sec-WebSocket-Accept 不匹配: 期望 {expect}, 收到 {got}")

    def _read_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WsError("连接已关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
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

    def send_raw(self, opcode, payload=b""):
        """客户端发的帧必须带掩码（RFC 6455 5.1）。"""
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


def fetch_token(agent, host="127.0.0.1", port=7199, timeout=5.0):
    """从无鉴权端点取自己的 token。绝不读配置文件里别人的 token。"""
    url = f"http://{host}:{port}/v1/bridge/{agent}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    data = body.get("data") or {}
    tok = data.get("token")
    if not tok:
        raise WsError(f"/v1/bridge/{agent} 没给 token：{body}")
    return tok, data


class ArenaLink:
    """一条到竞技场的常驻连接：收帧 → 回调，发命令 → 排队等 ack。

    **线程模型**：一个读线程负责收帧与重连；主线程（bot 决策循环）
    只读 `on_frame` 回调写下的数据、只调 `send_cmd`。
    """

    def __init__(self, agent, host="127.0.0.1", ws_port=7200, http_port=7199,
                 channels=("state", "units", "buildings", "factory", "drill",
                           "events", "rates", "stalls"),
                 hz=20):
        self.agent = agent
        self.host = host
        self.ws_port = ws_port
        self.http_port = http_port
        self.channels = list(channels)
        self.hz = hz

        self.token, self.bridge = fetch_token(agent, host, http_port)

        self.on_frame = None        # (ch, data, tick) -> None，在读线程里调用
        self.on_hello = None        # (info_dict) -> None
        self.on_error = None        # (message) -> None
        self.acks: "queue.Queue[dict]" = queue.Queue()

        self._ws = None
        self._stop = threading.Event()
        self._thread = None
        self._next_id = 1
        self._send_lock = threading.Lock()

        self.frames = 0
        self.reconnects = 0
        self.last_frame_at = 0.0

    # ---------------------------------------------------------------- 生命周期

    def start(self):
        self._thread = threading.Thread(target=self._run, name="bot-ws", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    # ---------------------------------------------------------------- 读线程

    def _run(self):
        delay = 0.5
        while not self._stop.is_set():
            try:
                self._ws = WsClient(self.host, self.ws_port,
                                    f"/ws?token={self.token}", timeout=10.0)
                self._ws.sock.settimeout(0.5)
                self._ws.send_json({"op": "sub", "channels": self.channels,
                                    "hz": self.hz})
                delay = 0.5
                self._pump()
            except Exception as e:
                if not self._stop.is_set():
                    if self.on_error:
                        self.on_error(f"连接中断: {e}")
            finally:
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:
                    pass
                self._ws = None

            if self._stop.is_set():
                break
            self.reconnects += 1
            # 退避，但可被 stop 打断
            waited = 0.0
            while waited < delay and not self._stop.is_set():
                time.sleep(0.1)
                waited += 0.1
            delay = min(delay * 2, 10.0)

    def _pump(self):
        while not self._stop.is_set():
            try:
                msg = self._ws.recv_text()
            except socket.timeout:
                continue                    # 超时只是没帧，不是断线
            if msg is None:
                raise WsError("服务端关闭连接")

            try:
                obj = json.loads(msg)
            except json.JSONDecodeError:
                continue

            op = obj.get("op")
            if op == "hello":
                if self.on_hello:
                    self.on_hello(obj)
                continue
            if op == "subok":
                continue
            if op == "ack":
                self.acks.put(obj)
                continue
            if op == "err":
                if self.on_error:
                    self.on_error(f"服务端: {obj.get('message')}")
                continue
            if op == "pong":
                continue

            ch = obj.get("ch")
            if ch:
                self.frames += 1
                self.last_frame_at = time.time()
                if self.on_frame:
                    self.on_frame(ch, obj.get("data"), obj.get("tick"))

    # ---------------------------------------------------------------- 写

    def send_cmd(self, endpoint, params=None):
        """发一条命令，**不等结果**。返回 id；ack 从 `self.acks` 取。

        `params` 的值会被转成字符串 —— 服务端只按 map[string]string 解析。
        """
        params = params or {}
        with self._send_lock:
            ws = self._ws
            if ws is None:
                raise WsError("连接未就绪")
            cid = self._next_id
            self._next_id += 1
            ws.send_json({
                "op": "cmd",
                "id": cid,
                "endpoint": endpoint,
                "params": {str(k): str(v) for k, v in params.items()},
            })
            return cid

    def drain_acks(self, limit=200):
        """取走当前所有 ack（不阻塞），返回列表。"""
        out = []
        while len(out) < limit:
            try:
                out.append(self.acks.get_nowait())
            except queue.Empty:
                break
        return out
