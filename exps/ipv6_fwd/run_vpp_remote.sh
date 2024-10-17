#!/usr/bin/env bash 

# 使用示例：sudo ./run_vpp_remote.sh -c 10,11-12

set -e

# vpp和vppctl的路径(vpp_binary变量)默认在../../tools/check-path.sh中指定
DIR=$(dirname "$0")
DATAPLANE_TOP=${DIR}/../..
source "${DATAPLANE_TOP}"/tools/check-path.sh

# 这里也可以直接修改
export vppctl_binary="/usr/local/bin/vppctl"
export vpp_binary="/usr/local/bin/vpp"

# dpdk绑定的网卡名
Ethernet0="Ethernet0"
Ethernet1="Ethernet1"

# VPP runtime socket目录位置
VPP_RUNTIME_DIR="/run/vpp/remote"
SOCKFILE="${VPP_RUNTIME_DIR}/cli_remote.sock"
VPP_REMOTE_PIDFILE="${VPP_RUNTIME_DIR}/vpp_remote.pid"

# 网卡PCIE设置,数组分别是Ethernet0和Ethernet1的PCIE地址
pcie_addr=("0000:84:00.0" "0000:84:00.1")

# 注意，这里rx queue数量默认等于workker线程数量（通过cal_cores函数计算出queues_count变量，在启动VPP时的配置中指定）

help_func()
{
    echo "Usage: ./run_vpp_remote.sh options"
    echo
    echo "Options:"
    echo "  -c <core list>       set CPU affinity. Assign VPP main thread to 1st core"
    echo "                       in list and place worker threads on other listed cores."
    echo "                       Cores are separated by commas, and worker cores can include ranges."
    echo
    echo "Example:"
    echo "  ./run_vpp_remote.sh -c 1,2-3"
    echo
}

