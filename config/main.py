import asyncio
import aiohttp
import base64
import time
import os
import shutil
from urllib.parse import urlparse
from asyncio import Semaphore
from datetime import datetime, timezone, timedelta
import glob

# 配置常量
MAX_DELAY = 5000
MAX_SAVE = 6666
NODES_PER_FILE = 666
SUB_FILE = os.path.join("source", "subs.txt")  # 项目根目录下的 source 文件夹
OUTPUT_FILE_PREFIX = "sub"
SUPPORTED_PROTOCOLS = ("vmess://", "ss://", "trojan://", "vless://", "hysteria://", "hysteria2://", "tuic://")

# 失败链接保存路径
FAIL_FOLDER = "fail"
FAIL_FILE = os.path.join(FAIL_FOLDER, "fail.txt")


def ensure_fail_folder_exists():
    """确保 fail 文件夹存在，如果不存在则创建"""
    if not os.path.exists(FAIL_FOLDER):
        os.makedirs(FAIL_FOLDER)
        print(f"📂 创建文件夹: {FAIL_FOLDER}")


def save_failed_links(failed_links):
    """将失败的链接保存到 fail 文件夹中的 fail.txt"""
    ensure_fail_folder_exists()
    with open(FAIL_FILE, "a", encoding="utf-8") as f:
        for link in failed_links:
            f.write(f"# {link}\n")  # 注释掉失败的链接


def remove_duplicates_and_save():
    """从 subs.txt 读取链接并去重，更新文件"""
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"[错误] 未找到文件 {SUB_FILE}")
        return []

    # 去重并保留唯一的链接
    unique_urls = list(set(urls))  # 使用 set 去重

    # 将去重后的链接重新写入 subs.txt
    with open(SUB_FILE, "w", encoding="utf-8") as f:
        for url in unique_urls:
            f.write(f"{url}\n")

    return unique_urls


def is_supported_node(url):
    """判断链接是否为支持的协议"""
    return url.startswith(SUPPORTED_PROTOCOLS)


def base64_decode_links(data):
    """解码 Base64 格式的订阅链接"""
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        return [line.strip() for line in decoded.strip().splitlines() if is_supported_node(line)]
    except Exception:
        return [line.strip() for line in data.strip().splitlines() if is_supported_node(line)]


async def fetch_subscription(session, url):
    """抓取订阅内容"""
    try:
        async with session.get(url, timeout=5) as resp:
            raw = await resp.text()
            return base64_decode_links(raw)
    except Exception:
        print(f"[失败] 抓取订阅失败，已注释该链接: {url}")
        # 保存失败链接，注释掉该链接并记录到 fail 文件夹
        save_failed_links([url])
        return []


def extract_host_port(node_url):
    """提取节点的主机和端口"""
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
    """测试节点延迟"""
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
    """测试单个节点的延迟"""
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
    """打印节点测试进度"""
    line = f"测试节点进度: {percent:6.2f}% | 成功: {success_count}"
    max_len = 50
    padded_line = line + " " * (max_len - len(line))
    print("\r" + padded_line, end="", flush=True)


async def test_all_nodes(nodes):
    """测试所有节点的延迟并返回可用节点"""
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


def get_beijing_time():
    """获取北京时间"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz)


def clear_output_folder():
    """清空输出文件夹"""
    folder = "output"
    if not os.path.exists(folder):
        os.makedirs(folder)
        print(f"📂 创建文件夹: {folder}")
        return

    # 删除 output 文件夹内所有文件和子目录
    for item in os.listdir(folder):
        path = os.path.join(folder, item)
        try:
            if os.path.isfile(path):
                os.remove(path)
                print(f"🗑️ 删除旧文件：{path}")
            elif os.path.isdir(path):
                shutil.rmtree(path)
                print(f"🗑️ 删除旧目录：{path}")
        except Exception as e:
            print(f"[错误] 删除 {path} 失败: {e}")


def get_output_folder():
    """获取输出文件夹"""
    folder = "output"
    if not os.path.exists(folder):
        os.makedirs(folder)
        print(f"📂 创建文件夹: {folder}")
    else:
        print(f"📂 使用现有文件夹: {folder}")
    return folder


async def save_nodes_to_file(nodes, file_index, folder):
    """保存节点到文件"""
    if len(nodes) >= 99:
        file_name = os.path.join(folder, f"{OUTPUT_FILE_PREFIX}{file_index}.txt")
        with open(file_name, "w", encoding="utf-8") as f:
            combined = "\n".join(nodes)
            encoded = base64.b64encode(combined.encode("utf-8")).decode("utf-8")
            f.write(encoded)
        print(f"📦 文件 {file_name} 保存成功，节点数: {len(nodes)}")
    else:
        print(f"[跳过] 文件 {file_index} 节点数不足 99，不保存。")


async def main():
    print("📥 读取并去重订阅链接...")
    # 读取并去重后的订阅链接
    urls = remove_duplicates_and_save()

    if not urls:
        print("[错误] 没有有效的订阅链接可用")
        return

    print("🌐 抓取订阅内容中...")
    async with aiohttp.ClientSession() as session:
        all_nodes = []
        failed_links = []

        for url in urls:
            nodes = await fetch_subscription(session, url)
            if nodes:
                print(f"[成功] 抓取订阅：{url}，节点数: {len(nodes)}")
                all_nodes.extend(nodes)
            else:
                failed_links.append(url)

        if failed_links:
            print(f"[注意] {len(failed_links)} 个订阅链接抓取失败，已保存至 {FAIL_FILE}")

    # 去重后的节点处理
    print(f"📊 抓取完成，节点总数（含重复）: {len(all_nodes)}")
    unique_nodes_map = {extract_host_port(n): n for n in all_nodes if extract_host_port(n)}
    unique_nodes = list(unique_nodes_map.values())
    print(f"🎯 去重后节点数: {len(unique_nodes)}")

    print(f"🚦 开始节点延迟测试，共 {len(unique_nodes)} 个节点")
    tested_nodes = await test_all_nodes(unique_nodes)
    print(f"\n✅ 测试完成: 成功 {len(tested_nodes)} / 总 {len(unique_nodes)}")

    if not tested_nodes:
        print("[结果] 没有可用节点")
        return

    # 获取输出文件夹
    output_folder = get_output_folder()

    # 清空旧文件夹
    clear_output_folder()

    # 保存有效节点
    print("💾 保存有效节点...")
    output_file_count = 1
    for i in range(0, len(tested_nodes), NODES_PER_FILE):
        nodes_chunk = tested_nodes[i:i + NODES_PER_FILE]
        await save_nodes_to_file(nodes_chunk, output_file_count, output_folder)
        output_file_count += 1

if __name__ == "__main__":
    asyncio.run(main())
