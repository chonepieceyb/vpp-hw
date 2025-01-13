#!/usr/bin/python3
import subprocess
import sys, os, time, re
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sockfile = "/run/vpp/remote/cli_remote.sock"
vppctl_binary = (
    PROJECT_ROOT + "/build-root/build-vpp-native/vpp/bin/vppctl"
)

def help_func():
    print("Usage: ./traffic_monitor.py")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--test_duration", type=int, help="Duration to let IPSec work", default=3, required=False)
    parser.add_argument('-d', '--dpdk-latency-show', help='use dpdk-latency-show', required=False, action='store_true')
    args = parser.parse_args()
    test_duration = args.test_duration
    dpdk_latency_show = args.dpdk_latency_show

    print(f"Letting VPP work for {test_duration} seconds:")
    if dpdk_latency_show:
        subprocess.run(["sudo", vppctl_binary, "-s", sockfile, "dpdk", "latency", "reset"], check=True)
    else:
        subprocess.run(["sudo", vppctl_binary, "-s", sockfile, "clear", "runtime"], check=True)
    for i in range(test_duration):
        print(f"..{i+1}", end="", flush=True)
        time.sleep(1)
    print("\n==========")

    if dpdk_latency_show:
        subprocess.run(["sudo", vppctl_binary, "-s", sockfile, "dpdk", "latency", "show"], check=True)
    else:
        subprocess.run(["sudo", vppctl_binary, "-s", sockfile, "show", "runtime"], check=True)
