import asyncio
import aiohttp
import base64
import time
import os
import shutil
from urllib.parse import urlparse
from asyncio import Semaphore
from datetime import datetime
import glob

MAX_DELAY = 5000
MAX_SAVE = 6666
NODES_PER_FILE = 666
OUTPUT_FILE_PREFIX = "sub"
SUPPORTED_PROTOCOLS = (
    "vmess://", "ss://", "trojan://", "vless://",
    "hysteria://", "hysteria2://", "tuic://"
)

def get_project_root():
    # main.py 在 config 下，项目根目录上两级
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SUB_FILE = os.path.join(get_project_root(), "source", "subs.txt")

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
        async with session.get(url, timeout=3) as resp:
            raw = await resp.text()
            return base64_decode_links(raw)
    except Exception as e:
        print(f"[失败] 抓取订阅失败，链接：{url}，错误：{e}")
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
    print()
    results.sort(key=lambda x: x[1])
    return [node for node, delay in results[:MAX_SAVE]]

def delete_old_output_folders():
    root = get_project_root()
    print(f"项目根目录路径: {root}")

    old_folders = glob.glob(os.path.join(root, "output*"))
    if not old_folders:
        print("未找到旧目录 output，跳过删除。")
        return

    for folder in old_folders:
        if os.path.isdir(folder):
            try:
                print(f"🗑️ 删除旧目录：{folder}")
                shutil.rmtree(folder)
            except Exception as e:
                print(f"[错误] 删除文件夹失败：{folder}，错误：{e}")
        else:
            print(f"[跳过] 不是目录，忽略：{folder}")

def create_output_folder():
    root = get_project_root()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    folder_name = os.path.join(root, f"output{timestamp}")
    os.makedirs(folder_name)
    print(f"📂 新建保存文件夹: {folder_name}")
    return folder_name

async def save_nodes_to_file(nodes, file_index, folder):
    if len(nodes) >= NODES_PER_FILE:
        file_name = os.path.join(folder, f"{OUTPUT_FILE_PREFIX}{file_index}.txt")
        with open(file_name, "w", encoding="utf-8") as f:
            combined = "\n".join(nodes)
            encoded = base64.b64encode(combined.encode("utf-8")).decode("utf-8")
            f.write(encoded)
        print(f"📦 文件 {file_name} 保存成功，节点数: {len(nodes)}")
    else:
        print(f"[跳过] 文件 {file_index} 节点数不足 {NODES_PER_FILE}，不保存。")

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

    print(f"📊 抓取完成，节点总数（含重复）: {len(all_nodes)}")
    unique_nodes_map = {}
    for n in all_nodes:
        hp = extract_host_port(n)
        if hp:
            unique_nodes_map[hp] = n
    unique_nodes = list(unique_nodes_map.values())
    print(f"🎯 去重后节点数: {len(unique_nodes)}")

    print(f"🚦 开始节点延迟测试，共 {len(unique_nodes)} 个节点")
    tested_nodes = await test_all_nodes(unique_nodes)
    print(f"\n✅ 测试完成: 成功 {len(tested_nodes)} / 总 {len(unique_nodes)}")

    if not tested_nodes:
        print("[结果] 无可用节点")
        return

    folder = create_output_folder()

    file_index = 1
    nodes_batch = []
    for i, node in enumerate(tested_nodes, start=1):
        nodes_batch.append(node)
        if len(nodes_batch) == NODES_PER_FILE or i == len(tested_nodes):
            await save_nodes_to_file(nodes_batch, file_index, folder)
            file_index += 1
            nodes_batch = []

if __name__ == "__main__":
    print(f"程序启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    delete_old_output_folders()
    asyncio.run(main())
