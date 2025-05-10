import asyncio
import aiohttp
import json
import re
import os

# Settings
BATCH_AT_ONCE = 3
PARENT_STATUS_URL = "http://localhost:24601/proxy/parent/status"

# Global rewards mapping
wallet_rewards = {}

# Utility functions
ansi_escape = re.compile(r'\x1B\[[0-?9;]*[mK]')
def real_length(s):
    return len(ansi_escape.sub('', s))

def pad_ansi(s, width):
    return s + ' ' * max(0, width - real_length(s))

def read_ip_ports(file_path):
    with open(file_path, "r") as f:
        return [line.strip() for line in f if line.strip()]

def colorize_cpu(value, thresholds=(50, 80)):
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

def colorize_mem(value, thresholds=(50, 80)):
    try:
        val = float(value)
    except:
        return pad_ansi(f"{value}", 6)
    if val < thresholds[0]:
        return pad_ansi(f"\033[92m{val:.1f}%\033[0m", 6)
    elif val < thresholds[1]:
        return pad_ansi(f"\033[93m{val:.1f}%\033[0m", 6)
    else:
        return pad_ansi(f"\033[91m{val:.1f}%\033[0m", 6)

def colorize_placement(position):
    try:
        val = int(position)
    except:
        return position
    if val < 51:
        color = "\033[92m"
    else:
        color = "\033[38;5;208m"
    return f"{color}{val}\033[0m/100"

async def fetch(session, url):
    try:
        async with session.get(url) as response:
            return await response.text()
    except:
        return None

async def fetch_parent_rewards(session):
    global wallet_rewards
    data = await fetch(session, PARENT_STATUS_URL)
    if data:
        try:
            parsed = json.loads(data)
            wallet_rewards = {}
            for entry in parsed:
                wallet = entry.get("address", "").strip()
                reward = entry.get("reward", 0)
                if wallet:
                    wallet_rewards[wallet] = reward
        except:
            pass

def parse_system_metrics(data):
    try:
        parsed = json.loads(data)
        version = parsed.get("version", "N/A").ljust(7)
        cpu = colorize_cpu(parsed.get("cpu_usage_percent", "N/A"))
        mem = colorize_mem(parsed.get("memory", {}).get("percent", "N/A"))
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
            if len(vault) >= 8:
                return f"{vault[:4]}..{vault[-4:]}"
            else:
                return vault
    except:
        pass
    return "\033[91mN/A\033[0m       "

def parse_stake_check(stake_data):
    if stake_data == "True":
        return "\033[92mTrue\033[0m "
    else:
        return "\033[91mN/A \033[0m "

def parse_wallet(api_test_data):
    try:
        parsed = json.loads(api_test_data)
        return parsed.get("data", "N/A").ljust(34)
    except:
        return "N/A                               "

async def process_ip(session, ip_port):
    sys_url = f"http://{ip_port}/system_metrics"
    stats_url = f"http://{ip_port}/fetch/wallet/stats/daily"
    delegate_get_url = f"http://{ip_port}/delegate/get"
    stake_check_url = f"http://{ip_port}/stake/check"
    api_test_url = f"http://{ip_port}/api/test"

    sys_data, stats_data, delegate_data, stake_data, api_test_data = await asyncio.gather(
        fetch(session, sys_url),
        fetch(session, stats_url),
        fetch(session, delegate_get_url),
        fetch(session, stake_check_url),
        fetch(session, api_test_url)
    )

    version, cpu, mem, uptime = parse_system_metrics(sys_data)
    stats = parse_wallet_stats(stats_data)
    vault_trunc = parse_vault_short(delegate_data)
    stake = parse_stake_check(stake_data)
    wallet = parse_wallet(api_test_data)

    wallet_clean = wallet.strip()
    reward = wallet_rewards.get(wallet_clean, None)

    if reward is not None:
        reward_text = f"{reward:.4f}".rjust(6)
    else:
        reward_text = "N/A   "

    return f"{version} | {cpu} | {mem} | {uptime} | {vault_trunc} | {stake} | {wallet} | {reward_text} | {stats}"

async def limited_process_ip(session, sem, ip_port):
    async with sem:
        return await process_ip(session, ip_port)

async def display_loop(ip_ports):
    sem = asyncio.Semaphore(5)
    os.system("cls" if os.name == "nt" else "clear")
    async with aiohttp.ClientSession() as session:
        await fetch_parent_rewards(session)

        print(f"===== Neuron Monitor - Made by SealClubber =====")
        print(f"{'Idx':<5} {'IP:PORT':<22} | {'Version':<7} | {'CPU':<6} | {'MEM':<6} | {'Uptime':<7} | {'Delegate':<10} | {'Stake':<5} | {'Wallet':<34} | {'Reward':<6} | Stats")
        print("-" * 29 + "+" + "-" * 9 + "+" + "-" * 8 + "+" + "-" * 8 + "+" + "-" * 9 + "+" + "-" * 12 + "+" + "-" * 7 + "+" + "-" * 36 + "+" + "-" * 8 + "+" + "-" * 27)

        rewards_list = []

        for i in range(0, len(ip_ports), BATCH_AT_ONCE):
            batch = ip_ports[i:i+BATCH_AT_ONCE]
            tasks = [limited_process_ip(session, sem, ip) for ip in batch]
            results = await asyncio.gather(*tasks)

            for j, result in enumerate(results):
                idx = i + j
                print(f"[{idx:>3}] {ip_ports[idx]:<22} | {result}")

                parts = result.split('|')
                if len(parts) >= 8:
                    reward_str = parts[7].strip()
                    try:
                        reward_value = float(reward_str)
                        rewards_list.append(reward_value)
                    except:
                        pass

    non_zero_rewards = [reward for reward in wallet_rewards.values() if reward > 0]

    print("\n===== Full Parent-Child Reward Summary =====")
    if non_zero_rewards:
        total_reward = sum(non_zero_rewards)
        avg_reward = total_reward / len(non_zero_rewards)
        max_reward = max(non_zero_rewards)
        min_reward = min(non_zero_rewards)

        print(f"Total reward:   {total_reward:>10.4f}")
        print(f"Average reward: {avg_reward:>10.4f}")
        print(f"Max reward:     {max_reward:>10.4f}")
        print(f"Min reward:     {min_reward:>10.4f}")
    else:
        print("No non-zero rewards found.")

if __name__ == "__main__":
    ip_ports = read_ip_ports("ip.txt")
    asyncio.run(display_loop(ip_ports))
