import json 

CONFIG_FILE="/mnt/disk1/yanghanlin/vpp-hw-rl/motivation_configs/motivation_exp_%s_settings.json"

##we assume the traffic is high skew 

exps_pto_num = 8
exp_timeout = 180
dispatcher_batch_sizes = list(range(16, 256 + 16, 16))
protocol_batch_sizes = list(range(16, 32, 4))
lookup_batch_sizes = list(range(16, 256 + 16, 16))

def __set_dispatcher_num(config, dispatcher_num):
    exp_config = {}
    exp_config["dispatcher"] = {}
    exp_config["dispatcher"]["num"] = exps_pto_num
    exp_config["nodes"] = {}


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
def __gen_rule1_equal_config(config_lines, dispatcher_bz, protocol_bz, lookup_bz):
    exp_config = {}
    if (dispatcher_bz == protocol_bz * exps_pto_num):
        __set_dispatcher_num(exp_config, exps_pto_num)
        __set_node_config(exp_config, "dispatcher", dispatcher_bz, exp_timeout)
        __set_protocol_node_config(exp_config, protocol_bz, exp_timeout)
        __set_node_config(exp_config, "ip6-lookup", 256, 0)
        config_lines.append(json.dumps(exp_config) + '\n')

def __gen_rule1_less_config(config_lines, dispatcher_bz, protocol_bz, lookup_bz):
    exp_config = {}
    if (dispatcher_bz < protocol_bz * exps_pto_num):
        __set_dispatcher_num(exp_config, exps_pto_num)
        __set_node_config(exp_config, "dispatcher", dispatcher_bz, exp_timeout)
        __set_protocol_node_config(exp_config, protocol_bz, exp_timeout)
        __set_node_config(exp_config, "ip6-lookup", 256, 0)
        config_lines.append(json.dumps(exp_config) + '\n')

def __gen_rule1_larger_config(config_lines, dispatcher_bz, protocol_bz, lookup_bz):
    exp_config = {}
    if (dispatcher_bz > protocol_bz * exps_pto_num):
        __set_dispatcher_num(exp_config, exps_pto_num)
        __set_node_config(exp_config, "dispatcher", dispatcher_bz, exp_timeout)
        __set_protocol_node_config(exp_config, protocol_bz, exp_timeout)
        __set_node_config(exp_config, "ip6-lookup", 256, 0)
        config_lines.append(json.dumps(exp_config) + '\n')

#rule2  sum(protocolx.size) and lookup.size
def __gen_rule2_equal_config(config_lines, dispatcher_bz, protocol_bz, lookup_bz):
    exp_config = {}
    if (lookup_bz == protocol_bz * exps_pto_num):
        __set_dispatcher_num(exp_config, exps_pto_num)
        __set_node_config(exp_config, "dispatcher", 256, 0)
        __set_protocol_node_config(exp_config, protocol_bz, exp_timeout)
        __set_node_config(exp_config, "ip6-lookup", lookup_bz, exp_timeout)
        config_lines.append(json.dumps(exp_config) + '\n')

def __gen_rule2_less_config(config_lines, dispatcher_bz, protocol_bz, lookup_bz):
    exp_config = {}
    if (lookup_bz < protocol_bz * exps_pto_num):
        __set_dispatcher_num(exp_config, exps_pto_num)
        __set_node_config(exp_config, "dispatcher", 256, 0)
        __set_protocol_node_config(exp_config, protocol_bz, exp_timeout)
        __set_node_config(exp_config, "ip6-lookup", lookup_bz, exp_timeout)
        config_lines.append(json.dumps(exp_config) + '\n')

def __gen_rule2_larger_config(config_lines, dispatcher_bz, protocol_bz, lookup_bz):
    exp_config = {}
    if (lookup_bz > protocol_bz * exps_pto_num):
        __set_dispatcher_num(exp_config, exps_pto_num)
        __set_node_config(exp_config, "dispatcher", 256, 0)
        __set_protocol_node_config(exp_config, protocol_bz, exp_timeout)
        __set_node_config(exp_config, "ip6-lookup", lookup_bz, exp_timeout)
        config_lines.append(json.dumps(exp_config) + '\n')
        
def gen_config(func):
    config_lines = []
    for dp_bz in dispatcher_batch_sizes:
        for pto_bz in protocol_batch_sizes:
            for lk_bz in lookup_batch_sizes:
                func(config_lines, dp_bz, pto_bz, lk_bz)
    return config_lines
                

if __name__ == '__main__':
    rule1_eq_config_lines = gen_config(__gen_rule1_equal_config)
    rule1_le_config_lines = gen_config(__gen_rule1_less_config)
    rule1_ge_config_lines = gen_config(__gen_rule1_larger_config)
    rule2_eq_config_lines = gen_config(__gen_rule2_equal_config)
    rule2_le_config_lines = gen_config(__gen_rule2_less_config)
    rule2_ge_config_lines = gen_config(__gen_rule2_larger_config)

    
    with open(CONFIG_FILE%"rule1_eq", 'w') as f:
      f.writelines(rule1_eq_config_lines)
    with open(CONFIG_FILE%"rule1_le", 'w') as f:
      f.writelines(rule1_le_config_lines)
    with open(CONFIG_FILE%"rule1_ge", 'w') as f:
      f.writelines(rule1_ge_config_lines)
    with open(CONFIG_FILE%"rule2_eq", 'w') as f:
      f.writelines(rule2_eq_config_lines)
    with open(CONFIG_FILE%"rule2_le", 'w') as f:
      f.writelines(rule2_le_config_lines)
    with open(CONFIG_FILE%"rule2_ge", 'w') as f:
      f.writelines(rule2_ge_config_lines)