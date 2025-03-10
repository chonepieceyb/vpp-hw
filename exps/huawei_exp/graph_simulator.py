import os
import json
import pandas as pd
from collections import defaultdict, deque
import numpy as np
import logging
import sys
from dataclasses import dataclass

ROOT_PATH = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(ROOT_PATH, "simulator_confs")

@dataclass
class BasicConf: 
    max_batchsize: int
    dispath_overhead_ns: int
    enq_overhead_fix_ns: int
    enq_overhead_per_pkt_ns: int
    check_queue_ns: int
    

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Node:
    def __init__(self, name, batch_size, workloads, profiling_data):
        """
        初始化节点
        :param name: 节点名称
        :param workloads: 节点对应的业务比例
        :param profiling_data: 节点的性能数据 (DataFrame)
        """
        self.name = name
        self.workloads = workloads
        self.profiling_data = profiling_data  # 存储性能数据 (DataFrame)
        self.next_nodes = []  # 存储下一跳节点名称
        self.batch_size = batch_size

class NodeGraph:
    def __init__(self, config_json, profiling_file, input_io_file):
        """
        初始化图
        :param config_file: JSON 配置文件路径
        :param profiling_file: 节点性能文件路径
        :param input_io_file: 输入 IO 文件路径
        """
        self.node_dict = {}  # 用于快速查找节点 {node_name: Node}
        self.io_time_data = []  # 存储 IO 时间数据 [(process_time_us, io_time_ns)]
        self.input_rate_data = []  # 存储输入速率数据 [(process_time_us, input_rate)]

        # 加载配置文件并初始化图
        self._load_config(config_json)
        self._load_profiling_data(profiling_file)
        self._load_input_io_data(input_io_file)
        self._build_graph()
        self.nodes = self._topological_sort()  # 在构造结束时完成拓扑排序
        self._parse_workload_path()

    def _load_config(self, config):
        self.workloads = config['workloads']
        self.nodes_config = config['nodes']

    def _load_profiling_data(self, profiling_file):
        """加载节点性能数据"""
        self.profiling_df = pd.read_csv(profiling_file)  # 读取性能数据文件

    def _load_input_io_data(self, input_io_file):
        """加载输入 IO 数据"""
        input_io_df = pd.read_csv(input_io_file)  # 读取输入 IO 文件
        self.io_time_data = list(zip(input_io_df['process_time_us'], input_io_df['avg_input_time_ns']))
        self.input_pkt_data = list(zip(input_io_df['process_time_us'], input_io_df['avg_input_pkts']))
        self.io_time_dict = dict(zip(input_io_df['process_time_us'], input_io_df['avg_input_time_ns'] / 1000))
        self.input_pkt_dict = dict(zip(input_io_df['process_time_us'], np.round(input_io_df['avg_input_pkts']).astype(int)))
        self.process_time_range = (input_io_df['process_time_us'].min(), input_io_df['process_time_us'].max())

    def _build_graph(self):
        """构建图"""
        for node_config in self.nodes_config:
            node_name = node_config['name']
            batch_size = node_config['batch_size']
            node_workloads = node_config['workloads']
            node_profiling_data = self.profiling_df[self.profiling_df['name'] == node_name]  # 过滤当前节点的性能数据
            node = Node(node_name, batch_size, node_workloads, node_profiling_data)
            node.next_nodes = node_config['next_nodes']
            self.node_dict[node.name] = node

    def _topological_sort(self):
        """对节点进行拓扑排序，并返回排序后的节点列表"""
        in_degree = defaultdict(int)  # 记录每个节点的入度
        adjacency_list = defaultdict(list)  # 邻接表

        # 初始化入度和邻接表
        for node in self.node_dict.values():
            for next_node_name in node.next_nodes:
                adjacency_list[node.name].append(next_node_name)
                in_degree[next_node_name] += 1

        # 使用队列进行拓扑排序
        queue = deque([node.name for node in self.node_dict.values() if in_degree[node.name] == 0])
        sorted_nodes = []

        while queue:
            current_node_name = queue.popleft()
            sorted_nodes.append(self.node_dict[current_node_name])

            for neighbor in adjacency_list[current_node_name]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 检查是否存在环
        if len(sorted_nodes) != len(self.node_dict):
            raise ValueError("图中存在环，无法进行拓扑排序！")

        return sorted_nodes
    
    def _parse_workload_path(self):
        self.workload_paths = {}
        for workload_name in self.workloads.keys():
            path = [] 
            for node in self.nodes:
                if workload_name in node.workloads:
                    path.append(node)
            self.workload_paths[workload_name] = path
        
class SimuStat: 
    def __init__(self):
        self.time_ns = 0
        self.pkts = 0
        self.overhead_ns = 0

