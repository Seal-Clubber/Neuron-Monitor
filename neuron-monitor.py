import asyncio
import aiohttp
import json
import re
import os
import sys
import webbrowser

# Batch settings
BATCH_SIZE = 15
SEM = asyncio.Semaphore(BATCH_SIZE)

# ANSI escape regex for padding
ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

def real_length(s):
    return len(ansi_escape.sub('', s))

def pad_ansi(s, width):
    return s + ' ' * max(0, width - real_length(s))

def read_ip_ports(file_path):
    with open(file_path, "r") as f:
        return [line.strip() for line in f if line.strip()]

def colorize(value, thresholds=(50, 80)):
    try:
        val = float(value)
    except:
        return pad_ansi(f"{value}", 6)
    if val < thresholds[0]:
        return pad_ansi(f"\033[91m{val:.1f}%\033[0m", 6)  # red
    elif val < thresholds[1]:
        return pad_ansi(f"\033[93m{val:.1f}%\033[0m", 6)  # yellow
    else:
        return pad_ansi(f"\033[92m{val:.1f}%\033[0m", 6)  # green

def colorize_placement(position, max_val=100):
    try:
        val = int(position)
    except:
        return position

    score = min(max(val - 1, 0), max_val - 1) / (max_val - 1)

    if score <= 0.2:
        color = "\033[92m"  # green
    elif score <= 0.5:
        color = "\033[93m"  # yellow
    elif score <= 0.8:
        color = "\033[38;5;208m"  # orange
    else:
        color = "\033[91m"  # red

    return f"{color}{val}/100\033[0m"

async def fetch(session, url):
    try:
        async with session.get(url) as response:
            return await response.text()
    except Exception:
        return None

def parse_system_metrics(data):
    try:
        parsed = json.loads(data)
        version = parsed.get("version", "N/A").ljust(7)
        cpu = colorize(parsed.get("cpu_usage_percent", "N/A"))
        mem = colorize(parsed.get("memory", {}).get("percent", "N/A"))
        uptime = f"{parsed.get('uptime', 0) / 3600:.2f}h".ljust(7)
        return version, cpu, mem, uptime
    except:
        return "TIMEOUT", "-     ", "-     ", "-      "

def parse_wallet_stats(text):
    if not text:
        return "Stats: TIMEOUT"
    match = re.search(r"(\d+)\s+competitions.*?average placement of\s+(\d+)", text)
    if match:
        comps = match.group(1).rjust(4)
        pos = colorize_placement(match.group(2))
        return f"{comps} comps, avg pos {pos}"
    return "Stats: N/A"

async def process_ip(session, ip_port):
    sys_url = f"http://{ip_port}/system_metrics"
    stats_url = f"http://{ip_port}/fetch/wallet/stats/daily"

    sys_data, stats_data = await asyncio.gather(
        fetch(session, sys_url),
        fetch(session, stats_url)
    )

    version, cpu, mem, uptime = parse_system_metrics(sys_data)
    stats = parse_wallet_stats(stats_data)

    return f"{version} | {cpu} | {mem} | {uptime} | {stats}"

async def limited_process_ip(session, ip_port):
    async with SEM:
        return await process_ip(session, ip_port)

async def run_extra_command(session, ip_port):
    url = f"http://{ip_port}/power/shutdown"
    print(f"\nTriggering reboot: {url}")
    response = await fetch(session, url)
    if response:
        print(f"Response:\n{response}")
        print(f"Refreshing...")
    else:
        print("No response or error.")

def open_browser(ip_port):
    url = f"http://{ip_port}"
    print(f"\nOpening browser to {url}...")
    webbrowser.open(url)

def menu_handler(ip_ports):
    user_input = input("\nEnter index to open menu (or just press Enter to exit): ").strip()
    if user_input == "":
        return "exit", None
    if not user_input.isdigit():
        return None, None
    index = int(user_input)
    if not (0 <= index < len(ip_ports)):
        print("Invalid index.")
        return None, None

    print("\nChoose action:")
    print("1. Reboot")
    print("2. Open in browser")
    choice = input("Enter choice (1/2, or Enter to refresh): ").strip()
    return choice, ip_ports[index] if choice in ("1", "2") else None

async def main_loop():
    ip_ports = read_ip_ports("ip.txt")
    async with aiohttp.ClientSession() as session:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print(f"===== Fetching Data - Made by SealClubber =====")
            print(f"{'Idx':<5} {'IP:PORT':<22} | {'Ver':<7} | {'CPU':<6} | {'MEM':<6} | {'Uptime':<7} | Stats")
            print("-" * 95)

            results = [None] * len(ip_ports)
            for i in range(0, len(ip_ports), BATCH_SIZE):
                batch = ip_ports[i:i + BATCH_SIZE]
                tasks = [limited_process_ip(session, ip) for ip in batch]
                batch_results = await asyncio.gather(*tasks)

                for j, result in enumerate(batch_results):
                    idx = i + j
                    results[idx] = result
                    print(f"[{idx:>3}] {"YourIpHere:24601":<22} | {result}")

            try:
                choice, target = await asyncio.to_thread(menu_handler, ip_ports)
                if choice == "exit":
                    print("Exiting logger.")
                    return
                if choice == "1" and target:
                    await run_extra_command(session, target)
                elif choice == "2" and target:
                    open_browser(target)
            except Exception as e:
                print(f"Menu error: {e}")

if __name__ == "__main__":
    asyncio.run(main_loop())
