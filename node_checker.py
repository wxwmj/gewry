import asyncio
import aiohttp
import base64
import time
from urllib.parse import urlparse
from asyncio import Semaphore

MAX_DELAY = 5000
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

def print_progress_line(proto, current, total, delay, success_count):
    delay_str = f"{delay}ms" if delay is not None else "timeout"
    print(f"{proto} ({current}/{total}) 延迟: {delay_str} 成功: {success_count}  ", end="\r", flush=True)

async def test_protocol_nodes(proto, nodes):
    total = len(nodes)
    success_count = 0
    tested_count = 0
    min_delay = None
    sem = Semaphore(8)  # 降低并发

    valid_nodes = []

    async def test_node(idx, node):
        nonlocal success_count, tested_count, min_delay
        async with sem:
            delay = await test_single_node(node)
            tested_count += 1
            if delay is not None:
                success_count += 1
                if min_delay is None or delay < min_delay:
                    min_delay = delay
                valid_nodes.append(node)
            print_progress_line(proto, tested_count, total, delay, success_count)

    start_time = time.perf_counter()
    tasks = [test_node(idx + 1, node) for idx, node in enumerate(nodes)]
    await asyncio.gather(*tasks)
    end_time = time.perf_counter()

    elapsed = int((end_time - start_time) * 1000)
    delay_str = f"{min_delay}ms" if min_delay is not None else "timeout"
    print(f"{proto} ({tested_count}/{total}) 延迟: {delay_str} 成功: {success_count} 测速耗时: {elapsed}ms")

    return valid_nodes  # 直接返回已测试通过的节点列表

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
        if not res:
            print(f"[警告] 抓取失败或无节点: {url}")
        raw_nodes.extend(res)

    print(f"📊 抓取完成，节点总数（含重复）: {len(raw_nodes)}")

    unique_nodes_map = {}
    for node in raw_nodes:
        key = extract_host_port(node)
        if key and key not in unique_nodes_map:
            unique_nodes_map[key] = node

    all_nodes = list(unique_nodes_map.values())
    print(f"🎯 去重后节点数: {len(all_nodes)}")

    groups = {}
    for node in all_nodes:
        proto = node.split("://")[0]
        groups.setdefault(proto, []).append(node)

    tested_all = []
    for proto in sorted(groups.keys()):
        print(f"🚦 开始测试协议: {proto} 共 {len(groups[proto])} 个节点")
        try:
            # 整个测速最多30秒超时限制
            tested_nodes = await asyncio.wait_for(test_protocol_nodes(proto, groups[proto]), timeout=30)
        except asyncio.TimeoutError:
            print(f"[超时] 协议 {proto} 测速超时，跳过剩余节点")
            tested_nodes = []
        tested_all.extend(tested_nodes)

    print(f"\n✅ 测试完成: 成功 {len(tested_all)} / 总 {len(all_nodes)}")

    if not tested_all:
        print("[结果] 无可用节点")
        return

    combined = "\n".join(tested_all)
    encoded = base64.b64encode(combined.encode("utf-8")).decode("utf-8")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(encoded)

    print(f"📦 有效节点已保存: {OUTPUT_FILE}（共 {len(tested_all)} 个）")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("程序被用户中断")
