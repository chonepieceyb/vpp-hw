import json 

CONFIG_FILE="/mnt/disk1/yanghanlin/vpp-hw-rl/motivation_exp_settings.json"

exps_pto_nums = list(range(2,17,2))
exps_batch_sizes = [64]
exp_timeouts = [6, 8, 10, 15, 20, 50, 100]

def __gen_config(config_lines, pto_num, batch_size, timeout):
    exp_config = {}
    exp_config["dispatcher"] = {}
    exp_config["dispatcher"]["num"] = pto_num
    exp_config["nodes"] = {}
    for i in range(16):
        id = i + 1
        exp_config["nodes"]["protocol%d"%id] = {}
        exp_config["nodes"]["protocol%d"%id]["size"] = batch_size 
        exp_config["nodes"]["protocol%d"%id]["timeout"] = timeout
    config_lines.append(json.dumps(exp_config) + '\n')
    
def gen_baseline_config(config_lines):
    __gen_config(config_lines, 1, 256, 0)
    for pto_num in exps_pto_nums:
        __gen_config(config_lines, pto_num, 256, 0)
    
def gen_exp_config(config_lines):
    for pto_num in exps_pto_nums:
        for batch_size in exps_batch_sizes:
            for timeout in exp_timeouts:
                __gen_config(config_lines, pto_num, batch_size, timeout)

if __name__ == '__main__':
    config_lines = []
    gen_baseline_config(config_lines)
    gen_exp_config(config_lines)
    print(config_lines)
    
    with open(CONFIG_FILE, 'w') as f:
        f.writelines(config_lines)