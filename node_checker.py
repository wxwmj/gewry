import asyncio
import aiohttp
import base64
import time
from urllib.parse import urlparse
from asyncio import Semaphore
from tqdm.asyncio import tqdm_asyncio

MAX_DELAY = 3000  # 3秒连接超时及最大延迟
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
        return None  # 返回 None 表示失败

def extract_host_port_protocol(node_url):
    try:
        parsed = urlparse(node_url)
        if parsed.hostname and parsed.port:
            port = int(parsed.port)
            if 0 < port < 65536:
                # 返回协议 + 主机:端口，避免不同协议节点被去重
                proto = node_url.split("://")[0]
                return f"{proto}://{parsed.hostname}:{port}"
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
        delay = await tcp_ping(host, port, timeout=MAX_DELAY / 1000)
        if delay is None or delay > MAX_DELAY:
            return None
        return node, delay
    except Exception:
        return None

async def test_all_nodes(nodes):
    sem = Semaphore(32)
    results = []

    async def test_node(node):
        async with sem:
            res = await test_single_node(node)
            if res is not None:
                results.append(res)

    # tqdm_asyncio支持异步任务进度条
    await tqdm_asyncio.gather(*[test_node(node) for node in nodes], desc="测试节点延迟")

    results.sort(key=lambda x: x[1])
    return [node for node, delay in results[:MAX_SAVE]]

def mark_failed_urls_in_file(failed_urls):
    """把 subs.txt 中失败的 URL 注释掉，其他行保持不变"""
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        with open(SUB_FILE, "w", encoding="utf-8") as f:
            for line in lines:
                stripped = line.strip()
                # 已经注释过的直接写
                if stripped.startswith("#"):
                    f.write(line)
                    continue
                # 如果该行是失败订阅链接，则注释掉
                if stripped in failed_urls:
                    f.write("# " + line)
                else:
                    f.write(line)
    except Exception as e:
        print(f"[错误] 标记失败订阅链接时出错: {e}")

async def main():
    print("📥 读取订阅链接...")
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    except FileNotFoundError:
        print(f"[错误] 未找到文件 {SUB_FILE}")
        return

    print("🌐 抓取订阅内容中...")
    failed_urls = set()
    all_nodes = []
    async with aiohttp.ClientSession() as session:
        for url in urls:
            nodes = await fetch_subscription(session, url)
            if nodes is None:
                print(f"[失败] 抓取订阅：{url}")
                failed_urls.add(url)
            elif nodes:
                print(f"[成功] 抓取订阅：{url}，节点数: {len(nodes)}")
                all_nodes.extend(nodes)
            else:
                print(f"[失败] 抓取订阅但无有效节点：{url}")
                failed_urls.add(url)

    if failed_urls:
        print(f"\n📌 标记 {len(failed_urls)} 个失败订阅链接为注释...")
        mark_failed_urls_in_file(failed_urls)

    print(f"\n📊 抓取完成，节点总数（含重复）: {len(all_nodes)}")

    unique_nodes_map = {}
    for node in all_nodes:
        key = extract_host_port_protocol(node)
        if key and key not in unique_nodes_map:
            unique_nodes_map[key] = node

    unique_nodes = list(unique_nodes_map.values())
    print(f"🎯 去重后节点数: {len(unique_nodes)}")

    if not unique_nodes:
        print("[结果] 无可用节点，退出。")
        return

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
