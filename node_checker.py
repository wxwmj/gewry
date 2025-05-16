import asyncio
import aiohttp
import base64
import time
from urllib.parse import urlparse
from asyncio import Semaphore
import sys

MAX_DELAY = 5000
MAX_SAVE = 1000
SUB_FILE = "subs.txt"
OUTPUT_FILE = "sub"  # 输出文件名，无扩展名
SUPPORTED_PROTOCOLS = ("vmess://", "ss://", "trojan://", "vless://", "hysteria://", "hysteria2://", "tuic://")
MAX_CONCURRENT = 32

MAX_PROGRESS_LINES = 10
progress_lines = []

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
            port = int(parsed.port)
            if 0 < port < 65536:
                return f"{parsed.hostname}:{port}"
    except Exception as e:
        print(f"[警告] 节点地址解析异常 {node_url}: {e}")
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
        return node, delay
    except Exception:
        return None

def print_progress_loop(percent, success_count, done_count, total):
    global progress_lines
    line = f"测试节点进度: {percent:6.2f}% | 成功: {success_count} | 已测: {done_count} / 总: {total}"
    progress_lines.append(line)

    if len(progress_lines) > MAX_PROGRESS_LINES:
        # 光标上移MAX_PROGRESS_LINES行，覆盖旧行
        sys.stdout.write(f"\033[{MAX_PROGRESS_LINES}A")

        # 清除并打印每行
        for i in range(MAX_PROGRESS_LINES):
            sys.stdout.write("\033[2K\r")  # 清除当前行
            sys.stdout.write(progress_lines[-MAX_PROGRESS_LINES + i] + "\n")

        sys.stdout.flush()
    else:
        print(line)
        sys.stdout.flush()

async def test_all_nodes(nodes):
    total = len(nodes)
    success_count = 0
    done_count = 0
    results = []
    sem = Semaphore(MAX_CONCURRENT)

    async def test_node(node):
        nonlocal success_count, done_count
        async with sem:
            res = await test_single_node(node)
            done_count += 1
            percent = done_count / total * 100
            if res is not None:
                results.append(res)
                success_count += 1
            print_progress_loop(percent, success_count, done_count, total)

    tasks = [test_node(node) for node in nodes]
    await asyncio.gather(*tasks)

    return [node for node, delay in sorted(results, key=lambda x: x[1])[:MAX_SAVE]]

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
                print(f"[失败] 抓取订阅：{url}")

    print(f"📊 抓取完成，节点总数（含重复）: {len(all_nodes)}")

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
