import asyncio
import aiohttp
import base64
import time
from urllib.parse import urlparse
from asyncio import Semaphore

MAX_DELAY = 5000  # 最大延迟 ms
MAX_SAVE = 1000   # 最大保存节点数
SUB_FILE = "subs.txt"  # 订阅链接文件名
OUTPUT_FILE = "sub"    # 输出文件名
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
        async with session.get(url, timeout=3) as resp:  # 连接超时3秒
            raw = await resp.text()
            return base64_decode_links(raw)
    except Exception:
        print(f"[失败] 抓取订阅失败，请确认链接是否有效，并建议注释该链接：{url}")
        return []

def extract_host_port(node_url):
    try:
        parsed = urlparse(node_url)
        if parsed.hostname and parsed.port:
            port = int(parsed.port)
            if 0 < port < 65536:
                return f"{parsed.hostname}:{port}"
    except Exception:
        return None
    return None

async def tcp_ping(host, port, timeout=3):
    try:
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
        delay = await tcp_ping(host, port, timeout=3)
        if delay is None or delay > MAX_DELAY:
            return None
        return node, delay
    except Exception:
        return None

def print_progress(percent, success_count):
    line = f"测试节点进度: {percent:6.2f}% | 成功: {success_count}"
    max_len = 50
    padded_line = line + " " * (max_len - len(line))
    print("\r" + padded_line, end="", flush=True)

async def test_all_nodes(nodes):
    total = len(nodes)
    success_count = 0
    done_count = 0
    results = []
    sem = Semaphore(32)
    last_print_percent = 0

    async def test_node(node):
        nonlocal success_count, done_count, last_print_percent
        async with sem:
            res = await test_single_node(node)
            if res is not None:
                results.append(res)
                success_count += 1
            done_count += 1
            percent = done_count / total * 100
            if percent - last_print_percent >= 5 or percent == 100:
                print_progress(percent, success_count)
                last_print_percent = percent

    tasks = [test_node(node) for node in nodes]
    await asyncio.gather(*tasks)
    print()  # 换行避免进度卡在一行

    results.sort(key=lambda x: x[1])
    return [node for node, delay in results[:MAX_SAVE]]

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
        all_nodes = []
        for url in urls:
            nodes = await fetch_subscription(session, url)
            if nodes:
                print(f"[成功] 抓取订阅：{url}，节点数: {len(nodes)}")
                all_nodes.extend(nodes)
            else:
                # 已在 fetch_subscription 里打印失败并提醒注释
                pass

    print(f"📊 抓取完成，节点总数（含重复）: {len(all_nodes)}")

    # 去重逻辑优化，key = host:port
    unique_nodes_map = {}
    for node in all_nodes:
        key = extract_host_port(node)
        if key and key not in unique_nodes_map:
            unique_nodes_map[key] = node

    unique_nodes = list(unique_nodes_map.values())
    print(f"🎯 去重后节点数: {len(unique_nodes)}")

    print(f"🚦 开始节点延迟测试，共 {len(unique_nodes)} 个节点")
    tested_nodes = await test_all_nodes(unique_nodes)

    print(f"\n✅ 测试完成: 成功 {len(tested_nodes)} / 总 {len(unique_nodes)}")

    if not tested_nodes:
        print("[结果] 无可用节点")
        return

    combined = "\n".join(tested_nodes)
    encoded = base64.b64encode(combined.encode("utf-8")).decode("utf-8")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(encoded)

    print(f"📦 有效节点已保存: {OUTPUT_FILE}（共 {len(tested_nodes)} 个）")

if __name__ == "__main__":
    asyncio.run(main())
