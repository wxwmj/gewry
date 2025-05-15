import asyncio
import base64
from urllib.parse import urlparse
import time
import sys
from asyncio import Semaphore

MAX_DELAY = 5000  # 最大延迟ms，超出视为超时

# 判断节点格式是否支持
def is_supported_node(url: str) -> bool:
    return url.startswith((
        "vmess://", "ss://", "trojan://", "vless://", "hysteria://", "hysteria2://", "tuic://"
    ))

# Base64解码并过滤有效节点
def base64_decode_links(data: str):
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        lines = [line.strip() for line in decoded.strip().splitlines()]
    except Exception:
        lines = [line.strip() for line in data.strip().splitlines()]
    return [line for line in lines if is_supported_node(line)]

# 异步TCP连接测速，返回延迟(ms)，超时返回None
async def tcp_ping(host: str, port: int, timeout=5):
    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(loop.getaddrinfo(host, port), timeout)
        start = time.perf_counter()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        end = time.perf_counter()
        writer.close()
        await writer.wait_closed()
        return int((end - start) * 1000)
    except Exception:
        return None

# 测试单节点，返回延迟或None
async def test_single_node(node: str):
    try:
        parsed = urlparse(node)
        host, port = parsed.hostname, parsed.port
        if not host or not port:
            return None
        delay = await tcp_ping(host, port, timeout=5)
        if delay is None or delay > MAX_DELAY:
            return None
        return delay
    except Exception:
        return None

# 进度打印管理器
class ProgressManager:
    def __init__(self, proto, total):
        self.proto = proto
        self.total = total
        self.success_count = 0
        self.tested_count = 0
        self.min_delay = None
        self.lock = asyncio.Lock()
        self.queue = asyncio.Queue()
        self._stop = False

    async def start(self):
        while not self._stop:
            idx, delay, success_update = await self.queue.get()
            async with self.lock:
                self.tested_count = idx
                if success_update:
                    self.success_count += 1
                    if self.min_delay is None or delay < self.min_delay:
                        self.min_delay = delay
                delay_str = f"{delay}ms" if delay is not None else "timeout"
                text = f"{self.proto} ({self.tested_count}/{self.total}) 延迟: {delay_str} 成功: {self.success_count}  "
                print('\r' + text + ' ' * 10, end='', flush=True)
            self.queue.task_done()
        print()  # 结束后换行

    async def report(self, idx, delay, success_update):
        await self.queue.put((idx, delay, success_update))

    def stop(self):
        self._stop = True

# 测试协议下所有节点
async def test_protocol_nodes(proto, nodes):
    total = len(nodes)
    prog = ProgressManager(proto, total)
    sem = Semaphore(32)  # 限制并发数

    # 启动打印进度任务
    progress_task = asyncio.create_task(prog.start())

    async def test_node(idx, node):
        async with sem:
            delay = await test_single_node(node)
            success_update = delay is not None
            await prog.report(idx, delay, success_update)
            return node if success_update else None

    tasks = [test_node(i + 1, node) for i, node in enumerate(nodes)]
    results = await asyncio.gather(*tasks)

    await prog.queue.join()
    prog.stop()
    await progress_task

    tested_nodes = [node for node in results if node is not None]
    return tested_nodes

async def main():
    # 这里用示例 base64 编码的订阅数据，替换成你的抓取数据
    example_sub = base64.b64encode(b"""
hysteria2://host1:443
hysteria2://host2:443
hysteria2://host3:443
    """).decode()

    nodes = base64_decode_links(example_sub)
    proto = "hysteria2"

    print(f"🎯 去重后节点数: {len(nodes)}")
    print(f"🚦 开始测试协议: {proto} 共 {len(nodes)} 个节点")

    tested_nodes = await test_protocol_nodes(proto, nodes)
    print(f"✅ {proto} 测试完成，成功节点数: {len(tested_nodes)}")

if __name__ == "__main__":
    asyncio.run(main())
