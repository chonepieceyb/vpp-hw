#!/usr/bin/python3
import subprocess
import sys, os, time, re
import argparse

# 使用示例：sudo python3 vpp_run.py -c 10,11-12

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# vpp和vppctl的路径
vppctl_binary = os.path.join(PROJECT_ROOT , "build-root/build-vpp-native/vpp/bin/vppctl")
vpp_binary = os.path.join(PROJECT_ROOT, "build-root/build-vpp-native/vpp/bin/vpp")

# dpdk绑定的网卡名
Ethernet0 = "Ethernet0"
Ethernet1 = "Ethernet1"

# VPP runtime socket目录位置
VPP_RUNTIME_DIR = "/run/vpp/remote"
SOCKFILE = os.path.join(VPP_RUNTIME_DIR, "cli_remote.sock")
VPP_REMOTE_PIDFILE = os.path.join(VPP_RUNTIME_DIR, "vpp_remote.pid")

# 网卡PCIE设置,数组分别是Ethernet0和Ethernet1的PCIE地址
pcie_addr = ["0000:84:00.0", "0000:84:00.1"]

def help_func():
    print("Usage: python3 vpp_run.py options")
    print()
    print("Options:")
    print("    -c <core list>       set CPU affinity. Assign VPP main thread to 1st core")
    print("                         in list and place worker threads on other listed cores.")
    print("                         Cores are separated by commas, and worker cores can include ranges.")
    print()
    print("Example:")
    print("    python3 vpp_run.py -c 1,2-3,6")
    print()
    sys.exit(0)

def err_cleanup():
    print("Remote VPP setup error, cleaning up...")
    if os.path.isfile(VPP_REMOTE_PIDFILE):
        with open(VPP_REMOTE_PIDFILE, "r") as f:
            vpp_remote_pid = f.read()
        subprocess.run(["sudo", "kill", "-9", vpp_remote_pid])
        os.remove(VPP_REMOTE_PIDFILE)
    sys.exit(1)

# 通过worker核心列表计算worker数量，用于设置dpdk网卡队列数
def cal_cores(worker_cores):
    count = 0
    for worker_core in worker_cores:
        if "-" in worker_core:
            worker_core = worker_core.split("-")
            count += int(worker_core[1]) - int(worker_core[0]) + 1
        else:
            count += 1
    return count

def setup_iface():
    # 网卡设置
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "set", "interface", "state", Ethernet0, "up"])
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "set", "interface", "ip", "address", Ethernet0, "192.168.1.1/24"])
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "enable", "ip6", "interface", Ethernet0])
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "set", "interface", "ip", "address", Ethernet0, "::1:1/112"])

    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "set", "interface", "state", Ethernet1, "up"])
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "set", "interface", "ip", "address", Ethernet1, "192.168.2.1/24"])
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "enable", "ip6", "interface", Ethernet1])
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "set", "interface", "ip", "address", Ethernet1, "::2:1/112"])

    # 检查网卡是否启动成功
    output = subprocess.check_output(["sudo", vppctl_binary, "-s", SOCKFILE, "show", "interface"]).decode()
    if Ethernet0 in output and Ethernet1 in output:
        print("Successfully set up interfaces!")
    else:
        print("Failed to set up interfaces!")
        err_cleanup()

    # 借助 192.168.1.100 这个虚拟下一跳IP(Trex收包port的IP)，配置路由表
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "set", "ip", "neighbor", Ethernet1, "192.168.2.2", "04:3f:72:f4:40:4a"])
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "set", "ip", "neighbor", Ethernet1, "::2:2", "04:3f:72:f4:40:4a"])
    # 将IPv4 L3 fwd流量转回node3 Trex
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "ip", "route", "add", "192.168.3.1/32", "via", "192.168.2.2", Ethernet1])
    # 将IPv6 L3 fwd流量转回node3 Trex
    subprocess.run(["sudo", vppctl_binary, "-s", SOCKFILE, "ip", "route", "add", "::3:1/128", "via", "::2:2", Ethernet1])
    print("IPv4&6 L3 fwd configuration successful!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--core", help="set CPU affinity. Assign VPP main thread to 1st core in list and place worker threads on other listed cores. Cores are separated by commas, and worker cores can include ranges.", required=True)
    args = parser.parse_args()

    core_list = args.core

    main_core = None
    worker_core_list = None

    # 正则匹配 -c 传入的 main/worker core 设置
    if not re.match(r"^[0-9]{1,3}((,[0-9]{1,3})|(,[0-9]{1,3}-[0-9]{1,3}))*$", core_list):
        print("error: \"-c\" requires correct cpu isolation core id")
        help_func()

    main_core = core_list.split(",")[0]
    worker_core_list = core_list.split(",")[1:]
    worker_core = ",".join(worker_core_list)

    if main_core == worker_core_list:
        print("error: \"-c\" option bad usage")
        help_func()
    queues_count = cal_cores(worker_core_list)
    print("queues_count:", queues_count)

    if not main_core or not worker_core_list:
        print("require an option: \"-c\"")
        help_func()

    # 启动VPP
    vpp_start_command = f"""sudo {vpp_binary} unix "{{ runtime-dir {VPP_RUNTIME_DIR} cli-listen {SOCKFILE} pidfile {VPP_REMOTE_PIDFILE} }}" \\
                            cpu "{{ main-core {main_core} corelist-workers {worker_core} }}" \\
                            plugins "{{ plugin default {{ enable }} plugin dpdk_plugin.so {{ enable }} plugin crypto_native_plugin.so {{ enable }} plugin crypto_openssl_plugin.so {{enable}} plugin ping_plugin.so {{enable}} plugin nat_plugin.so {{enable}} plugin test_batch.so {{enable}}}}"  \\
                            dpdk "{{ dev {pcie_addr[0]} {{ name {Ethernet0} num-tx-queues {queues_count} num-rx-queues {queues_count} }} \\
                                    dev {pcie_addr[1]} {{ name {Ethernet1} num-tx-queues {queues_count} num-rx-queues {queues_count} }} }}"
                        """

    subprocess.run([vpp_start_command], shell=True)

    print("Remote VPP starting up")

    time.sleep(0.5)

    # 尝试连接vppctl socket
    max_conn_retries = 15
    for conn_count in range(max_conn_retries):
        try:
            output = subprocess.check_output(["sudo", vppctl_binary, "-s", SOCKFILE, "show", "threads"]).decode()
            if not output:
                err_cleanup()
            break
        except subprocess.CalledProcessError:
            if conn_count == max_conn_retries - 1:
                err_cleanup()
            time.sleep(1)

    print("Setting up DPDK interfaces...")

    # 网卡设置 + 路由配置
    setup_iface()

    print("Successfully start remote VPP instance!")