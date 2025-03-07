import os
import json
import pandas as pd
from collections import defaultdict, deque
import numpy as np
import logging
import sys

ROOT_PATH = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(ROOT_PATH, "simulator_confs")
MAX_BATCHSIZE = 256


logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)


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

class Graph:
    def __init__(self, config_file, profiling_file, input_io_file):
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
        self._load_config(config_file)
        self._load_profiling_data(profiling_file)
        self._load_input_io_data(input_io_file)
        self._build_graph()
        self.nodes = self._topological_sort()  # 在构造结束时完成拓扑排序

    def _load_config(self, config_file):
        """加载 JSON 配置文件"""
        with open(config_file, 'r') as file:
            config = json.load(file)
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

class NodeRuntime:
    def __init__(self, node: Node, workload):
        self.pkts = 0
        self.batch_size = node.batch_size
        self.ratio = 0
        self.process_fn = self._build_process_fn(node) 
        self.name = node.name
        
        for w in node.workloads: 
            self.ratio += workload[w]         
    
    def _build_process_fn(self, node: Node):
        self.batch_time_dict = node.profiling_data.set_index('batchsize')['time_ns_total'].to_dict()
        def process_fn(batchsize):
            if (batchsize not in self.batch_time_dict):
                print("batchsize: %d not in dict of node %s"%(batchsize, self.name))
            return self.batch_time_dict[batchsize]
        return process_fn
    
    def enqueue_pkts(self, nb):
        #return the number of packet processed and time_ns
        self.pkts += (nb * self.ratio) 
        processed_nb = 0
        porcessed_time = 0
        while self.pkts > self.batch_size: 
            to_be_process = self.batch_size
            if self.batch_size == 0:  
                # 0 代表不用攒包
                to_be_process = min(MAX_BATCHSIZE, np.floor(self.pkts).astype(int))
            if to_be_process == 0:
                break
            processed_nb += to_be_process
            porcessed_time += self.process_fn(to_be_process)
            self.pkts -= to_be_process
        return processed_nb, porcessed_time
                        
class Simulator:
    def __init__(self):
        config_file = os.path.join(CONFIG_PATH, "config.json")  # JSON 配置文件路径
        profiling_file = os.path.join(CONFIG_PATH, "profiling.csv")  # 节点性能文件路径
        input_io_file = os.path.join(CONFIG_PATH, "input.csv")  # 输入 IO 文件路径
        self.graph = Graph(config_file, profiling_file, input_io_file)
        self.input_time_us_fn = self._built_input_time_us_fn() 
        self.input_packet_fn = self._build_input_packet_fn()
    
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
    
    def run(self, repeat_time):
        # return throughput
        count  = 0
        total_time_ns = 0
        total_pkts = 0
        last_process_time_ns = 0
        
        # init node runtime 
        node_runtimes = []
        for node in self.graph.nodes:
            node_runtimes.append(NodeRuntime(node, self.graph.workloads))        
        
        while count < repeat_time:
            process_time_ns  = 0
            input_pkts = self.input_packet_fn(np.round(last_process_time_ns / 1000))
            input_ns = self.input_time_us_fn(np.round(last_process_time_ns / 1000)) * 1000
            total_time_ns += input_ns
            logging.debug('获取数据包 %d, 耗时 %d (ns)'%(input_pkts, total_time_ns))
            for nr in node_runtimes:
                nb, time_ns = nr.enqueue_pkts(input_pkts)
                process_time_ns  += time_ns
                if nb != 0:
                    logging.debug('节点: %s, 处理 %d 数据包, 耗时 %d (ns)'%(nr.name, nb, time_ns))
            
            total_time_ns += process_time_ns
            total_pkts += input_pkts
            last_process_time_ns = process_time_ns
            count += 1
        
        assert total_time_ns != 0
        logging.info("totaltime_ns: %d"%total_time_ns)
        logging.info("totalpkts: %d"%total_pkts)
        return total_pkts / (total_time_ns / 1E9)
                 

# 示例用法
if __name__ == "__main__":
    s = Simulator()
    s.set_batch_all(256)
    throughput = s.run(1000)
    print("throughput (mpps): %f"%(throughput/1E6))
