import csv


"""
select
    "setting.nodes.ip6-input.size"        AS ip6_input.size,
    "setting.nodes.ip6-input.timeout"     AS ip6_input.timeout,
    "setting.nodes.ip4-input.size"        AS ip4_input.size,
    "setting.nodes.ip4-input.timeout"     AS ip4_input.timeout
....

按这样格式查询sql导出的csv文件可以用该脚本转换成vpp中设置node batch的命令
    
"""
def process_csv(file_path, length=10):
    command = "set node batch"
    node_setting : dict[str, dict[str, str]] = {}
    with open(file_path, mode='r') as file:
        csv_reader = csv.DictReader(file)
        for row in csv_reader:
            if csv_reader.line_num > length:
                break
            for column, value in row.items():
                if column.endswith('.timeout'):
                    node_name = column.replace('.timeout', '')
                    if node_name not in node_setting:
                        node_setting[node_name] = {}
                    node_setting[node_name]['timeout'] = value
                elif column.endswith('.size'):
                    node_name = column.replace('.size', '')
                    if node_name not in node_setting:
                        node_setting[node_name] = {}
                    node_setting[node_name]['size'] = value
            for node_name, setting in node_setting.items():
                node_name = node_name.replace('_', '-')
                command += f" {node_name} size {setting['size']} timeout {setting['timeout']}"
            command += "\n"
            node_setting = {}
            print(f"{command}")



if __name__ == '__main__':
    process_csv('command.csv', 2)
