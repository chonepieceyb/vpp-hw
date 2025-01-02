import re
import subprocess
import time
import os
import sys
from datetime import datetime

from sqlalchemy import Column, String, create_engine, Integer, Float, DateTime, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


nodes = [
         'ethernet-input', 
         'ip4-input-no-checksum', 'ip4-sv-reassembly-feature', 'nat-pre-in2out',
         'nat44-ed-in2out', 'nat44-ed-in2out-slowpath',
         'ip4-inacl', 'ip4-lookup', 'ip4-rewrite', 'Ethernet1-output',
         'ip6-input', 'ip6-lookup', 'ip6-rewrite',
         'arp-input', 'arp-reply',
         'ip4-receive', 'ip4-icmp-input', 'ip4-icmp-echo-request', 'ip4-icmp-echo-request', 'ip4-load-balance', 
         'ip4-mfib-forward-lookup', 'ip4-mfib-forward-rpf', 'ip4-drop', 'error-drop', 'drop', 
         'loop0-output','l2-input', 'l2-fwd', 'l2-output', 'tap0-output', 
         # 调节TX节点偶尔会导致VPP崩溃，暂时不调
        #  'tap0-tx', 'loop0-tx', 'Ethernet1-tx',
         ]
batch_sizes = range(1, 256+1, 1)
# timeout 不可以过大，否则会导致时间轮失效无法攒包
timeout = 2000
duration = 3
exp_repeat_count = 3

Base = declarative_base()

class VppExpData(Base):
    # 表的名字:
    __tablename__ = 'vpp_exp_data'

    # 表的结构:
    id = Column(Integer, primary_key=True)
    name = Column(String(30))
    batch_size_setting = Column(Integer)
    time_out_setting = Column(Integer)
    batch_size_actual = Column(Float)
    time_out_actual = Column(Float)
    L1I_cache_miss = Column(Float)
    L1D_cache_miss = Column(Float)
    L2_cache_miss = Column(Float)
    L3_cache_miss = Column(Float)
    avg_throughput_pkts = Column(Integer)
    avg_throughput_bits = Column(Integer)
    throughput_actual = Column(Float)
    avg_lat_ns = Column(Integer)
    timeout_pkts = Column(Integer)
    total_pkts = Column(Integer)
    imissed = Column(Integer)
    calls = Column(Integer)
    vectors = Column(Integer)
    suspends = Column(Integer)
    clocks = Column(Float)
    avg_dpc_per_call = Column(Float)
    total_dto = Column(Integer)
    create_time = Column(DateTime)
    deleted = Column(Boolean)

# 初始化数据库连接:
engine = create_engine("sqlite:///node_clock_exp_all.sqlite")

# 新创建数据库表
Base.metadata.create_all(engine)

# 连接到现有数据库
# Base.metadata.bind = engine
# Base.metadata.reflect(engine)

# 创建DBSession
session_maker = sessionmaker(bind=engine)
DBSession = session_maker()

def extract_vpp_wk_0_perf_stats(input_string):
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
            if len(parts) == 5:
                key = parts[0]
                stats[key] = {
                    "L1I_miss_per_pkt": float(parts[1]),
                    "L1D_miss_per_pkt": float(parts[2]),
                    "L2_miss_per_pkt": float(parts[3]),
                    "L3_miss_per_pkt": float(parts[4]),
                }
    return stats

def extract_lat_stats(input_string):
    pattern1 = re.compile(r"Ethernet1, avg_throughput\(pkt/s\): (\d+), avg_throughput\(bits/s\): (\d+), avg_lat\(ns\): (\d+), timeout_pkts: (\d+), total_pkts: (\d+), imissed: (\d+), total_latency: (\d+)")
    pattern2 = re.compile(r"Ethernet0, avg_throughput\(pkt/s\): (\d+), avg_throughput\(bits/s\): (\d+), avg_lat\(ns\): (\d+), timeout_pkts: (\d+), total_pkts: (\d+), imissed: (\d+), total_latency: (\d+)")
    lat_stats = {}
    match = pattern1.search(input_string)
    if match:
        lat_stats = {
            "avg_throughput_pkts": int(match.group(1)),
            "avg_throughput_bits": int(match.group(2)),
            "avg_lat_ns": int(match.group(3)),
            "timeout_pkts": int(match.group(4)),
            "total_pkts": int(match.group(5)),
            "imissed": int(match.group(6)),
        }
    match = pattern2.search(input_string)
    if match:
        lat_stats['imissed'] = int(match.group(1))
    return lat_stats

def extract_vpp_wk_0_runtime_stats(input_string):
    pattern = re.compile(r"Thread 1 vpp_wk_0 \(lcore \d*\)\s*\n.*\n\s*Name\s+State\s+Calls\s+Vectors\s+Suspends\s+Clocks\s+Vectors/Call\s+Avg DPC/Call\s+Total DTO\s*\n((?:.*\n)*)", re.DOTALL)
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
            if len(parts) == 9:
                key = parts[0]
                stats[key] = {
                    "State": parts[1],
                    "Calls": int(parts[2]),
                    "Vectors": int(parts[3]),
                    "Suspends": int(parts[4]),
                    "Clocks": float(parts[5]),
                    "Vectors_per_Call": float(parts[6]),
                    "Avg_DPC_per_Call": float(parts[7]),
                    "Total_DTO": int(parts[8]),
                }
    # get throughput from show runtime
    throughput_match = re.search(r"Thread 1 vpp_wk_0 \(lcore \d*\)\s*\n.*\n\s*vector rates in ([\d\.e+-]+)", input_string)
    if throughput_match:
        throughput = float(throughput_match.group(1))
    else:
        throughput = None
    # update throughput for every node
    for key, value in stats.items():
        value["throughput_actual"] = throughput
    return stats