class Simulator:
    class NodeRuntime:
        def __init__(self, node: Node, graph: NodeGraph, basic_config):
            self.pkts = 0
            self.node = node 
            self.process_fn = self._build_process_fn(node) 
            self.basic_config = basic_config
            self.is_out = False
            if len(node.next_nodes) == 0:
                self.is_out = True
            #for latencies
            self.enqueue_ts_queue = deque() 
            self.queue_process_latencies = []
            workload_weights = []
            workload_dict = graph.workloads
            for next_name in node.next_nodes: 
                next_node = graph.node_dict[next_name]
                weight = 0
                for next_w_type in next_node.workloads:
                    if next_w_type in node.workloads:
                        weight += workload_dict[next_w_type]
                workload_weights.append(weight)
            
            _workload_weights = np.array(workload_weights)
            total = _workload_weights.sum()
            self.next_ratio = (_workload_weights / total).tolist()
            
            logging.debug("node runtime %s init finish, summary: "%self.node.name)
            logging.debug("batchsize: %d"%self.node.batch_size)
            if len(self.node.next_nodes) > 0:
                logging.debug(self.node.next_nodes)
                logging.debug(self.next_ratio)
            
            
        def _build_process_fn(self, node: Node):
            self.batch_time_dict = node.profiling_data.set_index('batchsize')['time_ns_total'].to_dict()
            def process_fn(batchsize):
                if (batchsize not in self.batch_time_dict):
                    print("batchsize: %d not in dict of node %s"%(batchsize, self.node.name))
                return self.batch_time_dict[batchsize]
            return process_fn
        
        def build_nexts_runtime(self, runtime_dict): 
            self.next_runtimes = []
            for next_name in self.node.next_nodes: 
                self.next_runtimes.append(runtime_dict[next_name])
        
        def enqueue_pkts(self, nb, stat: SimuStat):
            self.enqueue_ts_queue.append([nb, stat.time_ns])
            self.pkts += nb
            #TODO: overhead may be a function of nb
            overhead_ns = self.basic_config.enq_overhead_fix_ns + nb * self.basic_config.enq_overhead_per_pkt_ns
            stat.time_ns += overhead_ns
            stat.overhead_ns += overhead_ns
            logging.debug('节点: %s, 入队 %f 数据包, 耗时 %d (ns), 当前总时间: %d (ns)'%(self.node.name, nb, overhead_ns, stat.time_ns,))
        
        def _put_to_nexts(self, nb_all, stat: SimuStat):
            for next_r, ratio in zip(self.next_runtimes, self.next_ratio):
                next_r.enqueue_pkts(nb_all * ratio, stat)
        
        def process_pkts(self, stat: SimuStat):
            to_be_process = 0
            stat.time_ns += self.basic_config.check_queue_ns
            stat.overhead_ns += self.basic_config.check_queue_ns
            while self.pkts > self.node.batch_size: 
                to_be_process = self.node.batch_size
                if self.node.batch_size == 0:  
                    # 0 代表不用攒包
                    to_be_process = min(self.basic_config.max_batchsize, np.floor(self.pkts).astype(int))
                if to_be_process == 0:
                    break
                stat.time_ns += self.basic_config.dispath_overhead_ns
                stat.overhead_ns += self.basic_config.dispath_overhead_ns
                time_ns = self.process_fn(to_be_process)
                stat.time_ns += time_ns
                self.pkts -= to_be_process
                logging.debug('节点: %s, 处理 %d 数据包, 耗时 %d (ns), 当前总时间: %d (ns)'%(self.node.name, to_be_process, time_ns, stat.time_ns))
                
                to_be_poped = to_be_process
                while to_be_poped >= 1e-6: 
                    #pop queue time 
                    enq_item = self.enqueue_ts_queue[0]
                    lat_ns = stat.time_ns - enq_item[1]
                    self.queue_process_latencies.append(lat_ns)
                    if enq_item[0] < to_be_poped:
                        to_be_poped -= enq_item[0]
                        self.enqueue_ts_queue.popleft()
                    else:
                        enq_item[0] -= to_be_poped
                        to_be_poped = 0
                        if enq_item[0] <= 1e-6:
                           self.enqueue_ts_queue.popleft() 
                
                self._put_to_nexts(to_be_process, stat)
                if self.is_out:
                    stat.pkts += to_be_process
                
        
    def __init__(self, config_path):
        config_file = os.path.join(config_path, "config.json")  # JSON 配置文件路径
        profiling_file = os.path.join(config_path, "profiling.csv")  # 节点性能文件路径
        input_io_file = os.path.join(config_path, "input.csv")  # 输入 IO 文件路径
        """加载 JSON 配置文件"""
        with open(config_file, 'r') as file:
            config = json.load(file)
        self.graph = NodeGraph(config, profiling_file, input_io_file)
        self.input_time_us_fn = self._built_input_time_us_fn() 
        self.input_packet_fn = self._build_input_packet_fn()
        self.basic_config = BasicConf(**config["basic_config"])

    def _built_input_time_us_fn(self):
        def input_time_us_nf(time_us):
            if time_us < self.graph.process_time_range[0]:
                time_us = self.graph.process_time_range[0]
            elif time_us > self.graph.process_time_range[1]:
                time_us = self.graph.process_time_range[1]
            return self.graph.io_time_dict[time_us]
        return input_time_us_nf
    
    def _build_input_packet_fn(self):   
        def input_packet_us_nf(time_us):
            if time_us < self.graph.process_time_range[0]:
                time_us = self.graph.process_time_range[0]
            elif time_us > self.graph.process_time_range[1]:
                time_us = self.graph.process_time_range[1]
            return self.graph.input_pkt_dict[time_us]
        return input_packet_us_nf 
    
    def set_batch_all(self, batchsize):
        for n in self.graph.nodes:
            n.batch_size = batchsize
            
    def set_batch(self, batch_dict):
        for node_name, batch_size in batch_dict.items():
            self.graph.node_dict[node_name].batch_size = batch_size
    
    def _get_latency(self, node_runtimes_dict, percentile = 90):
        def _get_one_latency(path, percentile):
            lat = 0
            lat_list = []
            for n in path:
                r = node_runtimes_dict[n.name]
                assert len(r.queue_process_latencies) != 0
                print(r.node.name, r.queue_process_latencies)
                lat_percentile = np.percentile(np.array(r.queue_process_latencies), percentile)
                lat += lat_percentile
                lat_list.append((n.name, lat_percentile))
            return lat, lat_list
        latencies = {}
        for workload_name, path in self.graph.workload_paths.items():
            lat, lat_list = _get_one_latency(path, percentile)
            latencies[workload_name] = (lat, lat_list)
        return latencies
    
    def run(self, total_pkts):
        # return throughput

        last_io_ns = 0
        
        # init node runtime 
        logging.debug("Simulation init")
        node_runtimes_dict = {}
        node_runtimes = []
        input_runtime = None 
        for node in self.graph.nodes:
            logging.debug("init node runtime %s"%node.name)
            r = Simulator.NodeRuntime(node, self.graph, self.basic_config)
            node_runtimes.append(r)        
            node_runtimes_dict[node.name] = r
            if node.name == "ethernet-input":
                input_runtime = r
                
        for nr in node_runtimes: 
            nr.build_nexts_runtime(node_runtimes_dict)
            
        stat = SimuStat()
        logging.debug("start simulation")
        while stat.pkts < total_pkts:
            process_time_ns = stat.time_ns - last_io_ns
            input_pkts = self.input_packet_fn(np.round(process_time_ns / 1000))
            input_ns = self.input_time_us_fn(np.round(process_time_ns / 1000)) * 1000
            stat.time_ns += input_ns
            last_io_ns = stat.time_ns
            logging.debug('获取数据包 %d, 耗时 %d (ns), 当前总时间: %d (ns)'%(input_pkts, input_ns, stat.time_ns))
            input_runtime.enqueue_pkts(input_pkts, stat)
            for nr in node_runtimes:
                nr.process_pkts(stat)
        
        assert stat.time_ns != 0
        # logging.info("totaltime_ns: %d"%stat.time_ns)
        # logging.info("totalpkts: %d"%stat.pkts)
        # logging.info("overhead_ns: %d"%stat.overhead_ns)
        # logging.info("overhead: %f"%(stat.overhead_ns/stat.time_ns))
        return stat.pkts / (stat.time_ns / 1E9), self._get_latency(node_runtimes_dict, 90)
                 

