import asyncio
import base64
from urllib.parse import urlparse
import time

MAX_DELAY = 5000  # 最大延迟毫秒

# 简单判断是否支持的协议（你可根据实际扩展）
def is_supported_node(url: str) -> bool:
    return url.startswith((
        "vmess://", "ss://", "trojan://", "vless://", "hysteria2://"
    ))

# 解析base64或明文，过滤支持的节点
def base64_decode_links(data: str):
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        lines = [line.strip() for line in decoded.strip().splitlines()]
    except Exception:
        lines = [line.strip() for line in data.strip().splitlines()]
    return [line for line in lines if is_supported_node(line)]

# TCP测速函数
async def tcp_ping(host: str, port: int, timeout=5):
    try:
        start = time.perf_counter()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        end = time.perf_counter()
        writer.close()
        await writer.wait_closed()
        delay_ms = int((end - start) * 1000)
        if delay_ms > MAX_DELAY:
            return None
        return delay_ms
    except Exception:
        return None

# 测试单个节点
async def test_single_node(node: str):
    parsed = urlparse(node)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return None
    return await tcp_ping(host, port)

# 进度显示类，单行更新
class ProgressManager:
    def __init__(self, proto, total):
        self.proto = proto
        self.total = total
        self.success_count = 0
        self.tested_count = 0

    def update(self, idx, delay):
        self.tested_count = idx
        if delay is not None:
            self.success_count += 1
        delay_str = f"{delay}ms" if delay is not None else "timeout"
        print(f"\r{self.proto} ({self.tested_count}/{self.total}) 延迟: {delay_str} 成功: {self.success_count}  ", end="", flush=True)

async def test_protocol_nodes(proto, nodes):
    prog = ProgressManager(proto, len(nodes))

    sem = asyncio.Semaphore(32)

    async def run_test(idx, node):
        async with sem:
            delay = await test_single_node(node)
            prog.update(idx, delay)
            return node if delay is not None else None

    tasks = [run_test(i + 1, node) for i, node in enumerate(nodes)]
    results = await asyncio.gather(*tasks)
    print()  # 换行
    return [node for node in results if node is not None]

async def main():
    # 真实可测速节点示例，端口改成你要测速的端口，地址改成真实有效域名/IP
    # 这里用公共HTTP端口作为示范（不要用hysteria2协议写法，改成支持测试的格式）
    example_nodes = [
        "hysteria2://google.com:80",
        "hysteria2://cloudflare.com:80",
        "hysteria2://invalid.domain:80",  # 这会timeout
    ]

    proto = "hysteria2"
    print(f"🎯 去重后节点数: {len(example_nodes)}")
    print(f"🚦 开始测试协议: {proto} 共 {len(example_nodes)} 个节点")

    tested = await test_protocol_nodes(proto, example_nodes)

    print(f"✅ {proto} 测试完成，成功节点数: {len(tested)}")

if __name__ == "__main__":
    asyncio.run(main())
