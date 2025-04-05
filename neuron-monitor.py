import asyncio
import aiohttp
import json
import re
import os
import sys
import webbrowser

# Batch settings
BATCH_SIZE = 5
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
        return pad_ansi(f"\033[91m{val:.1f}%\033[0m", 6)
    elif val < thresholds[1]:
        return pad_ansi(f"\033[93m{val:.1f}%\033[0m", 6)
    else:
        return pad_ansi(f"\033[92m{val:.1f}%\033[0m", 6)

def colorize_placement(position, max_val=100):
    try:
        val = int(position)
    except:
        return position
    score = min(max(val - 1, 0), max_val - 1) / (max_val - 1)
    if score <= 0.2:
        color = "\033[92m"
    elif score <= 0.5:
        color = "\033[93m"
    elif score <= 0.8:
        color = "\033[38;5;208m"
    else:
        color = "\033[91m"
    return f"{color}{val}\033[0m/100"

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

def parse_vault_short(delegate_data):
    try:
        parsed = json.loads(delegate_data)
        if isinstance(parsed, list) and parsed:
            vault = parsed[0].get("vault", "")
            if len(vault) >= 6:
                return f"{vault[:4]}..{vault[-4:]}"
            return vault
    except:
        return "N/A       "

def parse_stake_check(stake_data):
    try:
        if stake_data == "True":
            return "True "
        else:
            return "N/A  "
    except:
        return "N/A  "

def parse_connection_status(data):
    try:
        parsed = json.loads(data)
        central = parsed.get("central")
        pubsub = parsed.get("pubsub")
        if isinstance(central, bool) and isinstance(pubsub, bool):
            c = "\033[92mOnline\033[0m" if central else "\033[91mClosed\033[0m"
            p = "\033[92mOnline\033[0m" if pubsub else "\033[91mClosed\033[0m"
            return f"{c}/{p}"
    except Exception:
        pass
    return "N/A          "

def parse_wallet_short(api_test_data):
    try:
        parsed = json.loads(api_test_data)
        wallet = parsed.get("data", "")
        if len(wallet) >= 8:
            return f"{wallet[:4]}..{wallet[-4:]}"
        return wallet
    except:
        return "N/A       "

def parse_satori_amount(html_text):
    try:
        match = re.search(r"Satori:\s*([0-9.]+)", html_text)
        if match:
            return match.group(1).rjust(6)
    except:
        pass
    return "N/A   "

def format_satori(satori_val, stake_status):
    if stake_status.strip() == "N/A":
        return f"\033[91m{satori_val}\033[0m"  # red
    return satori_val

async def process_ip(session, ip_port):
    sys_url = f"http://{ip_port}/system_metrics"
    stats_url = f"http://{ip_port}/fetch/wallet/stats/daily"
    delegate_get_url = f"http://{ip_port}/delegate/get"
    stake_check_url = f"http://{ip_port}/stake/check"
    status_url = f"http://{ip_port}/connections-status/refresh"
    api_test_url = f"http://{ip_port}/api/test"
    chat_url = f"http://{ip_port}/chat"

    sys_data, stats_data, delegate_get_data, stake_check_data, conn_status_data, api_test_data, chat_data = await asyncio.gather(
        fetch(session, sys_url),
        fetch(session, stats_url),
        fetch(session, delegate_get_url),
        fetch(session, stake_check_url),
        fetch(session, status_url),
        fetch(session, api_test_url),
        fetch(session, chat_url)
    )

    version, cpu, mem, uptime = parse_system_metrics(sys_data)
    stats = parse_wallet_stats(stats_data)
    vault_trunc = parse_vault_short(delegate_get_data)
    stake = parse_stake_check(stake_check_data)
    conn_status = parse_connection_status(conn_status_data)
    wallet_trunc = parse_wallet_short(api_test_data)
    satori_raw = parse_satori_amount(chat_data)
    satori = format_satori(satori_raw, stake)

    return f"{version} | {cpu} | {mem} | {uptime} | {vault_trunc} | {stake} | {conn_status} | {wallet_trunc} | {satori} | {stats}"

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
            print(f"{'Idx':<5} {'IP:PORT':<22} | {'Version':<7} | {'CPU':<6} | {'MEM':<6} | {'Uptime':<7} | {'Delegate':<10} | {'Stake':<5} | {'CENT/PUBSUB':<13} | {'Wallet':<10} | {'Satori':<6} | Stats")
            print("-" * 154)

            results = [None] * len(ip_ports)
            for i in range(0, len(ip_ports), BATCH_SIZE):
                batch = ip_ports[i:i + BATCH_SIZE]
                tasks = [limited_process_ip(session, ip) for ip in batch]
                batch_results = await asyncio.gather(*tasks)

                for j, result in enumerate(batch_results):
                    idx = i + j
                    results[idx] = result
                    print(f"[{idx:>3}] {ip_ports[idx]:<22} | {result}")

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
