import asyncio
import aiohttp
import base64
import sys
from urllib.parse import urlparse

MAX_DELAY = 5000
SUB_FILE = "subs.txt"
OUTPUT_FILE = "sub"
MAX_CONCURRENT = 32

SUPPORTED_PROTOCOLS = ("vmess://", "ss://", "trojan://", "vless://", "hysteria://", "hysteria2://", "tuic://")

def is_supported_node(url):
    return url.startswith(SUPPORTED_PROTOCOLS)

def base64_decode_links(data):
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        return [line.strip() for line in decoded.strip().splitlines() if is_supported_node(line)]
    except Exception:
        # 如果解码失败，尝试原始文本逐行过滤
        return [line.strip() for line in data.strip().splitlines() if is_supported_node(line)]

async def fetch_subscription(session, url):
    try:
        async with session.get(url, timeout=10) as resp:
            raw = await resp.text()
            return base64_decode_links(raw)
    except Exception:
        return []

def extract_host_port(node_url):
    try:
        parsed = urlparse(node_url)
        if parsed.hostname and parsed.port:
            return f"{parsed.hostname}:{parsed.port}"
    except:
        return None
    return None

async def tcp_ping(host, port, timeout=5):
    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(loop.getaddrinfo(host, port), timeout)
        start = loop.time()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        end = loop.time()
        writer.close()
        await writer.wait_closed()
        return int((end - start) * 1000)
    except Exception:
        return None

async def test_single_node(node):
    parsed = urlparse(node)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return None
    delay = await tcp_ping(host, port, timeout=5)
    if delay is None or delay > MAX_DELAY:
        return None
    return delay

def print_progress(proto, current, total, delay, success_count):
    delay_str = f"{delay}ms" if delay is not None else "timeout"
    # \r 回到行首，覆盖当前行，不换行
    sys.stdout.write(f"\r{proto} ({current}/{total}) 延迟: {delay_str} 成功: {success_count}  ")
    sys.stdout.flush()

async def test_nodes_of_subscription(proto, nodes):
    total = len(nodes)
    success_count = 0

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    tested_nodes = []

    async def test_node(idx, node):
        nonlocal success_count
        async with sem:
            delay = await test_single_node(node)
            if delay is not None:
                success_count += 1
                tested_nodes.append(node)
            print_progress(proto, idx, total, delay, success_count)

    tasks = [test_node(i+1, node) for i, node in enumerate(nodes)]
    await asyncio.gather(*tasks)
    print()  # 换行

    print(f"✅ {proto} 测试完成，成功节点数: {success_count}\n")
    return tested_nodes

async def main():
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"未找到文件: {SUB_FILE}")
        return

    async with aiohttp.ClientSession() as session:
        for url in urls:
            nodes = await fetch_subscription(session, url)
            if not nodes:
                print(f"⚠️ 订阅链接无节点或抓取失败: {url}\n")
                continue

            # 去重按 host:port
            unique = {}
            for node in nodes:
                key = extract_host_port(node)
                if key and key not in unique:
                    unique[key] = node
            dedup_nodes = list(unique.values())

            proto = dedup_nodes[0].split("://")[0] if dedup_nodes else "unknown"
            print(f"🚦 开始测试协议: {proto} 共 {len(dedup_nodes)} 个节点")

            tested_nodes = await test_nodes_of_subscription(proto, dedup_nodes)

            # 这里可以保存每个订阅测试成功节点到文件（附加写入）
            # 下面简单写入一个总文件，或者按需求拆分
            if tested_nodes:
                with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                    for node in tested_nodes:
                        f.write(node + "\n")

if __name__ == "__main__":
    asyncio.run(main())
