import json 

CONFIG_FILE="/mnt/disk1/yanghanlin/vpp-hw-rl/motivation1_exp_settings.json"

exps_pto_num = 16
exps_batch_sizes = list(range(32, 256+16, 16))
exp_timeouts = 400

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
    __gen_config(config_lines, exps_pto_num, 256, 0)
    
def gen_exp_config(config_lines):
    for batch_size in exps_batch_sizes:   
        __gen_config(config_lines, exps_pto_num, batch_size, exp_timeouts)

if __name__ == '__main__':
    config_lines = []
    gen_baseline_config(config_lines)
    gen_exp_config(config_lines)
    print(config_lines)
    
    with open(CONFIG_FILE, 'w') as f:
        f.writelines(config_lines)