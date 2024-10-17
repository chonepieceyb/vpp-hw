#!/usr/bin/env bash

# Copyright (c) 2023-2024, Arm Limited.
#
# SPDX-License-Identifier: Apache-2.0

set -e

export vppctl_binary="/usr/local/bin/vppctl"
DIR=$(dirname "$0")
DATAPLANE_TOP=${DIR}/../..
# shellcheck source=../../tools/check-path.sh
. "${DATAPLANE_TOP}"/tools/check-path.sh

help_func()
{
    echo "Usage: ./traffic_monitor.sh options"
    echo
    echo "Options:"
    echo "  -i <VPP instance>   specify VPP instance: local/remote"
    echo "  -m                  test via memif interface"
    echo "  -p                  test via physical interface"
    echo "  -h                  show this message and quit"
    echo
    echo "Example:"
    echo "  ./traffic_monitor.sh -m -i local"
    echo "  ./traffic_monitor.sh -p -i local"
    echo
}

options=(-o "hmpi:")
opts=$(getopt "${options[@]}" -- "$@")
eval set -- "$opts"

test_duration=3

while true; do
    case "$1" in
      -i)
          if [[ "$2" == "local" ]]; then
            sockfile=/run/vpp/local/cli_local.sock
          elif [[ "$2" == "remote" ]]; then
            sockfile=/run/vpp/remote/cli_remote.sock
          else
            echo "Correctly specify the VPP instance: local/remote"
            exit 1
          fi
          shift 2
          ;;
      -h)
          help_func
          exit 0
          ;;
      -m)
          memif_iface="1"
          shift 1
          ;;
      -p)
          phy_iface="1"
          shift 1
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

if [[ "${memif_iface}" && "${phy_iface}" ]]; then
    echo "Don't support both -m and -p at the same time!!"
    help_func
    exit 1
fi

check_vppctl

echo "=========="

sudo "${vppctl_binary}" -s "${sockfile}" clear runtime

echo "Letting IPSec work for ${test_duration} seconds:"
for _ in $(seq ${test_duration}); do
    echo -n "..$_"
    sleep 1
done

sudo "${vppctl_binary}" -s "${sockfile}" show runtime

echo
echo "END"
