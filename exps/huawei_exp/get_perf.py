import re
import subprocess
import time
import os
import json
import argparse
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

# given follow input string, how to extract vpp_wk_0 (1)‘s each line presented cache hit/miss statistics, store them in a dict
# Example usage for the new input format
input_string = """
                         cache misses detail                         
                        L1I miss/pkt L1D miss/pkt L2 miss/pkt L3 miss/pkt
vpp_main (0)                                                             
vpp_wk_0 (1)                                                             
  ip4-icmp-echo-request        13.88        18.14        9.17        0.00
             dpdk-input          .24         8.48         .14        0.00
              arp-reply        18.48        26.29        7.14        0.00
              arp-input         2.92         7.75        2.58        0.00
   ip4-mfib-forward-rpf         6.67        14.17        3.38        0.00
ip4-mfib-forward-lookup        21.45        26.62        6.16        0.00
              ip6-input          .14          .80         .02        0.00
            ip6-rewrite          .23         1.89         .01        0.00
             ip6-lookup          .21          .93         .03        0.00
  ip4-input-no-checksum          .28         1.09         .04        0.00
               ip4-drop          .28         2.63         .12        0.00
            ip4-rewrite          .51         1.85         .02        0.00
            ip4-receive        25.38        23.89       14.81        0.00
       ip4-load-balance        13.27        33.61        6.86        0.00
             ip4-lookup          .23         1.23         .06        0.00
         ip4-icmp-input         2.19         6.08        3.76        0.00
         ethernet-input          .29         2.44         .20        0.00
             error-drop         1.34        12.31         .04        0.00
                   drop         2.46         8.66         .34        0.00
           Ethernet1-tx          .52         5.56         .15        0.00
       Ethernet1-output          .10          .48        0.00        0.00
"""
@dataclass
class CacheStats:
    name : str = ""
    batchsize : int = 0
    L1I_miss_per_pkt_list: List[float] = field(default_factory=list)
    L1D_miss_per_pkt_list: List[float] = field(default_factory=list)
    L2_miss_per_pkt_list: List[float] = field(default_factory=list)
    L3_miss_per_pkt_list: List[float] = field(default_factory=list)
    
@dataclass
class CacheStat:
    name : str = ""
    batchsize : int = 0
    L1I_miss_per_pkt: float = 0.0
    L1D_miss_per_pkt: float = 0.0
    L2_miss_per_pkt: float = 0.0
    L3_miss_per_pkt: float = 0.0

def get_perf_stats():
    perf_result = ""
    try:
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "stop"], capture_output=False)
        perf_result = subprocess.check_output([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "show", "perfmon", "statistics"]).decode()
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "reset"], capture_output=False)
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "start", "bundle", "cache-detail"], capture_output=False)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running the command: {e}")

    perf_result = remove_CtrlChars(perf_result)
    # Define a pattern to match the section starting with vpp_wk_0 (1) and capture the following lines
    pattern = re.compile(r"vpp_wk_0 \(1\)\s*\n((?:.*\n)*)", re.DOTALL)
    match = pattern.search(perf_result)

    if match:
        # Extract the relevant section
        vpp_wk_0_section = match.group(1)

        # Split the section into lines
        lines = vpp_wk_0_section.strip().split("\n")

        # Process each line to extract statistics
        for line in lines:
            parts = line.split()
            if len(parts) == 5:
                name = parts[0]
                if name not in total_stat:
                    cache_stats = CacheStats()
                    cache_stats.name = name
                    cache_stats.batchsize = batchsize
                    total_stat[name] = cache_stats
                else:
                    cache_stats = total_stat[name]
                print(f"current cache_stats: L1I: {parts[1]}, L1D: {parts[2]}, L2: {parts[3]}, L3: {parts[4]},  name: {parts[0]}")
                cache_stats.L1I_miss_per_pkt_list.append(float(parts[1]))
                cache_stats.L1D_miss_per_pkt_list.append(float(parts[2]))
                cache_stats.L2_miss_per_pkt_list.append(float(parts[3]))
                cache_stats.L3_miss_per_pkt_list.append(float(parts[4]))

def get_avg(stats):
    avg_stats = {}
    for key, value in stats.items():
        avg_stats[key] = {
            "L1_hit/pkt": sum(value["L1_hit/pkt"] for value in stats.values()) / len(stats),
            "L1_miss/pkt": sum(value["L1_miss/pkt"] for value in stats.values()) / len(stats),
            "L2_hit/pkt": sum(value["L2_hit/pkt"] for value in stats.values()) / len(stats),
            "L2_miss/pkt": sum(value["L2_miss/pkt"] for value in stats.values()) / len(stats),
            "L3_hit/pkt": sum(value["L3_hit/pkt"] for value in stats.values()) / len(stats),
            "L3_miss/pkt": sum(value["L3_miss/pkt"] for value in stats.values()) / len(stats),
        }
    return avg_stats

def remove_CtrlChars(string):
    # 去除控制字符
    pattern = re.compile(r'\x1b\[[0-9;]*[mGK]')
    return pattern.sub('', string)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--batchsize", help="batchsize", type=int, required=True)
    parser.add_argument("-c", "--count", help="repeat_count", type=int, required=True)
    batchsize = parser.parse_args().batchsize
    repeat_count = parser.parse_args().count

    total_stat = {}
    res = []
    for i in range(repeat_count):
        get_perf_stats()
        print(f"Get cache stats for {i} times")
        time.sleep(1)
    for node_name, cache_stats in total_stat.items():
        cache_stat = CacheStat()
        cache_stat.name = node_name
        cache_stat.batchsize = cache_stats.batchsize
        cache_stat.L1I_miss_per_pkt = np.average(cache_stats.L1I_miss_per_pkt_list)
        cache_stat.L1D_miss_per_pkt = np.average(cache_stats.L1D_miss_per_pkt_list)
        cache_stat.L2_miss_per_pkt = np.average(cache_stats.L2_miss_per_pkt_list)
        cache_stat.L3_miss_per_pkt = np.average(cache_stats.L3_miss_per_pkt_list)
        res.append(cache_stat)

    os.makedirs(LOG_DIR, exist_ok=True)
    json_file_path = os.path.join(LOG_DIR, f"cache_state_{batchsize}.json")
    with open(json_file_path, "w") as json_file:
        # stat_dict = {stat.name: asdict(stat) for stat in total_stat}
        res.sort(key=lambda x: (x.name, x.batchsize))
        json.dump([asdict(stat) for stat in res], json_file, indent=2)

