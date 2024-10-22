import re
import sys
import subprocess
import time


def get_perf_stats():
    perf_result = ""
    try:
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "stop"], capture_output=False)
        perf_result = subprocess.check_output([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "show", "perfmon", "statistics"]).decode()
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "reset"], capture_output=False)
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "start", "bundle", "cache-detail"], capture_output=False)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running the command: {e}")
    print(perf_result)
    print("----------")

if __name__ == "__main__":
    while True:
        try:
            get_perf_stats()
            time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)

