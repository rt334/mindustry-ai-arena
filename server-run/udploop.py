import socket, threading, time

result = {}
def server():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 55999))
    s.settimeout(5)
    try:
        data, addr = s.recvfrom(1024)
        result['server_recv'] = f"收到 {len(data)} 字节 from {addr}"
        s.sendto(b"pong", addr)
        result['server_sent'] = "已回 pong"
    except Exception as e:
        result['server_recv'] = f"失败: {e}"
    finally:
        s.close()

t = threading.Thread(target=server, daemon=True)
t.start()
time.sleep(0.5)

c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
c.bind(("127.0.0.1", 0))
c.settimeout(5)
try:
    c.sendto(b"ping", ("127.0.0.1", 55999))
    result['client_sent'] = f"已发送 ping，本地端口 {c.getsockname()[1]}"
    data, addr = c.recvfrom(1024)
    result['client_recv'] = f"收到 {data} from {addr}"
except Exception as e:
    result['client_recv'] = f"失败: {e}"
finally:
    c.close()
t.join(timeout=6)

for k in ['client_sent','server_recv','server_sent','client_recv']:
    print(f"   {k:14} {result.get(k,'(无)')}")
