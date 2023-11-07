#!/usr/bin/env python

import time
try:
    import proxmoxer.core
except ImportError:
    pass
import requests.exceptions
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.proxmox import proxmox_argument_spec, connect_to_proxmox
from ansible.module_utils.proxmox import get_vm_by_name, get_vm_by_id

def main():
    module = AnsibleModule(
        argument_spec=dict(
            proxmox_argument_spec(),
            hostname=dict(aliases=['name']),
            vmid=dict(type='int'),
            timeout=dict(type='int', default=60),
        ),
        mutually_exclusive=[['vmid', 'hostname']]
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
    vm = proxmox.nodes('{node}/{type}/{vmid}'.format(**vm[0]))

    elapsed = 0
    error_msg = None

    while elapsed < module.params['timeout']:
        try:
            vm.agent('network-get-interfaces').get()
            module.exit_json(changed=False, msg="up in {0} seconds".format(elapsed))
        except proxmoxer.core.ResourceException as e:
            error_msg = str(e)
        except requests.exceptions.ReadTimeout:
            pass
        elapsed += 1
        time.sleep(1)

    module.exit_json(changed=False, msg=error_msg)

if __name__ == '__main__':
    main()
