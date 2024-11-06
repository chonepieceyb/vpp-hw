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
    total_lat_ns = Column(Integer)
    total_pkts = Column(Integer)
    throughput_actual = Column(Float)
    timeout_pkts = Column(Integer)
    avg_lat_ns = Column(Float)
    imissed = Column(Integer)
    calls = Column(Integer)
    vectors = Column(Integer)
    suspends = Column(Integer)
    clocks = Column(Float)
    avg_dpc_per_call = Column(Float)
    total_dto = Column(Integer)
    create_time = Column(DateTime)
    deleted = Column(Boolean)

class PerfData(Base):
    __tablename__ = 'vpp_perf_data'
    id = Column(Integer, primary_key=True)
    batch_size_setting = Column(Integer)
    # L1-dcache-loads,L1-dcache-load-misses,L1-dcache-store,icache.hit,icache.misses,icache.ifdata_stall,LLC-loads,LLC-load-misses,LLC-stores,L2_RQSTS.ALL_DEMAND_MISS
    L1_dcache_loads = Column(Integer)
    L1_dcache_load_misses = Column(Integer)
    L1_dcache_store = Column(Integer)
    icache_hit = Column(Integer)
    icache_misses = Column(Integer)
    icache_ifdata_stall = Column(Integer)
    LLC_loads = Column(Integer)
    LLC_load_misses = Column(Integer)
    LLC_stores = Column(Integer)
    L2_RQSTS_ALL_DEMAND_MISS = Column(Integer)
    create_time = Column(DateTime)
    deleted = Column(Boolean)

# 初始化数据库连接:
engine = create_engine('sqlite:///vpp_exp.db')
# 创建数据库表
Base.metadata.create_all(engine)
# 创建DBSession类型:
session_maker = sessionmaker(bind=engine)
DBSession = session_maker()