# 示例用法
if __name__ == "__main__":
    s = Simulator(CONFIG_PATH)
    for n in s.graph.nodes: 
        print(n.name)
    for batchsize in [32]:
        s.set_batch_all(0)
        s.set_batch({
            # "ip6-input": batchsize,
            # "ip4-input-no-checksum" : batchsize,
            # "nat44-ed-in2out": batchsize,
            # "nat44-ed-in2out-slowpath" :batchsize,
            "arp-input" :  batchsize,
            "ip4-receive" :  batchsize,
            "ip4-mfib-forward-lookup":  batchsize,
            "loop0-output" : batchsize
        })
        throughput, latencies = s.run(300000)
        print("%d: throughput (mpps): %f"%(batchsize, throughput/1E6))
        
        for workload_name, lat_tup in latencies.items(): 
            print("%s: %d (us)"%(workload_name, lat_tup[0]/1000))
            print(lat_tup[1])

    # for batchsize in [0, 16, 32, 48, 64, 96, 128]:
    #     print ("############# only small %d #############"%batchsize)
    #     s.set_batch_all(0)
    #     s.set_batch({
    #         "arp-input" : batchsize,
    #         "ip4-receive" : batchsize,
    #         "ip4-mfib-forward-lookup": batchsize,
    #         "loop0-output" : batchsize
    #     })
    #     throughput = s.run(500000)
    #     print("throughput (mpps): %f"%(throughput/1E6))