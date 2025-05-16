import os
import asyncio
import aiohttp
import socket

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("[错误] 环境变量 OPENAI_API_KEY 未设置，无法调用 OpenAI API。")

async def test_tcp(host, port, timeout=5):
    loop = asyncio.get_event_loop()
    try:
        fut = loop.run_in_executor(None, lambda: socket.create_connection((host, port), timeout))
        conn = await asyncio.wait_for(fut, timeout)
        conn.close()
        return True
    except Exception:
        return False

async def test_openai_api():
    if not OPENAI_API_KEY:
        return False
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    json_data = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "测试连通性"}]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=json_data, timeout=10) as resp:
                if resp.status == 200:
                    return True
                else:
                    text = await resp.text()
                    print(f"\n[OpenAI API] 状态码: {resp.status}, 内容: {text}")
                    return False
    except Exception as e:
        print(f"\n[OpenAI API] 请求异常: {e}")
        return False

async def main():
    # 请把你的节点改成这个格式
    nodes = [
        {"host": "8.8.8.8", "port": 53},
        {"host": "1.1.1.1", "port": 53},
        # {"host": "your_node_ip_or_domain", "port": your_node_port},
    ]

    total = len(nodes)
    success = 0

    for i, node in enumerate(nodes, 1):
        tcp_ok = await test_tcp(node["host"], node["port"])
        chatgpt_ok = False
        if tcp_ok:
            chatgpt_ok = await test_openai_api()

        if tcp_ok and chatgpt_ok:
            success += 1

        percent = i / total * 100
        print(f"\r测试节点进度: {percent:6.2f}% | 成功: {success} | 当前节点 TCP: {tcp_ok} | ChatGPT: {chatgpt_ok}", end="", flush=True)

    print("\n测试完成")

if __name__ == "__main__":
    asyncio.run(main())
