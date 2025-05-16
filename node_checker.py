import asyncio
import aiohttp
import base64
import time
from urllib.parse import urlparse
from asyncio import Semaphore
from datetime import datetime

MAX_DELAY = 5000
MAX_SAVE = 1000  # 保存测速后延迟最低的前1000条节点
SUB_FILE = "subs.txt"
OUTPUT_FILE = "sub"  # 输出文件名改为 sub（无扩展名）
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
    done_count = 0
    results = []
    sem = Semaphore(32)

    async def test_node(node):
        nonlocal success_count, done_count
        async with sem:
            delay = await test_single_node(node)
            if delay is not None and delay <= MAX_DELAY:
                results.append((node, delay))
                success_count += 1
            done_count += 1
            print(f"\r测试进度 ({done_count}/{total}) 成功: {success_count}   ", end="", flush=True)

    tasks = [test_node(node) for node in nodes]
    await asyncio.gather(*tasks)
    print()

    results.sort(key=lambda x: x[1])
    top_nodes = [node for node, delay in results[:MAX_SAVE]]

    return top_nodes

async def main():
    print("📥 读取订阅链接...")
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"[错误] 未找到文件 {SUB_FILE}")
        return

    print("🌐 抓取订阅链接中...")
    fetch_stats = {}  # 统计每个链接成功失败节点数
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_subscription(session, url) for url in urls]
        results = await asyncio.gather(*tasks)

    raw_nodes = []
    for url, res in zip(urls, results):
        success_num = len(res) if res else 0
        fail_num = 0 if res else 1  # 简单认为抓取失败算1个失败
        fetch_stats[url] = {"success": success_num, "fail": fail_num}

        if success_num:
            print(f"[成功] 抓取链接: {url} 节点数: {success_num}")
        else:
            print(f"[失败] 抓取链接: {url}")

        raw_nodes.extend(res if res else [])

    print(f"📊 抓取完成，节点总数（含重复）: {len(raw_nodes)}")

    unique_nodes_map = {}
    for node in raw_nodes:
        key = extract_host_port(node)
        if key and key not in unique_nodes_map:
            unique_nodes_map[key] = node

    all_nodes = list(unique_nodes_map.values())
    print(f"🎯 去重后节点数: {len(all_nodes)}")

    print(f"🚦 开始节点延迟测试，共 {len(all_nodes)} 个节点")
    tested_nodes = await test_all_nodes(all_nodes)

    print(f"\n✅ 测试完成: 成功 {len(tested_nodes)} / 总 {len(all_nodes)}")

    if not tested_nodes:
        print("[结果] 无可用节点")
        return

    combined = "\n".join(tested_nodes)
    encoded = base64.b64encode(combined.encode("utf-8")).decode("utf-8")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(encoded)

    print(f"📦 有效节点已保存: {OUTPUT_FILE}（共 {len(tested_nodes)} 个）")

    # 打印抓取统计，格式化时间和统计内容
    for url, counts in fetch_stats.items():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        print(f"{now} - {url}: 成功 {counts['success']}，失败 {counts['fail']}")

if __name__ == "__main__":
    asyncio.run(main())
