import json 
import random

CONFIG_FILE="/mnt/disk1/yanghanlin/vpp-hw-rl/motivation_configs/motivation_exp_%s_settings.json"

##we assume the traffic is high skew 

exps_pto_num = 8
exp_timeout = 180
dispatcher_batch_sizes = list(range(32, 256 + 16, 16))
protocol_batch_sizes = list(range(16, 32 + 8, 4))
lookup_batch_sizes = list(range(32, 256 + 16, 16))

def __set_dispatcher_num(config, dispatcher_num):
    config["dispatcher"] = {}
    config["dispatcher"]["num"] = dispatcher_num
    config["nodes"] = {}


def __set_node_config(config, node_name, batch_size, timeout):
    if "nodes" not in config.keys():
        config["nodes"] = {}
    config["nodes"][node_name] = {}
    config["nodes"][node_name]["size"] = batch_size
    config["nodes"][node_name]["timeout"] = timeout
 
def __set_protocol_node_config(config, batch_size, timeout):
    for i in range(16):
        id = i + 1
        __set_node_config(config, "protocol%d"%id, batch_size, timeout)   

#rule1, dispatcher.size and sum(protocolx.size)
def gen_rule1_eq_config():
    config_lines = []
    for pto_bz in protocol_batch_sizes:
        for dp_bz in dispatcher_batch_sizes:
            if dp_bz == pto_bz * exps_pto_num:
                exp_config = {}
                __set_dispatcher_num(exp_config, exps_pto_num)
                __set_node_config(exp_config, "dispatcher", dp_bz, exp_timeout)
                __set_protocol_node_config(exp_config, pto_bz, exp_timeout)
                __set_node_config(exp_config, "ip6-lookup", 256, 0)
                config_lines.append(json.dumps(exp_config) + '\n')
    return config_lines

def gen_rule1_le_config():
    config_lines = []
    for pto_bz in protocol_batch_sizes:
        for dp_bz in dispatcher_batch_sizes:
            if dp_bz < pto_bz * exps_pto_num:
                exp_config = {}
                __set_dispatcher_num(exp_config, exps_pto_num)
                __set_node_config(exp_config, "dispatcher", dp_bz, exp_timeout)
                __set_protocol_node_config(exp_config, pto_bz, exp_timeout)
                __set_node_config(exp_config, "ip6-lookup", 256, 0)
                config_lines.append(json.dumps(exp_config) + '\n')
    return config_lines

def gen_rule1_ge_config():
    config_lines = []
    for pto_bz in protocol_batch_sizes:
        for dp_bz in dispatcher_batch_sizes:
            if dp_bz > pto_bz * exps_pto_num:
                exp_config = {}
                __set_dispatcher_num(exp_config, exps_pto_num)
                __set_node_config(exp_config, "dispatcher", dp_bz, exp_timeout)
                __set_protocol_node_config(exp_config, pto_bz, exp_timeout)
                __set_node_config(exp_config, "ip6-lookup", 256, 0)
                config_lines.append(json.dumps(exp_config) + '\n')
    return config_lines

def gen_rule2_eq_config():
    config_lines = []
    for pto_bz in protocol_batch_sizes:
        for lk_bz in lookup_batch_sizes:
            if lk_bz == pto_bz * exps_pto_num:
                exp_config = {}
                __set_dispatcher_num(exp_config, exps_pto_num)
                __set_node_config(exp_config, "dispatcher", 256, 0)
                __set_protocol_node_config(exp_config, pto_bz, exp_timeout)
                __set_node_config(exp_config, "ip6-lookup", lk_bz, exp_timeout)
                config_lines.append(json.dumps(exp_config) + '\n')
    return config_lines


def gen_rule2_le_config():
    config_lines = []
    for pto_bz in protocol_batch_sizes:
        for lk_bz in lookup_batch_sizes:
            if lk_bz < pto_bz * exps_pto_num:
                exp_config = {}
                __set_dispatcher_num(exp_config, exps_pto_num)
                __set_node_config(exp_config, "dispatcher", 256, 0)
                __set_protocol_node_config(exp_config, pto_bz, exp_timeout)
                __set_node_config(exp_config, "ip6-lookup", lk_bz, exp_timeout)
                config_lines.append(json.dumps(exp_config) + '\n')
    return config_lines

def gen_rule2_ge_config():
    config_lines = []
    for pto_bz in protocol_batch_sizes:
        for lk_bz in lookup_batch_sizes:
            if lk_bz > pto_bz * exps_pto_num:
                exp_config = {}
                __set_dispatcher_num(exp_config, exps_pto_num)
                __set_node_config(exp_config, "dispatcher", 256, 0)
                __set_protocol_node_config(exp_config, pto_bz, exp_timeout)
                __set_node_config(exp_config, "ip6-lookup", lk_bz, exp_timeout)
                config_lines.append(json.dumps(exp_config) + '\n')
    return config_lines
                

if __name__ == '__main__':
    rule1_config_lines = gen_rule1_eq_config()
    rule1_config_lines.extend(gen_rule1_le_config())
    rule1_config_lines.extend(gen_rule1_ge_config())
    random.shuffle(rule1_config_lines)
    rule2_config_lines = gen_rule2_eq_config()
    rule2_config_lines.extend(gen_rule2_le_config())
    rule2_config_lines.extend(gen_rule2_ge_config())
    random.shuffle(rule2_config_lines)

    print(len(rule1_config_lines))
    print(len(rule2_config_lines))

    
    with open(CONFIG_FILE%"rule1", 'w') as f:
      f.writelines(rule1_config_lines)
    with open(CONFIG_FILE%"rule2", 'w') as f:
      f.writelines(rule2_config_lines)