def get_stats(key_tuple):
    perf_result = ""
    lat_result = ""
    runtime_result = ""
    try:
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "stop"], capture_output=False, check=True)
        perf_result = subprocess.check_output([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "show", "perfmon", "statistics"]).decode()
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "reset"], capture_output=False, check=True)
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "start", "bundle", "cache-detail"], capture_output=False, check=True)
        lat_result = subprocess.check_output([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "show", "dpdk", "latency"]).decode()
        runtime_result = subprocess.check_output([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "show", "runtime"]).decode()
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "clear", "runtime"], capture_output=False, check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running the command: {e}")
    perf_result = remove_CtrlChars(perf_result)
    perf_stat = extract_vpp_wk_0_perf_stats(perf_result)
    lat_stat = extract_lat_stats(lat_result)
    runtime_stat = extract_vpp_wk_0_runtime_stats(runtime_result)
    # print(f"perf_stats: {perf_stat}")
    # print(f"lat_stat: {lat_stat}")
    # print(f"runtime_stat: {runtime_stat}")
    stats = {**perf_stat, **lat_stat, **runtime_stat}
    store_vpp_exp_data(perf_stat, lat_stat, runtime_stat, key_tuple)
    return stats

# store data into database
def store_vpp_exp_data(perf_stat: dict, lat_stat: dict, runtime_stat: dict, key_tuple: tuple):
    # key_dict = {node: {"batch_size": batch_size, "timeout": timeout} for node, batch_size, timeout in key_tuple}
    node, batch_size, timeout = key_tuple
    now = datetime.now()
    print("--Insert data into database--")
    for node_name, runtime in runtime_stat.items():
        if node_name != node:
            continue
        data = VppExpData()
        try:
            data.name = node_name
            # data.batch_size_setting = key_dict.get(node_name, {}).get('batch_size', None)
            data.batch_size_setting = batch_size
            # data.time_out_setting = key_dict.get(node_name, {}).get('batch_size', None)
            data.time_out_setting = timeout
            data.batch_size_actual = runtime['Vectors_per_Call']
            data.time_out_actual = runtime['Avg_DPC_per_Call']
            data.L1I_cache_miss = perf_stat.get(node_name, {}).get('L1I_miss_per_pkt', None)
            data.L1D_cache_miss = perf_stat.get(node_name, {}).get('L1D_miss_per_pkt', None)
            data.L2_cache_miss = perf_stat.get(node_name, {}).get('L2_miss_per_pkt', None)
            data.L3_cache_miss = perf_stat.get(node_name, {}).get('L3_miss_per_pkt', None)
            data.total_lat_ns = lat_stat.get('total_lat_ns', None)
            data.total_pkts = lat_stat.get('total_pkts', None)
            data.throughput_actual = runtime['throughput_actual']
            data.avg_lat_ns = lat_stat.get('avg_lat_ns', None)
            data.imissed = lat_stat.get('imissed', None)
            data.calls = runtime['Calls']
            data.vectors = runtime['Vectors']
            data.suspends = runtime['Suspends']
            data.clocks = runtime['Clocks']
            data.avg_dpc_per_call = runtime['Avg_DPC_per_Call']
            data.total_dto = runtime['Total_DTO']
            data.create_time = now
            data.deleted = False
            DBSession.add(data)
            DBSession.commit()
            print(f"Insert {node_name}, {batch_size} into database")
        except Exception as e:
            print(f"An error occurred while inserting data into database: {e}")

def reset_stats():
    try:
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "stop"], capture_output=False, check=True)
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "reset"], capture_output=False, check=True)
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "clear", "runtime"], capture_output=False, check=True)
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "dpdk", "latency", "reset"], capture_output=True, check=True)
        subprocess.run([ "sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "perfmon", "start", "bundle", "cache-detail"], capture_output=False, check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running the command: {e}")

def remove_CtrlChars(string):
    # 去除控制字符
    pattern = re.compile(r'\x1b\[[0-9;]*[mGK]')
    return pattern.sub('', string)

def _act(kt):
    command = [
        "sudo",
        "vppctl",
        "-s",
        "/run/vpp/remote/cli_remote.sock",
        "set",
        "node",
        "batch",
    ]
    # for node, batch_size, timeout in kt:
    node, batch_size, timeout = kt
    command.extend([node, "size", str(batch_size), "timeout", str(timeout)])
    command_str = " ".join(command)
    print(f"Running command: {command_str}")
    subprocess.run(command, check=True)

# 单独修改dpdk-input节点的batch_size和timeout
def _gen_combinations_dpdk_input(partial=None):
    nodes = ['dpdk-input']
    batch_sizes = range(16, 256+16, 16)
    timeouts = [1.0]
    for batch_size in batch_sizes:
        for timeout in timeouts:
            yield [[node, batch_size, timeout] for node in nodes]

def reset_all_node_batch_size():
    command = [
        "sudo",
        "vppctl",
        "-s",
        "/run/vpp/remote/cli_remote.sock",
        "set",
        "node",
        "batch",
    ]
    for node in nodes:
        command.extend([node, "size", '256', "timeout", '0'])
    print("Reset all node batch size...")
    subprocess.run(command, check=True)

def record_exp_data():
    for node in nodes:
        for batch_size in batch_sizes:
            global batch_size_setting, time_out_setting
            batch_size_setting = batch_size
            time_out_setting = timeout
            key_tuple = (node, batch_size, timeout)
            print(f"Running with node: {node}, batchsize {batch_size}", file=sys.stderr)
            for i in range(exp_repeat_count):
                reset_all_node_batch_size()
                _act(key_tuple)
                reset_stats()
                time.sleep(duration)
                get_stats(key_tuple)


if __name__ == "__main__":
    record_exp_data()
