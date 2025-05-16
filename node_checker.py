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
    print(f"[抓取] 开始抓取订阅链接: {url}")
    try:
        async with session.get(url, timeout=10) as resp:
            raw = await resp.text()
            print(f"[抓取] 抓取完成: {url}，内容长度 {len(raw)}")
            return base64_decode_links(raw)
    except Exception as e:
        print(f"[抓取] 抓取失败: {url}，错误: {e}")
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

async def tcp_ping(host, port, timeout=5):
    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(loop.getaddrinfo(host, port), timeout)
        start = time.perf_counter()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        end = time.perf_counter()
        writer.close()
        await writer.wait_closed()
        delay_ms = int((end - start) * 1000)
        print(f"[测速] 成功连接 {host}:{port} 延迟 {delay_ms} ms")
        return delay_ms
    except Exception as e:
        print(f"[测速] 连接失败 {host}:{port} 错误: {e}")
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

line_template = "测试节点进度: {percent:6.2f}% | 成功: {success_count} | 失败: {fail_count}"
max_len = 60  # 估计最大行长度

def print_progress(percent, success_count, fail_count):
    line = line_template.format(percent=percent, success_count=success_count, fail_count=fail_count)
    padded_line = line + " " * (max_len - len(line))
    print("\r" + padded_line, end="", flush=True)

async def test_all_nodes(nodes):
    total = len(nodes)
    success_count = 0
    fail_count = 0
    done_count = 0
    results = []
    sem = Semaphore(32)

    progress_checkpoint = 0.1  # 每10%打印一次
    next_progress = progress_checkpoint

    async def test_node(node):
        nonlocal success_count, done_count, fail_count, next_progress
        async with sem:
            res = await test_single_node(node)
            done_count += 1
            if res is not None:
                results.append(res)
                success_count += 1
            else:
                fail_count += 1

            percent = done_count / total
            # 只在达到或超过每10%时打印
            if percent >= next_progress or done_count == total:
                print_progress(percent * 100, success_count, fail_count)
                while next_progress <= percent:
                    next_progress += progress_checkpoint

    print("[测速] 开始测速...")
    tasks = [test_node(node) for node in nodes]
    await asyncio.gather(*tasks)
    print()  # 换行，避免进度条卡在同一行

    results.sort(key=lambda x: x[1])
    top_nodes = [node for node, delay in results[:MAX_SAVE]]

    print(f"[测速] 总任务数: {total}, 成功: {success_count}, 失败: {fail_count}")
    return top_nodes

async def main():
    print("📥 读取订阅链接...")
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"[错误] 未找到文件 {SUB_FILE}")
        return

    if not urls:
        print(f"[错误] 订阅链接文件 {SUB_FILE} 是空的")
        return

    print(f"🌐 抓取订阅内容中... 共 {len(urls)} 条链接")
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

    if not unique_nodes:
        print("[结果] 无可用节点，退出")
        return

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