err_cleanup()
{
    echo "Remote VPP setup error, cleaning up..."
    if [[ -f "${VPP_REMOTE_PIDFILE}" ]]; then
        vpp_remote_pid=$(cat "${VPP_REMOTE_PIDFILE}")
        sudo kill -9 "${vpp_remote_pid}"
        sudo rm "${VPP_REMOTE_PIDFILE}"
    fi
    exit 1
}
cal_cores()
{
  IFS=',' read -ra array <<< "$1"
  count=0

  for item in "${array[@]}"; do
      if [[ $item == *-* ]]; then
          start=${item%-*}
          end=${item#*-}
          count=$((count + end - start + 1))
      else
          count=$((count + 1))
      fi
  done

  echo $count
}
setup_iface()
{
    # 网卡设置
    sudo "${vppctl_binary}" -s "${SOCKFILE}" set interface state "${Ethernet0}" up
    sudo "${vppctl_binary}" -s "${SOCKFILE}" set interface ip address "${Ethernet0}" 192.168.1.1/24
    sudo "${vppctl_binary}" -s "${SOCKFILE}" enable ip6 interface "${Ethernet0}"
    sudo "${vppctl_binary}" -s "${SOCKFILE}" set interface ip address "${Ethernet0}" ::1:1/112
    
    sudo "${vppctl_binary}" -s "${SOCKFILE}" set interface state "${Ethernet1}" up
    sudo "${vppctl_binary}" -s "${SOCKFILE}" set interface ip address "${Ethernet1}" 192.168.2.1/24
    sudo "${vppctl_binary}" -s "${SOCKFILE}" enable ip6 interface "${Ethernet1}"
    sudo "${vppctl_binary}" -s "${SOCKFILE}" set interface ip address "${Ethernet1}" ::2:1/112

    # 检查网卡是否启动成功
    LOG=$(sudo "${vppctl_binary}" -s "${SOCKFILE}" show interface)
    if [[ "${LOG}" == *"${Ethernet0}"* && "${LOG}" == *"${Ethernet1}"* ]]; then
        echo "Successfully set up interfaces!"
    else
        echo "Failed to set up interfaces!"
        err_cleanup
    fi

    # 借助 192.168.1.100 这个虚拟下一跳IP(Trex收包port的IP)，配置路由表
    sudo "${vppctl_binary}" -s "${SOCKFILE}" set ip neighbor "${Ethernet1}" 192.168.2.2 04:3f:72:f4:40:4a
    sudo "${vppctl_binary}" -s "${SOCKFILE}" set ip neighbor "${Ethernet1}" ::2:2 04:3f:72:f4:40:4a
    # 将IPv4 L3 fwd流量转回node3 Trex
    sudo "${vppctl_binary}" -s "${SOCKFILE}" ip route add 192.168.3.1/32 via 192.168.2.2 "${Ethernet1}"
    # 将IPv6 L3 fwd流量转回node3 Trex
    sudo "${vppctl_binary}" -s "${SOCKFILE}" ip route add ::3:1/128 via ::2:2 "${Ethernet1}"
    echo "IPv4&6 L3 fwd configuration successful!"
}

options=(-o "h:c:")
opts=$(getopt "${options[@]}" -- "$@")
eval set -- "$opts"

while true; do
    case "$1" in
      -h)
          help_func
          exit 0
          ;;
      -c)
          if ! [[ "$2" =~ ^[0-9]{1,3}((,[0-9]{1,3})|(,[0-9]{1,3}-[0-9]{1,3}))+$ ]]; then
              echo "error: \"-c\" requires correct cpu isolation core id"
              help_func
              exit 1
          fi
          main_core=$(echo "$2" | cut -d "," -f 1)
          worker_core=$(echo "$2" | cut -d "," -f 2-)
          if [[ "${main_core}" == "${worker_core}" ]]; then
              echo "error: \"-c\" option bad usage"
              help_func
              exit 1
          fi
          queues_count=$(cal_cores "$worker_core")
        #   queues_count=1
          echo "queues_count: ""${queues_count}"
          shift 2
          ;;
      --)
          shift
          break
          ;;
      *)
          echo "Invalid Option!!"
          help_func
          exit 1
          ;;
    esac
done

if ! [[ "${main_core}" && "${worker_core}" ]]; then
    echo "require an option: \"-c\""
    help_func
    exit 1
fi

check_vpp
check_vppctl

# 启动VPP
sudo "${vpp_binary}" unix "{ runtime-dir ${VPP_RUNTIME_DIR} cli-listen ${SOCKFILE} pidfile ${VPP_REMOTE_PIDFILE} }"                                                              \
                        cpu "{ main-core ${main_core} corelist-workers ${worker_core} }"                                                                                            \
                        plugins "{ plugin default { enable } plugin dpdk_plugin.so { enable } plugin crypto_native_plugin.so {enable} plugin crypto_openssl_plugin.so {enable} plugin ping_plugin.so { enable } plugin nat_plugin.so {enable}}"  \
                        dpdk "{ dev ${pcie_addr[0]} { name "${Ethernet0}" num-tx-queues ${queues_count} num-rx-queues ${queues_count}} 
                                dev ${pcie_addr[1]} { name "${Ethernet1}" num-tx-queues ${queues_count} num-rx-queues ${queues_count}}}"

echo "Remote VPP starting up"


sleep 0.5

# 尝试连接vppctl socket
set +e
max_conn_retries=10
for conn_count in $(seq ${max_conn_retries}); do
    if ! output=$(sudo "${vppctl_binary}" -s "${SOCKFILE}" show threads); then
        if [[ ${conn_count} -eq ${max_conn_retries} ]]; then
            err_cleanup
        fi
        sleep 1
    elif [[ -z "${output}" ]]; then
        err_cleanup
    else
        break
    fi
done
set -e

echo "Setting up DPDK interfaces..."

# 网卡设置 + IPsec配置
setup_iface

echo "Successfully start remote VPP instance!"
