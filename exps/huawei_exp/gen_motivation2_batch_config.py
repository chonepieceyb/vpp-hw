import json 

CONFIG_FILE="/mnt/disk1/yanghanlin/vpp-hw-rl/motivation_configs/motivation1_batch_exp_settings.json"

exps_pto_nums = 16

configs = [(i * 16, i * 160) for i in range(1, 17)]

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
    
def gen_exp_config(config_lines):
    for c in configs:
        __gen_config(config_lines, 16, c[0], c[1])
    

if __name__ == '__main__':
    config_lines = []
    gen_exp_config(config_lines)
    print(config_lines)
    
    with open(CONFIG_FILE, 'w') as f:
        f.writelines(config_lines)