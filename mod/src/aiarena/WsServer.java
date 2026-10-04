package aiarena;

import arc.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * AI 竞技场 · WebSocket 服务端（RFC 6455，零依赖）。
 *
 * 为什么要自己写：mod 的 HTTP 端点是 JDK 内置的
 * {@code com.sun.net.httpserver.HttpServer}，它**不支持连接劫持**，
 * 所以没法在它上面做 Upgrade。必须另开一个裸 ServerSocket 自己实现握手与分帧。
 *
 * 和 REST 的分工：
 *   REST    一次性查询（/content、/map、/ore、/block…），简单、无状态
 *   WS      高频状态流 + 命令复用同一条连接
 *
 * 为什么 WS 比轮询好（实测数据）：
 *   旧 ai-client.py 每拍发 4 个 GET（state/units/buildings/map），
 *   4 个 agent 就是 16 req/s，每个请求带一整套 HTTP 头。
 *   而且轮询周期决定了反应延迟 —— 1 秒一拍，敌人出现要最多 1 秒才知道。
 *   WS 是服务端按 tick 推，延迟降到「一帧」。
 *
 * 协议（全部是 JSON 文本帧）：
 *
 *   客户端 -> 服务端
 *     {"op":"sub","channels":["state","units","buildings","factory","drill","events"],"hz":5}
 *     {"op":"cmd","id":42,"endpoint":"place","params":{"x":60,"y":100,"block":"conveyor"}}
 *     {"op":"ping"}
 *
 *   服务端 -> 客户端
 *     {"ch":"units","tick":1234,"data":[...]}
 *     {"op":"ack","id":42,"ok":true,"status":200,"data":{...}}
 *     {"op":"hello","agent":"alpha","team":"sharded","channels":[...],"hz":5}
 *     {"op":"pong"}
 *     {"op":"err","message":"..."}
 *
 * 鉴权：握手时在 query string 里带 token —— /ws?token=xxx。
 * 浏览器没法给 WebSocket 握手设自定义头，所以用 query string 是通行做法。
 *
 * 线程模型：
 *   接受线程        1 个，accept 新连接
 *   读线程          每连接 1 个，解析客户端帧
 *   写线程          每连接 1 个，从队列取帧发送
 *   游戏主线程      按订阅频率调 push()，只往队列里塞，不直接写 socket
 */
public class WsServer {

    /** 支持的频道。 */
    private static final Set<String> CHANNELS =
        new LinkedHashSet<>(Arrays.asList("state", "units", "buildings", "factory", "drill", "events"));

    /** RFC 6455 规定的握手魔术串。 */
    private static final String WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

    private static ServerSocket socket;
    private static Thread acceptThread;
    private static volatile boolean running = false;

    /** 所有活跃连接。游戏线程遍历它推送，所以用并发容器。 */
    private static final List<Conn> conns = new CopyOnWriteArrayList<>();

    private static HttpClient http;
    private static int httpPort;

    // ---------------------------------------------------------------- 生命周期

    public static void start(int port, int apiPort) {
        if (running) return;
        httpPort = apiPort;
        http = HttpClient.newBuilder().connectTimeout(java.time.Duration.ofSeconds(3)).build();

        try {
            socket = new ServerSocket();
            socket.setReuseAddress(true);
            socket.bind(new InetSocketAddress(AIArena.bind, port));
        } catch (Throwable t) {
            AIArena.log("WsServer bind failed on " + port + ": " + t);
            return;
        }

        running = true;
        acceptThread = new Thread(WsServer::acceptLoop, "ai-arena-ws-accept");
        acceptThread.setDaemon(true);
        acceptThread.start();
        AIArena.log("WebSocket listening on ws://" + AIArena.bind + ":" + port + "/ws");
    }

    public static void stop() {
        running = false;
        for (Conn c : conns) c.close();
        conns.clear();
        try { if (socket != null) socket.close(); } catch (Throwable ignored) {}
    }

    public static int connectionCount() { return conns.size(); }

    private static void acceptLoop() {
        while (running) {
            try {
                Socket s = socket.accept();
                s.setTcpNoDelay(true);
                // 握手放到独立线程，避免一个慢客户端卡住 accept
                Thread t = new Thread(() -> handshake(s), "ai-arena-ws-handshake");
                t.setDaemon(true);
                t.start();
            } catch (Throwable t) {
                if (running) AIArena.log("ws accept error: " + t);
            }
        }
    }

    // ---------------------------------------------------------------- 握手

