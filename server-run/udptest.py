import socket
# 用 IPv4 明确发一个 UDP 包到 127.0.0.1:6567
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2)
try:
    s.sendto(b"\x00" * 8, ("127.0.0.1", 6567))
    print("   已用 IPv4 发送")
    data, addr = s.recvfrom(2048)
    print(f"   收到来自 {addr} 的 {len(data)} 字节")
except socket.timeout:
    print("   超时（Mindustry 只回协议内包，裸包无响应是正常的）")
except Exception as e:
    print(f"   错误: {e}")
finally:
    s.close()
