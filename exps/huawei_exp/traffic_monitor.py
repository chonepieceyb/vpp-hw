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
    args = parser.parse_args()
    test_duration = args.test_duration

    print(f"Letting VPP work for {test_duration} seconds:")
    subprocess.run(["sudo", vppctl_binary, "-s", sockfile, "clear", "runtime"], check=True)
    for i in range(test_duration):
        print(f"..{i+1}", end="", flush=True)
        time.sleep(1)
    print("\n==========")

    subprocess.run(["sudo", vppctl_binary, "-s", sockfile, "show", "runtime"], check=True)
