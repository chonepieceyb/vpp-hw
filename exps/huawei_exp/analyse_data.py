import re
import subprocess
import time
import os
import json
import argparse
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--test_duration", type=int, help="Duration to let IPSec work", default=3, required=False)
    total_stat = []
    for filename in os.listdir(LOG_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(LOG_DIR, filename)
            match = re.match(r"cache_state_(\w+).json", filename)
            if match:
                batch_size = match.group(1)
            with open(file_path, "r") as json_file:
                data = json.load(json_file)
                print(f"file:{file_path}, len:{len(data)}")
                for stat in data:
                    total_stat.append(stat)
    # 按node_name和batchsize排序
    total_stat.sort(key=lambda x: (x['name'], x['batchsize']))
    # list(map(lambda stat: print(stat), total_stat))
    data_list = []
    for stat in total_stat:
        curr_list = []
        curr_list.append(stat['batchsize'])
        curr_list.append(stat['L1I_miss_per_pkt'])
        curr_list.append(stat['L1D_miss_per_pkt'])
        curr_list.append(stat['L2_miss_per_pkt'])
        curr_list.append(stat['L3_miss_per_pkt'])
        data_list.append(curr_list)
    node_names = [stat['name'] for stat in total_stat]

    #显示所有列
    pd.set_option('display.max_columns', None)
    #显示所有行
    pd.set_option('display.max_rows', None)
    #设置value的显示长度为100，默认为50
    pd.set_option('max_colwidth',100)
    table = pd.DataFrame(data_list, columns=["batch", "L1I", "L1D", "L2", "L3"], index=node_names)
    print(table)

