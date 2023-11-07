#!/usr/bin/env python

import re
import time
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.proxmox import proxmox_argument_spec, connect_to_proxmox, wait_for
from ansible.module_utils.proxmox import serialize_disk, get_vm_by_name, get_vm_by_id


def main():
    module = AnsibleModule(
        argument_spec=dict(
            proxmox_argument_spec(),
            hostname=dict(aliases=['name']),
            vmid=dict(type='int'),
            size=dict(type='int'),
            storage=dict(default='local-lvm'),
            device=dict(),
            format=dict(default='raw', choices=['qcow2', 'raw', 'subvol']),
            state=dict(default='present', choices=['present', 'absent', 'list'])
        ),
        supports_check_mode=True,
        required_one_of=[['vmid', 'hostname']],
        mutually_exclusive=[['vmid', 'hostname']],
        required_if=[
            ['state', 'present', ['size']],
            ['state', 'absent', ['device']],
        ]
    )

    proxmox = connect_to_proxmox(module)
    if module.params['hostname']:
        try:
            vm = get_vm_by_name(proxmox, module.params['hostname'])
        except IndexError:
            module.fail_json(
                msg="No VM found with hostname '{hostname}'".format(
                    **module.params))
    else:
        try:
            vm = get_vm_by_id(proxmox, module.params['vmid'])
        except IndexError:
            module.fail_json(
                msg="No VM found with ID '{vmid}'".format(
                    **module.params))
    node = proxmox.nodes(vm[0]['node'])
    vm = proxmox.nodes('{node}/{type}/{vmid}'.format(**vm[0]))


    conf = vm.config.get()

    if module.params['state'] == 'present':
        if module.params.get('device') and module.params['device'] in conf:
                disk = serialize_disk(conf[module.params['device']])
                if 'size' not in disk:
                    module.fail_json(msg='Invalid device', **disk)
                size = int(disk['size'].replace('G', ''))
                if size > module.params['size']:
                    module.fail_json(msg='cannot shrink drives')
                elif size < module.params['size']:
                    taskid = vm.resize.put(
                        disk=module.params['device'],
                        size='{size}G'.format(**module.params))
                    changed = True
                else:
                    changed = False
                module.exit_json(changed=changed,
                                 **{module.params['device']: dict(
                                 storage=disk['storage'],
                                 name=disk['name'],
                                 size=module.params['size'])})
        else:
            if not module.params.get('device'):
                device_type = 'scsi'
                for key in conf:
                    for dev_type in ('scsi', 'sata', 'ide'):
                        if key.startswith(dev_type):
                            device_type = dev_type
                            break
                dev_number = 1
                while device_type + str(dev_number) in conf:
                    dev_number += 1
                device = device_type + str(dev_number)
            else:
                device = module.params['device']
            taskid = vm.config.post(
                **{device: '{storage}:{size},format={format}'.format(
                    **module.params)})
            if not wait_for(node, taskid):
                module.fail_json(msg='Volume creation timeout')
            conf = vm.config.get()
            module.exit_json(changed=True,
                             **{device: serialize_disk(conf[device])})

    elif module.params['state'] == 'absent':
        if module.params['device'] not in conf:
            module.exit_json(changed=False)
        else:
            disk = serialize_disk(conf[module.params['device']])
            vm.config.set(delete=module.params['device'])
            conf = vm.config.get()
            for key, val in conf.items():
                if val == '{0}:{1}'.format(storage, name):
                    vm.config.set(delete=key)
                    break
            module.exit_json(changed=True,
                             **{key: disk})

    else:
        disks = {}
        for key in conf:
            if re.match('scsi[0-9]+', key) or re.match('sata[0-9]+', key) or \
                    re.match('ide[0-9]+', key) or re.match('virtio[0-9]+', key):
                disks[key] = serialize_disk(conf[key])
        module.exit_json(**disks)


if __name__ == '__main__':
    main()