    private static void handshake(Socket s) {
        try {
            InputStream in = s.getInputStream();
            OutputStream out = s.getOutputStream();

            // 读 HTTP 请求头（到空行为止）。限制大小，别让恶意请求打爆内存。
            ByteArrayOutputStream head = new ByteArrayOutputStream();
            int state = 0;   // 计数连续 CRLFCRLF
            int b;
            while ((b = in.read()) != -1 && head.size() < 8192) {
                head.write(b);
                if (b == '\r' || b == '\n') {
                    state++;
                    if (state == 4) break;
                } else {
                    state = 0;
                }
            }

            String raw = head.toString(StandardCharsets.ISO_8859_1);
            String[] lines = raw.split("\r?\n");
            if (lines.length == 0) { s.close(); return; }

            String requestLine = lines[0];
            Map<String, String> headers = new HashMap<>();
            for (int i = 1; i < lines.length; i++) {
                int c = lines[i].indexOf(':');
                if (c <= 0) continue;
                headers.put(lines[i].substring(0, c).trim().toLowerCase(Locale.ROOT),
                            lines[i].substring(c + 1).trim());
            }

            String key = headers.get("sec-websocket-key");
            if (key == null) {
                writeRaw(out, "HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
                s.close();
                return;
            }

            // 从 query string 取 token
            String token = null;
            try {
                String[] parts = requestLine.split(" ");
                if (parts.length >= 2) {
                    String path = parts[1];
                    int q = path.indexOf('?');
                    if (q >= 0) {
                        for (String kv : path.substring(q + 1).split("&")) {
                            int e = kv.indexOf('=');
                            if (e > 0 && kv.substring(0, e).equals("token")) {
                                token = java.net.URLDecoder.decode(kv.substring(e + 1), StandardCharsets.UTF_8);
                            }
                        }
                    }
                }
            } catch (Throwable ignored) {}

            AIArena.Agent agent = token == null ? null : AIArena.agentByToken(token);
            if (agent == null) {
                writeRaw(out, "HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
                s.close();
                AIArena.log("ws handshake rejected: bad token");
                return;
            }

            String accept = Base64.getEncoder().encodeToString(
                MessageDigest.getInstance("SHA-1").digest((key + WS_GUID).getBytes(StandardCharsets.ISO_8859_1)));

            writeRaw(out,
                "HTTP/1.1 101 Switching Protocols\r\n" +
                "Upgrade: websocket\r\n" +
                "Connection: Upgrade\r\n" +
                "Sec-WebSocket-Accept: " + accept + "\r\n\r\n");

            Conn conn = new Conn(s, in, out, agent);
            conns.add(conn);
            conn.start();
            conn.send("{\"op\":\"hello\",\"agent\":" + Json.str(agent.id)
                      + ",\"team\":" + Json.str(agent.team() == null ? "" : agent.team().name)
                      + ",\"channels\":[\"state\",\"units\",\"buildings\",\"factory\",\"drill\",\"events\"]"
                      + ",\"hz\":5,\"wsPort\":" + socket.getLocalPort()
                      + ",\"apiPort\":" + httpPort + "}");
            AIArena.log("ws client connected: " + agent.id
                        + " (" + conns.size() + " active)");

        } catch (Throwable t) {
            AIArena.log("ws handshake failed: " + t);
            try { s.close(); } catch (Throwable ignored) {}
        }
    }

    private static void writeRaw(OutputStream out, String s) throws IOException {
        out.write(s.getBytes(StandardCharsets.ISO_8859_1));
        out.flush();
    }

    // ---------------------------------------------------------------- 推送

    /**
     * 游戏主线程每帧调用。按每个连接的订阅频率推送它订阅的频道。
     *
     * 必须跑在主线程 —— channelJson 会读 Vars.state / Groups。
     */
    public static void tick() {
        if (!running || conns.isEmpty()) return;
        if (mindustry.Vars.state == null || !mindustry.Vars.state.isGame()) return;

        long now = System.currentTimeMillis();
        for (Conn c : conns) {
            try {
                if (now - c.lastPush < c.intervalMs) continue;
                c.lastPush = now;

                for (String ch : c.channels) {
                    String data = HttpApi.channelJson(ch, c.agent);
                    if (data == null) continue;
                    c.send("{\"ch\":" + Json.str(ch)
                           + ",\"tick\":" + mindustry.Vars.state.tick
                           + ",\"data\":" + data + "}");
                }
            } catch (Throwable t) {
                // 单个连接出错不能影响其它连接，更不能把异常抛回游戏主循环
                Log.err("ws push failed: " + t);
            }
        }
    }

    // ---------------------------------------------------------------- 连接

    private static final class Conn {
        final Socket socket;
        final InputStream in;
        final OutputStream out;
        final AIArena.Agent agent;

        final Set<String> channels = new LinkedHashSet<>(Arrays.asList("state", "units", "buildings"));
        final BlockingQueue<String> outbox = new LinkedBlockingQueue<>(512);
        final AtomicBoolean closed = new AtomicBoolean(false);

        volatile int hz = 5;
        volatile long intervalMs = 200;
        volatile long lastPush = 0;

        Thread writer, reader;

        Conn(Socket socket, InputStream in, OutputStream out, AIArena.Agent agent) {
            this.socket = socket;
            this.in = in;
            this.out = out;
            this.agent = agent;
        }

        void start() {
            writer = new Thread(this::writeLoop, "ai-arena-ws-write");
            writer.setDaemon(true);
            writer.start();

            reader = new Thread(this::readLoop, "ai-arena-ws-read");
            reader.setDaemon(true);
            reader.start();
        }

        /** 入队。满就丢最旧的 —— 状态帧是「最新优先」，积压没有意义。 */
        void send(String json) {
            if (closed.get()) return;
            if (!outbox.offer(json)) {
                outbox.poll();
                outbox.offer(json);
            }
        }

        private void writeLoop() {
            try {
                while (!closed.get()) {
                    String msg = outbox.poll(1, TimeUnit.SECONDS);
                    if (msg == null) continue;
                    writeFrame(out, 0x1, msg.getBytes(StandardCharsets.UTF_8));
                }
            } catch (InterruptedException ignored) {
            } catch (Throwable t) {
                close();
            }
        }

        private void readLoop() {
            try {
                while (!closed.get()) {
                    Frame f = readFrame(in);
                    if (f == null) break;

                    if (f.opcode == 0x8) break;                       // close
                    if (f.opcode == 0x9) { writeFrame(out, 0xA, f.payload); continue; }  // ping -> pong
                    if (f.opcode == 0xA) continue;                    // pong
                    if (f.opcode != 0x1 && f.opcode != 0x2) continue; // 只要 text/binary

                    handleMessage(new String(f.payload, StandardCharsets.UTF_8));
                }
            } catch (Throwable ignored) {
            } finally {
                close();
            }
        }

        private void handleMessage(String text) {
            try {
                // Mindustry 用的是 arc 自带的 Jval（arc.util.serialization），
                // 不是 JsonReader。
                var obj = arc.util.serialization.Jval.read(text);
                String op = obj.getString("op", "");

                switch (op) {
                    case "ping" -> send("{\"op\":\"pong\"}");

                    case "sub" -> {
                        var chs = obj.get("channels");
                        if (chs != null && chs.isArray()) {
                            channels.clear();
                            for (var v : chs.asArray()) {
                                String name = v.asString();
                                if (CHANNELS.contains(name)) channels.add(name);
                            }
                        }
                        int wantHz = obj.getInt("hz", hz);
                        hz = Math.max(1, Math.min(60, wantHz));
                        intervalMs = 1000L / hz;
                        send("{\"op\":\"subok\",\"channels\":" + jsonArray(channels) + ",\"hz\":" + hz + "}");
                    }

                    case "cmd" -> {
                        int id = obj.getInt("id", -1);
                        String endpoint = obj.getString("endpoint", "");
                        Map<String, String> params = new LinkedHashMap<>();
                        var ps = obj.get("params");
                        if (ps != null && ps.isObject()) {
                            for (var e : ps.asObject()) {
                                params.put(e.key, e.value.asString());
                            }
                        }
                        // 命令走内部 HTTP 调回 REST —— 复用全部 25 个端点，
                        // 也自动继承它的鉴权、可见性校验和错误码。
                        dispatchAsync(id, endpoint, params);
                    }

                    default -> send("{\"op\":\"err\",\"message\":" + Json.str("unknown op: " + op) + "}");
                }
            } catch (Throwable t) {
                send("{\"op\":\"err\",\"message\":" + Json.str("bad message: " + t) + "}");
            }
        }

        private void dispatchAsync(int id, String endpoint, Map<String, String> params) {
            Thread t = new Thread(() -> {
                try {
                    StringBuilder url = new StringBuilder("http://127.0.0.1:" + httpPort
                        + "/v1/" + agent.id + "/" + endpoint);
                    boolean firstParam = true;
                    for (var e : params.entrySet()) {
                        url.append(firstParam ? '?' : '&');
                        firstParam = false;
                        url.append(java.net.URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8))
                           .append('=').append(java.net.URLEncoder.encode(e.getValue(), StandardCharsets.UTF_8));
                    }
                    // token 走 Authorization 头，不是 query string ——
                    // REST 端点只认 Bearer 头，放 query 里会 401。
                    // 这里的 agent.token 就是握手时验过的那个，不用再查。
                    var b = HttpRequest.newBuilder(URI.create(url.toString()))
                        .timeout(java.time.Duration.ofSeconds(20))
                        .header("Authorization", "Bearer " + agent.token);
                    b = params.isEmpty()
                        ? b.GET()
                        : b.POST(HttpRequest.BodyPublishers.noBody());
                    var resp = http.send(b.build(), HttpResponse.BodyHandlers.ofString());

                    send("{\"op\":\"ack\",\"id\":" + id + ",\"status\":" + resp.statusCode()
                         + ",\"body\":" + resp.body() + "}");
                } catch (Throwable ex) {
                    send("{\"op\":\"ack\",\"id\":" + id + ",\"status\":0"
                         + ",\"body\":{\"ok\":false,\"code\":1500,\"error\":" + Json.str(String.valueOf(ex)) + "}}");
                }
            }, "ai-arena-ws-cmd");
            t.setDaemon(true);
            t.start();
        }

        void close() {
            if (!closed.compareAndSet(false, true)) return;
            conns.remove(this);
            try { socket.close(); } catch (Throwable ignored) {}
            AIArena.log("ws client disconnected: " + agent.id + " (" + conns.size() + " active)");
        }
    }

    private static String jsonArray(Collection<String> xs) {
        StringBuilder sb = new StringBuilder("[");
        boolean f = true;
        for (String s : xs) {
            if (!f) sb.append(',');
            f = false;
            sb.append(Json.str(s));
        }
        return sb.append(']').toString();
    }

    // ---------------------------------------------------------------- 帧编解码

    private static final class Frame {
        int opcode;
        byte[] payload;
    }

    /**
     * 读一个帧。
     *
     * 客户端 -> 服务端的帧**必须**带掩码（RFC 6455 5.1），不带就直接拒绝 ——
     * 这是协议硬性要求，也是防缓存污染攻击的设计。
     */
    private static Frame readFrame(InputStream in) throws IOException {
        int b0 = in.read();
        if (b0 < 0) return null;
        int b1 = in.read();
        if (b1 < 0) return null;

        Frame f = new Frame();
        f.opcode = b0 & 0x0F;
        boolean masked = (b1 & 0x80) != 0;
        long len = b1 & 0x7F;

        if (len == 126) {
            len = ((long) readByte(in) << 8) | readByte(in);
        } else if (len == 127) {
            len = 0;
            for (int i = 0; i < 8; i++) len = (len << 8) | readByte(in);
        }

        // 单帧上限 4MB，防止恶意长度打爆内存
        if (len < 0 || len > 4L * 1024 * 1024) throw new IOException("frame too large: " + len);

        byte[] mask = null;
        if (masked) {
            mask = new byte[4];
            readFully(in, mask);
        }

        byte[] payload = new byte[(int) len];
        readFully(in, payload);

        if (masked) {
            for (int i = 0; i < payload.length; i++) {
                payload[i] ^= mask[i & 3];
            }
        }

        f.payload = payload;
        return f;
    }

    /** 服务端 -> 客户端的帧**不能**带掩码。 */
    private static synchronized void writeFrame(OutputStream out, int opcode, byte[] payload) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream(payload.length + 10);
        buf.write(0x80 | opcode);   // FIN + opcode

        int len = payload.length;
        if (len < 126) {
            buf.write(len);
        } else if (len < 65536) {
            buf.write(126);
            buf.write((len >>> 8) & 0xFF);
            buf.write(len & 0xFF);
        } else {
            buf.write(127);
            for (int i = 7; i >= 0; i--) buf.write((int) (((long) len >>> (8 * i)) & 0xFF));
        }
        buf.write(payload, 0, payload.length);
        out.write(buf.toByteArray());
        out.flush();
    }

    private static int readByte(InputStream in) throws IOException {
        int b = in.read();
        if (b < 0) throw new IOException("eof");
        return b;
    }

    private static void readFully(InputStream in, byte[] dst) throws IOException {
        int off = 0;
        while (off < dst.length) {
            int n = in.read(dst, off, dst.length - off);
            if (n < 0) throw new IOException("eof");
            off += n;
        }
    }
}
