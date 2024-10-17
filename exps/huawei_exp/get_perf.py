import re
import sys
import subprocess
import time
import unicodedata

# given follow input string, how to extract vpp_wk_0 (1)‘s each line presented cache hit/miss statistics, store them in a dict
# Example usage for the new input format
input_string = """
                            cache hits and misses                               
L1 hit/pkt L1 miss/pkt L2 hit/pkt L2 miss/pkt L3 hit/pkt L3 miss/pkt
vpp_main (0)                                                                              
vpp_wk_0 (1)                                                                              
dpdk-input     344.97        6.62       6.38         .23        .23        0.00
ip4-input-no-checksum     115.99        2.56       2.56        0.00       0.00        0.00
ip4-rewrite     110.60        1.47       1.46        0.00       0.00        0.00
ip4-lookup     109.84        2.85       2.84         .01        .01        0.00
ethernet-input     134.32        3.81       3.01         .80        .80        0.00
Ethernet1-tx     136.98        3.89       3.66         .24        .24        0.00
Ethernet1-output     105.89        1.52       1.51        0.00       0.00        0.00
"""


def extract_vpp_wk_0_stats(input_string):
    # Use regular expressions to find the section between vpp_wk_0 (1) and vpp_wk_1 (2)
    # Define a pattern to match the section starting with vpp_wk_0 (1) and capture the following lines
    pattern = re.compile(r"vpp_wk_0 \(1\)\s*\n((?:.*\n)*)", re.DOTALL)
    match = pattern.search(input_string)

    stats = {}
    if match:
        # Extract the relevant section
        vpp_wk_0_section = match.group(1)

        # Split the section into lines
        lines = vpp_wk_0_section.strip().split("\n")

        # Process each line to extract statistics
        for line in lines:
            parts = line.split()
            if len(parts) == 7:
                key = parts[0]
                stats[key] = {
                    "L1_hit/pkt": float(parts[1]),
                    "L1_miss/pkt": float(parts[2]),
                    "L2_hit/pkt": float(parts[3]),
                    "L2_miss/pkt": float(parts[4]),
                    "L3_hit/pkt": float(parts[5]),
                    "L3_miss/pkt": float(parts[6]),
                }
    return stats

def get_perf_stats():
    perf_result = ""
    try:
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "stop"], capture_output=False)
        perf_result = subprocess.check_output([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "show", "perfmon", "statistics"]).decode()
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "reset"], capture_output=False)
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "start", "bundle", "cache-hierarchy"], capture_output=False)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running the command: {e}")
    perf_result = remove_CtrlChars(perf_result)
    stats = extract_vpp_wk_0_stats(perf_result)
    return stats


def remove_CtrlChars(string):
    # 去除控制字符
    pattern = re.compile(r'\x1b\[[0-9;]*[mGK]')
    return pattern.sub('', string)

if __name__ == "__main__":
    for i in range(10):
        stats = get_perf_stats()
        print(stats)
        time.sleep(1)

