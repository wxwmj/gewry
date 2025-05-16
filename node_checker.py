import asyncio
import aiohttp
import base64
import os
import time
from urllib.parse import urlparse
from asyncio import Semaphore
import openai

MAX_DELAY = 5000  # 最大延迟 ms
MAX_SAVE = 1000   # 最大保存节点数
SUB_FILE = "subs.txt"  # 订阅链接文件名
OUTPUT_FILE = "sub"    # 输出文件名
SUPPORTED_PROTOCOLS = ("vmess://", "ss://", "trojan://", "vless://", "hysteria://", "hysteria2://", "tuic://")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TEST_TIMEOUT = 5  # 测试ChatGPT连接超时时间(秒)

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
        async with session.get(url, timeout=5) as resp:
            raw = await resp.text()
            return base64_decode_links(raw), None
    except Exception:
        return [], url  # 返回失败的链接，方便注释

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
        # 测试ChatGPT连通性
        if not OPENAI_API_KEY:
            print("[警告] OPENAI_API_KEY 未设置，跳过 ChatGPT 连通检测")
            return node, delay
        try:
            openai.api_key = OPENAI_API_KEY
            # 使用asyncio.to_thread调用同步接口防止阻塞
            def openai_test_call():
                completion = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": "Ping"}],
                    max_tokens=1,
                    temperature=0,
                )
                return completion.choices[0].message.content.strip()
            # 设置超时限制
            reply = await asyncio.wait_for(asyncio.to_thread(openai_test_call), timeout=OPENAI_TEST_TIMEOUT)
            if reply:
                return node, delay
            else:
                return None
        except Exception:
            return None
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
        failed_urls = []
        for url in urls:
            nodes, failed_url = await fetch_subscription(session, url)
            if nodes:
                print(f"[成功] 抓取订阅：{url}，节点数: {len(nodes)}")
                all_nodes.extend(nodes)
            if failed_url:
                failed_urls.append(failed_url)

    print(f"📊 抓取完成，节点总数（含重复）: {len(all_nodes)}")

    # 失败订阅自动注释写回文件
    if failed_urls:
        print(f"⚠️ 发现抓取失败订阅链接 {len(failed_urls)} 个，正在添加注释...")
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(SUB_FILE, "w", encoding="utf-8") as f:
            for line in lines:
                stripped = line.strip()
                if stripped in failed_urls and not stripped.startswith("#"):
                    f.write("# " + line)
                else:
                    f.write(line)

    # 去重，key = host:port
    unique_nodes_map = {}
    for node in all_nodes:
        key = extract_host_port(node)
        if key and key not in unique_nodes_map:
            unique_nodes_map[key] = node

    unique_nodes = list(unique_nodes_map.values())
    print(f"🎯 去重后节点数: {len(unique_nodes)}")

    print(f"🚦 开始节点延迟及ChatGPT连通测试，共 {len(unique_nodes)} 个节点")
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
    if not OPENAI_API_KEY:
        print("[错误] 环境变量 OPENAI_API_KEY 未设置，无法检测 ChatGPT 连通性")
    asyncio.run(main())
