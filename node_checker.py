import asyncio
import aiohttp
import base64
import time
from urllib.parse import urlparse
from asyncio import Semaphore
import sys

MAX_DELAY = 5000
MAX_OUTPUT_NODES = 1000
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

async def test_all_nodes(nodes):
    total = len(nodes)
    success_count = 0
    results = []
    sem = Semaphore(32)

    async def test_node(idx, node):
        nonlocal success_count
        async with sem:
            delay = await test_single_node(node)
            if delay is not None:
                results.append((node, delay))
                success_count += 1
            delay_str = f"{delay}ms" if delay else "timeout"
            sys.stdout.write(f"\r测试进度 ({idx}/{total}) 延迟: {delay_str} 成功: {success_count}   ")
            sys.stdout.flush()

    tasks = [test_node(i + 1, node) for i, node in enumerate(nodes)]
    await asyncio.gather(*tasks)
    print()
    return results

async def main():
    print("📥 读取订阅链接...")
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"[错误] 未找到文件 {SUB_FILE}")
        return

    print("🌐 抓取订阅内容中...")
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_subscription(session, url) for url in urls]
        results = await asyncio.gather(*tasks)

    raw_nodes = []
    for url, res in zip(urls, results):
        if res:
            print(f"[✓] 抓取成功: {url}  节点数: {len(res)}")
            raw_nodes.extend(res)
        else:
            print(f"[×] 抓取失败: {url}")

    print(f"📊 抓取完成，节点总数（含重复）: {len(raw_nodes)}")

    unique_nodes_map = {}
    for node in raw_nodes:
        key = extract_host_port(node)
        if key and key not in unique_nodes_map:
            unique_nodes_map[key] = node

    all_nodes = list(unique_nodes_map.values())
    print(f"🎯 去重后节点数: {len(all_nodes)}")

    print(f"🚦 开始节点延迟测试，共 {len(all_nodes)} 个节点")
    tested = await test_all_nodes(all_nodes)

    print(f"\n✅ 测试完成: 成功 {len(tested)} / 总 {len(all_nodes)}")

    if not tested:
        print("[结果] 无可用节点")
        return

    # 按延迟升序排序，保留前 MAX_OUTPUT_NODES 个
    top_nodes = sorted(tested, key=lambda x: x[1])[:MAX_OUTPUT_NODES]
    final_nodes = [node for node, _ in top_nodes]

    combined = "\n".join(final_nodes)
    encoded = base64.b64encode(combined.encode("utf-8")).decode("utf-8")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(encoded)

    print(f"📦 已保存延迟最低的前 {len(final_nodes)} 个节点到: {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
