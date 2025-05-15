import sys
import time
import random

def print_progress(proto, current, total, delay, success_count):
    delay_str = f"{delay}ms" if delay is not None else "timeout"
    sys.stdout.write(f"\r{proto} ({current}/{total}) 延迟: {delay_str} 成功: {success_count}  ")
    sys.stdout.flush()

def simulate_check_nodes(protocol, nodes_count):
    success = 0
    for i in range(1, nodes_count + 1):
        # 模拟延迟或者timeout
        delay = random.choice([None]*5 + [50, 80, 120])
        if delay is not None:
            success += 1
        print_progress(protocol, i, nodes_count, delay, success)
        time.sleep(0.05)
    print()  # 换行结束打印

def main():
    # 你可以把这里改成你真实的节点数和协议名称
    protocol = "hysteria2"
    total_nodes = 37

    print(f"🎯 去重后节点数: {total_nodes}")
    print(f"🚦 开始测试协议: {protocol} 共 {total_nodes} 个节点")

    simulate_check_nodes(protocol, total_nodes)

    print(f"✅ {protocol} 测试完成，成功节点数: 结束时成功个数")

if __name__ == "__main__":
    main()
