import re
import sys
import subprocess
import time
import unicodedata

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
                    "L1I_miss/pkt": float(parts[1]),
                    "L1D_miss/pkt": float(parts[2]),
                    "L1_miss/pkt": float(parts[3]),
                    "L2_miss/pkt": float(parts[4]),
                    "L3_miss/pkt": float(parts[5]),
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

