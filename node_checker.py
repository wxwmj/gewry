import asyncio
import aiohttp
import base64
import time
from urllib.parse import urlparse
from asyncio import Semaphore

MAX_DELAY = 5000
MAX_SAVE = 1000
SUB_FILE = "subs.txt"
OUTPUT_FILE = "sub"
SUPPORTED_PROTOCOLS = ("vmess://", "ss://", "trojan://", "vless://", "hysteria://", "hysteria2://", "tuic://")

def is_supported_node(url):
    return url.startswith(SUPPORTED_PROTOCOLS)

def base64_decode_links(data):
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        return [line.strip() for line in decoded.strip().splitlines() if is_supported_node(line)]
    except Exception:
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
        start = time.perf_counter()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        end = time.perf_counter()
        writer.close()
        await writer.wait_closed()
        return int((end - start) * 1000)
    except Exception:
        return None

async def test_single_node(node):
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

async def test_nodes_for_subscription(nodes):
    sem = Semaphore(32)
    success_count = 0
    fail_count = 0
    results = []

    async def test_node(node):
        nonlocal success_count, fail_count
        async with sem:
            delay = await test_single_node(node)
            if delay is not None:
                results.append((node, delay))
                success_count += 1
            else:
                fail_count += 1

    tasks = [test_node(node) for node in nodes]
    await asyncio.gather(*tasks)

    # 按延迟排序，取前MAX_SAVE条节点
    results.sort(key=lambda x: x[1])
    top_nodes = [node for node, delay in results[:MAX_SAVE]]

    return top_nodes, success_count, fail_count

async def main():
    print("📥 读取订阅链接...")
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"[错误] 未找到文件 {SUB_FILE}")
        return

    print("🌐 抓取订阅链接中...")
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_subscription(session, url) for url in urls]
        all_nodes_lists = await asyncio.gather(*tasks)

    all_success_nodes = []
    for url, nodes in zip(urls, all_nodes_lists):
        if not nodes:
            print(f"{url}: 抓取失败或无节点")
            continue
        print(f"{url}: 抓取节点数 {len(nodes)}，开始测速...")

        tested_nodes, success, fail = await test_nodes_for_subscription(nodes)
        print(f"{url}: 测速结果 -> 成功 {success}，失败 {fail}")

        all_success_nodes.extend(tested_nodes)

    # 去重处理
    unique_nodes_map = {}
    for node in all_success_nodes:
        key = extract_host_port(node)
        if key and key not in unique_nodes_map:
            unique_nodes_map[key] = node

    final_nodes = list(unique_nodes_map.values())
    print(f"🎯 总计有效节点数（去重后）: {len(final_nodes)}")

    if not final_nodes:
        print("[结果] 无可用节点")
        return

    combined = "\n".join(final_nodes)
    encoded = base64.b64encode(combined.encode("utf-8")).decode("utf-8")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(encoded)

    print(f"📦 有效节点已保存: {OUTPUT_FILE}（共 {len(final_nodes)} 个）")

if __name__ == "__main__":
    asyncio.run(main())
