#!/bin/bash

set -o pipefail

APT=$(which apt-get 2>/dev/null)

if [ -n "$APT" ]; then
    systemctl stop apt-daily.service
    systemctl kill --kill-who=all apt-daily.service
    systemctl disable apt-daily.service
    systemctl disable apt-daily.timer
    systemctl disable apt-daily-upgrade.service
    systemctl disable apt-daily-upgrade.timer

    # wait until `apt-get updated` has been killed
    while ! (systemctl list-units --all apt-daily.service | egrep -q '(dead|failed)')
    do
      sleep 1
    done
    while [ $(ps -ef | grep apt | grep -cv grep) -gt 0 ]
    do
      sleep 1
    done
fi

rm -f /etc/sudoers.d/90-cloud-init-users