duration = 3
exp_repeat_count = 10

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
    pattern1 = re.compile(r"Ethernet1 \[latency\] total_lat\(ns\): (\d+), pkts: (\d+), timeout_pkts: (\d+), avg_lat\(ns\): (\d+), imissed: (\d+)")
    pattern2 = re.compile(r"Ethernet0 \[latency\] total_lat\(ns\): \d+, pkts: \d+, timeout_pkts: \d+, avg_lat\(ns\): \d+, imissed: (\d+)")
    lat_stats = {}
    match = pattern1.search(input_string)
    if match:
        lat_stats = {
            "total_lat_ns": int(match.group(1)),
            "total_pkts": int(match.group(2)),
            "timeout_pkts": int(match.group(3)),
            "avg_lat_ns": int(match.group(4)),
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
    key_dict = {node: {"batch_size": batch_size, "timeout": timeout} for node, batch_size, timeout in key_tuple}
    now = datetime.now()
    print("--Insert data into database--")
    for node_name, runtime in runtime_stat.items():
        data = VppExpData()
        try:
            data.name = node_name
            data.batch_size_setting = key_dict.get(node_name, {}).get('batch_size', None)
            data.time_out_setting = key_dict.get(node_name, {}).get('batch_size', None)
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
        #     print(f"Insert {node_name} into database")
        except Exception as e:
            print(f"An error occurred while inserting data into database: {e}")
    DBSession.commit()

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
    for node, batch_size, timeout in kt:
        command.extend([node, "size", str(batch_size), "timeout", str(timeout)])
    print(f"Running command: {command}")
    subprocess.run(command, check=True)

def _act_dpdk_input(kt):
    node, batch_size, timeout = kt[0]
    subprocess.run(["sudo", "vppctl", "-s", "/run/vpp/remote/cli_remote.sock", "set", "dpdk", "batchsize", "Ethernet0", "batchsize", str(batch_size), "timeout", str(timeout)], check=True)

# 单独修改dpdk-input节点的batch_size和timeout
def _gen_combinations_dpdk_input(partial=None):
    nodes = ['dpdk-input']
    batch_sizes = range(16, 256+16, 16)
    timeouts = [1.0]
    for batch_size in batch_sizes:
        for timeout in timeouts:
            yield [[node, batch_size, timeout] for node in nodes]

# 所有节点的batch_size和timeout都相同
def _gen_combinations_same_babtch(partial=None):
    nodes = ["ip4-input-no-checksum", "ip6-input", "nat-pre-in2out", "ip4-inacl"]
    batch_sizes = range(16, 256+16, 16)
    timeouts = [90000000]
    for batch_size in batch_sizes:
        for timeout in timeouts:
            yield [[node, batch_size, timeout] for node in nodes]

# 生成所有节点的batch_size和timeout的组合
def _gen_combinations(partial=None):
    nodes = ["ip4-input-no-checksum", "ip6-input", "nat-pre-in2out", "ip4-inacl"]
    batch_sizes = [16, 32, 48, 64, 96, 128, 160, 192, 224, 256]
    timeouts = [90000000]

    for batch_size in batch_sizes:
        for timeout in timeouts:
            if partial is None:
                new_partial = []
            else:
                new_partial = list(partial)
            new_partial.append([nodes[len(new_partial)], batch_size, timeout])
            if len(new_partial) == len(nodes):
                yield new_partial
            else:
                for combination in _gen_combinations(new_partial):
                    yield combination

def record_exp_data():
    for key_tuple in _gen_combinations_same_babtch():
        print(f"Running with key_tuple: {key_tuple}", file=sys.stderr)
        for i in range(exp_repeat_count):
            _act(key_tuple)
            reset_stats()
            time.sleep(duration)
            get_stats(key_tuple)

# used to reocrd perf-tool performance data
def record_perf_data():
    perf_pattern = re.compile(r"Performance counter stats for process id '(\d+)':\s*\n*((?:.*\n)*).*seconds time elapsed")
    now = datetime.now()
    # [修改这里控制生成key_tuple的方式]
    for key_tuple in _gen_combinations_dpdk_input():
        print(f"Running with key_tuple: {key_tuple}", file=sys.stderr)
        for i in range(exp_repeat_count):
            # [修改这里控制改batch_size的方式]
            _act_dpdk_input(key_tuple)
            # sudo perf stat -e L1-dcache-loads,L1-dcache-load-misses,L1-dcache-store,icache.hit,icache.misses,icache.ifdata_stall,LLC-loads,LLC-load-misses,LLC-stores,L2_RQSTS.ALL_DEMAND_MISS -p $(ps -eLo pid,comm | grep vpp_wk_0 | awk '{print $1}') sleep 3
            ps_reault = subprocess.check_output(['ps', '-eLo', 'pid,comm']).decode().split('\n')
            for line in ps_reault:
                if 'vpp_wk_0' in line:
                    vpp_worker_pid = line.split()[0]
            perf_result = subprocess.check_output(['sudo', 'perf', 'stat', '-e', 'L1-dcache-loads,L1-dcache-load-misses,L1-dcache-store,icache.hit,icache.misses,icache.ifdata_stall,LLC-loads,LLC-load-misses,LLC-stores,L2_RQSTS.ALL_DEMAND_MISS', '-p', vpp_worker_pid, 'sleep', str(duration)], stderr=subprocess.STDOUT).decode()
            perf_result = remove_CtrlChars(perf_result)
            match = perf_pattern.search(perf_result)
            if match:
                perf_section = match.group(2)
                lines = perf_section.strip().split("\n")
                perf_stat = {}
                for line in lines:
                    parts = line.split()
                    name = parts[1]
                    value = int(parts[0].replace(',', ''))
                    perf_stat[name] = value
                perf_data = PerfData()
                perf_data.batch_size_setting = key_tuple[0][1]
                perf_data.L1_dcache_loads = perf_stat.get('L1-dcache-loads', None)
                perf_data.L1_dcache_load_misses = perf_stat.get('L1-dcache-load-misses', None)
                perf_data.L1_dcache_store = perf_stat.get('L1-dcache-store', None)
                perf_data.icache_hit = perf_stat.get('icache.hit', None)
                perf_data.icache_misses = perf_stat.get('icache.misses', None)
                perf_data.icache_ifdata_stall = perf_stat.get('icache.ifdata_stall', None)
                perf_data.LLC_loads = perf_stat.get('LLC-loads', None)
                perf_data.LLC_load_misses = perf_stat.get('LLC-load-misses', None)
                perf_data.LLC_stores = perf_stat.get('LLC-stores', None)
                perf_data.L2_RQSTS_ALL_DEMAND_MISS = perf_stat.get('L2_RQSTS.ALL_DEMAND_MISS', None)
                perf_data.create_time =  now
                perf_data.deleted = False
                DBSession.add(perf_data)
                DBSession.commit()
            else:
                print("No match found")

if __name__ == "__main__":
    reset_stats()
    record_perf_data()

# if __name__ == "__main__":
#     reset_stats()
#     time.sleep(1)
#     for i in range(3):
#         stats = get_stats()
#         # print(stats)
#         time.sleep(1)
