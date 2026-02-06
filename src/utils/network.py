import socket
import contextlib

def get_free_port(start_port=8000, max_port=9000):
    """
    寻找一个可用的端口。
    从 start_port 开始尝试，直到 max_port。
    """
    for port in range(start_port, max_port):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            try:
                # 尝试绑定端口，如果成功则说明端口可用
                # SO_REUSEADDR 允许立即重用端口
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    raise IOError(f"No free ports found in range {start_port}-{max_port}")

def get_local_ip():
    """获取本机局域网 IP (优先返回 192.168.x.x)"""
    try:
        # 方法1: 获取所有网卡 IP
        hostname = socket.gethostname()
        _, _, ips = socket.gethostbyname_ex(hostname)
        
        # 优先级排序: 192.168 > 10. > 172.
        for ip in ips:
            if ip.startswith("192.168."):
                return ip
        for ip in ips:
            if ip.startswith("10.") and not ip.startswith("10.0.0.0"): # 排除某些特殊 Docker/VPN 网段? 这里的判断比较宽泛
                return ip
        for ip in ips:
            if ip.startswith("172."):
                return ip
                
        # 方法2: 如果上面没找到合适的，回退到 UDP 连接探测
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
