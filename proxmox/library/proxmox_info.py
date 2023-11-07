#!/usr/bin/env python

import re
try:
    import proxmoxer.core
except ImportError:
    pass
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.proxmox import proxmox_argument_spec, connect_to_proxmox
from ansible.module_utils.proxmox import proxmox_tags_to_dict, serialize_disk

def facts(vm):
    return dict(
        memory_total=vm['maxmem'] // (1024 * 1024 * 1024),
        disk_total=vm['maxdisk'] // (1024 * 1024 * 1024),
        vmid=vm['vmid'],
        cpus=vm['cpus'],
        status=vm['status'],
        name=vm['name'],
        tags=proxmox_tags_to_dict(vm['tags']) if 'tags' in vm else {})

def main():
    module = AnsibleModule(
        argument_spec=dict(
            proxmox_argument_spec(),
            filters=dict(type='dict', default={}),
        ),
        supports_check_mode=True
    )

    proxmox = connect_to_proxmox(module)
    servers = []
    nodes = ['{node}/{type}'.format(**vm) for vm in proxmox.cluster.resources.get(type='vm')]
    for node in set(nodes):
        for vm in proxmox.nodes(node).get():
            server = facts(vm)
            server['node'] = node
            append = True
            for key, value in module.params['filters'].items():
                if key == 'name' and ((isinstance(value, list) and \
                        server['name'] not in value) or \
                        (not isinstance(value, list) and \
                            server['name'] != value)):
                    append = False
                elif key in ('id', 'vmid') and ((isinstance(value, list) and \
                        server['vmid'] not in value) or \
                        (not isinstance(value, list) and \
                            server['vmid'] != value)):
                    append = False
                elif key == 'status' and ((isinstance(value, list) and \
                        server['status'] not in value) or \
                        (not isinstance(value, list) and \
                            server['status'] != value)):
                    append = False
                elif key.startswith('tag:'):
                    tag_key = key.split(':', 1)[1]
                    if tag_key not in server['tags']:
                        append = False
                    elif (isinstance(value, list) and \
                            server['tags'][tag_key] not in value) or \
                            (not isinstance(value, list) and \
                                server['tags'][tag_key] != value):
                        append = False
            if append is True:
                disks = {}
                vm = proxmox.nodes('{node}/{vmid}'.format(**server))
                conf = vm.config.get()
                for key in conf:
                    if re.match('scsi[0-9]+', key) or re.match('sata[0-9]+', key) or \
                            re.match('ide[0-9]+', key) or re.match('virtio[0-9]+', key):
                        disks[key] = serialize_disk(conf[key])
                server['disks'] = disks
                try:
                    network_info = vm.agent('network-get-interfaces').get()
                except proxmoxer.core.ResourceException:
                    network_info = None
                if network_info is not None:
                    server['ip_adresses'] = []
                    for ifce in network_info['result']:
                        if ifce['name'] == 'lo':
                            continue
                        for ips in ifce['ip-addresses']:
                            if ips['ip-address-type'] == 'ipv4':
                                server['ip_adresses'].append(ips['ip-address'])
                servers.append(server)

    module.exit_json(servers=servers)


if __name__ == '__main__':
    main()
