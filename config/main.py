import os
import shutil
from datetime import datetime
from pathlib import Path

SUB_FILE = "source/subs.txt"  # 你的 subs.txt 路径
SAVE_LIMIT = 6666
BATCH_SIZE = 666

# 🗑️ 删除所有旧的 output 文件夹（包括 output 本身）
for folder in Path(".").glob("output*"):
    if folder.is_dir():
        shutil.rmtree(folder)
        print(f"🗑️ 删除旧目录：{folder.name}")

# 📂 新建带时间戳的新 output 文件夹
now = datetime.now().strftime("%Y%m%d_%H%M")
output_folder = f"output{now}"
os.makedirs(output_folder, exist_ok=True)
print(f"📂 新建保存文件夹: {output_folder}")

# 📥 读取订阅链接
print("📥 读取订阅链接...")
if not os.path.exists(SUB_FILE):
    print(f"[错误] 未找到文件 {SUB_FILE}")
    exit(1)

with open(SUB_FILE, "r", encoding="utf-8") as f:
    urls = [line.strip() for line in f if line.strip()]

# 🛰️ 模拟获取节点数据（替换为真实处理逻辑）
nodes = [{"data": f"节点{i}"} for i in range(1, SAVE_LIMIT + 557)]  # 模拟

print(f"✅ 测试完成: 成功 {len(nodes)} / 总 {len(nodes)}")

# 💾 保存分组后的文件
for i in range(0, len(nodes), BATCH_SIZE):
    batch = nodes[i:i + BATCH_SIZE]
    if len(batch) < 99:
        print(f"[跳过] 文件 {i // BATCH_SIZE + 1} 节点数不足 99，不保存。")
        continue

    filename = f"{output_folder}/sub{i // BATCH_SIZE + 1}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        for node in batch:
            f.write(str(node) + "\n")
    print(f"📦 文件 {filename} 保存成功，节点数: {len(batch)}")
