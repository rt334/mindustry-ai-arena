import socket, struct, time
# Mindustry 的 UDP 握手包类型：先发 StreamBegin 之类的探测
# 这里只是确认 socket 层面能否互通
for fam, addr in [(socket.AF_INET, "127.0.0.1")]:
    s = socket.socket(fam, socket.SOCK_DGRAM)
    s.settimeout(3)
    try:
        s.sendto(b"\xff" * 16, (addr, 6567))
        print(f"   IPv4 -> {addr}:6567 已发送")
    except Exception as e:
        print(f"   IPv4 发送失败: {e}")
    finally:
        s.close()
time.sleep(0.5)
print("   完成（Mindustry 只回协议内包，无响应属正常）")
