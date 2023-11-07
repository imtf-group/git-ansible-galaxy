#!/usr/bin/env python

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.proxmox import proxmox_argument_spec, connect_to_proxmox, get_vm_by_name
from ansible.module_utils.proxmox import proxmox_tags_to_dict, dict_to_proxmox_tags, get_vm_by_id


def main():
    module = AnsibleModule(
        argument_spec=dict(
            proxmox_argument_spec(),
            hostname=dict(aliases=['name']),
            vmid=dict(type='int'),
            tags=dict(type='dict'),
            state=dict(default='present', choices=['present', 'absent', 'list']),
            append=dict(type='bool', default=False)
        ),
        supports_check_mode=True,
        required_one_of=[['vmid', 'hostname']],
        mutually_exclusive=[['vmid', 'hostname']],
        required_if=[
            ['state', 'present', ['tags']],
            ['state', 'absent', ['tags']]
        ]
    )

    tags = module.params['tags']
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

    conf = vm.config.get()
    tags_dict = proxmox_tags_to_dict(conf.get('tags', ''))
    initial_tags = dict(tags_dict)

    if module.params['state'] == 'present':
        if module.params['append'] is False:
            tags_dict = {}
        tags_dict.update(tags)
        try:
            vm.config.post(tags=dict_to_proxmox_tags(tags_dict))
        except Exception as e:
            module.fail_json(msg=str(e))
        module.exit_json(changed=(initial_tags != tags_dict), tags=tags_dict)

    elif module.params['state'] == 'absent':
        for tag in tags:
            if tag in tags_dict:
                del tags_dict[tag]
        try:
            vm.config.post(tags=dict_to_proxmox_tags(tags_dict))
        except Exception as e:
            module.fail_json(msg=str(e))
        module.exit_json(changed=(initial_tags != tags_dict), tags=tags_dict)

    else:
        module.exit_json(tags=tags_dict)

if __name__ == '__main__':
    main()
