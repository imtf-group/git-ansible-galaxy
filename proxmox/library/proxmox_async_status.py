#!/usr/bin/env python

import time
try:
    import proxmoxer.core
except ImportError:
    pass
import requests.exceptions
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.proxmox import proxmox_argument_spec, connect_to_proxmox

def main():
    module = AnsibleModule(
        argument_spec=dict(
            proxmox_argument_spec(),
            node=dict(),
            task_id=dict(required=True)
        )
    )
    proxmox = connect_to_proxmox(module)
    node = module.params['node']
    if not node:
        node = proxmox.nodes.get()[0]['node']
    try:
        retval = proxmox.nodes(node).tasks(module.params['task_id']).status.get()
    except Exception as e:
        retval = {'status': 'error', 'exceptions': str(e)}
    while 'status' not in retval:
        time.sleep(2)
        try:
            retval = proxmox.nodes(node).tasks(module.params['task_id']).status.get()
        except Exception as e:
            retval = {'status': 'error', 'exceptions': str(e)}
    module.exit_json(changed=False, **retval)

if __name__ == '__main__':
    main()
