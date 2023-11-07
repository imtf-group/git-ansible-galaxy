#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2016, Abdoul Bah (@helldorado) <bahabdoul at gmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
from ansible.module_utils.proxmox import proxmox_argument_spec, get_vm_by_id, connect_to_proxmox
__metaclass__ = type

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}


import os
import re
import time
import traceback
from distutils.version import LooseVersion

try:
    from proxmoxer import ProxmoxAPI
    HAS_PROXMOXER = True
except ImportError:
    HAS_PROXMOXER = False

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native


VZ_TYPE = 'qemu'

def get_vmid(proxmox, name):
    return [vm['vmid'] for vm in proxmox.cluster.resources.get(type='vm') if vm.get('name') == name]


def get_nextvmid(module, proxmox):
    try:
        vmid = proxmox.cluster.nextid.get()
        return vmid
    except Exception as e:
        module.fail_json(msg="Unable to get next vmid. Failed with exception: %s" % to_native(e),
                         exception=traceback.format_exc())


def node_check(proxmox, node):
    return [True for nd in proxmox.nodes.get() if nd['node'] == node]


def get_vminfo(module, proxmox, node, vmid, **kwargs):
    global results
    results = {}
    mac = {}
    devices = {}
    try:
        vm = proxmox.nodes(node).qemu(vmid).config.get()
    except Exception as e:
        module.fail_json(msg='Getting information for VM with vmid = %s failed with exception: %s' % (vmid, e))

    # Sanitize kwargs. Remove not defined args and ensure True and False converted to int.
    kwargs = dict((k, v) for k, v in kwargs.items() if v is not None)

    # Convert all dict in kwargs to elements. For hostpci[n], ide[n], net[n], numa[n], parallel[n], sata[n], scsi[n], serial[n], virtio[n]
    for k in list(kwargs.keys()):
        if isinstance(kwargs[k], dict):
            kwargs.update(kwargs[k])
            del kwargs[k]

    # Split information by type
    for k, v in kwargs.items():
        if re.match(r'net[0-9]', k) is not None:
            interface = k
            k = vm[k]
            k = re.search('=(.*?),', k).group(1)
            mac[interface] = k
        if (re.match(r'virtio[0-9]', k) is not None or
                re.match(r'ide[0-9]', k) is not None or
                re.match(r'scsi[0-9]', k) is not None or
                re.match(r'sata[0-9]', k) is not None):
            device = k
            k = vm[k]
            k = re.search('(.*?),', k).group(1)
            devices[device] = k

    results['mac'] = mac
    results['devices'] = devices
    results['vmid'] = int(vmid)


def settings(module, proxmox, vmid, node, name, timeout, **kwargs):
    proxmox_node = proxmox.nodes(node)

    # Sanitize kwargs. Remove not defined args and ensure True and False converted to int.
    kwargs = dict((k, v) for k, v in kwargs.items() if v is not None)

    if getattr(proxmox_node, VZ_TYPE)(vmid).config.set(**kwargs) is None:
        return True
    else:
        return False


def create_vm(module, proxmox, vmid, newid, node, name, memory, cpu, cores, sockets, timeout, update, **kwargs):
    # Available only in PVE 4
    only_v4 = ['force', 'protection', 'skiplock']

    # valide clone parameters
    valid_clone_params = ['format', 'full', 'pool', 'snapname', 'storage', 'target']
    clone_params = {}
    # Default args for vm. Note: -args option is for experts only. It allows you to pass arbitrary arguments to kvm.
    vm_args = "-serial unix:/var/run/qemu-server/{0}.serial,server,nowait".format(vmid)

    proxmox_node = proxmox.nodes(node)

    # Sanitize kwargs. Remove not defined args and ensure True and False converted to int.
    kwargs = dict((k, v) for k, v in kwargs.items() if v is not None)
    kwargs.update(dict([k, int(v)] for k, v in kwargs.items() if isinstance(v, bool)))

    # The features work only on PVE 4
    if PVE_MAJOR_VERSION < 4:
        for p in only_v4:
            if p in kwargs:
                del kwargs[p]

    # If update, don't update disk (virtio, ide, sata, scsi) and network interface
    if update:
        if 'virtio' in kwargs:
            del kwargs['virtio']
        if 'sata' in kwargs:
            del kwargs['sata']
        if 'scsi' in kwargs:
            del kwargs['scsi']
        if 'ide' in kwargs:
            del kwargs['ide']
        if 'net' in kwargs:
            del kwargs['net']

    # Convert all dict in kwargs to elements. For hostpci[n], ide[n], net[n], numa[n], parallel[n], sata[n], scsi[n], serial[n], virtio[n]
    for k in list(kwargs.keys()):
        if isinstance(kwargs[k], dict):
            kwargs.update(kwargs[k])
            del kwargs[k]

    # Rename numa_enabled  to numa. According the API documentation
    if 'numa_enabled' in kwargs:
        kwargs['numa'] = kwargs['numa_enabled']
        del kwargs['numa_enabled']

    # -args and skiplock require root@pam user
    if module.params['api_user'] == "root@pam" and module.params['args'] is None:
        if not update:
            kwargs['args'] = vm_args
    elif module.params['api_user'] == "root@pam" and module.params['args'] is not None:
        kwargs['args'] = module.params['args']
    elif module.params['api_user'] != "root@pam" and module.params['args'] is not None:
        module.fail_json(msg='args parameter require root@pam user. ')

    if module.params['api_user'] != "root@pam" and module.params['skiplock'] is not None:
        module.fail_json(msg='skiplock parameter require root@pam user. ')

    if update:
        if getattr(proxmox_node, VZ_TYPE)(vmid).config.set(name=name, memory=memory, cpu=cpu, cores=cores, sockets=sockets, **kwargs) is None:
            return True
        else:
            return False
    elif module.params['clone'] is not None:
        for param in valid_clone_params:
            if module.params[param] is not None:
                clone_params[param] = module.params[param]
        clone_params.update(dict([k, int(v)] for k, v in clone_params.items() if isinstance(v, bool)))
        taskid = proxmox_node.qemu(vmid).clone.post(newid=newid, name=name, **clone_params)
    else:
        taskid = getattr(proxmox_node, VZ_TYPE).create(vmid=vmid, name=name, memory=memory, cpu=cpu, cores=cores, sockets=sockets, **kwargs)

    if timeout == 0:
      return taskid
    while timeout:
        if (proxmox_node.tasks(taskid).status.get()['status'] == 'stopped' and
                proxmox_node.tasks(taskid).status.get()['exitstatus'] == 'OK'):
            return True
        timeout = timeout - 1
        if timeout == 0:
            module.fail_json(msg='Reached timeout while waiting for creating VM. Last line in task before timeout: %s' %
                                 proxmox_node.tasks(taskid).log.get()[:1])
        time.sleep(1)
    return False


def start_vm(module, proxmox, vm, vmid, timeout):
    taskid = getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE)(vmid).status.start.post()
    if timeout == 0:
      return taskid
    while timeout:
        if (proxmox.nodes(vm[0]['node']).tasks(taskid).status.get()['status'] == 'stopped' and
                proxmox.nodes(vm[0]['node']).tasks(taskid).status.get()['exitstatus'] == 'OK'):
            return True
        timeout -= 1
        if timeout == 0:
            module.fail_json(msg='Reached timeout while waiting for starting VM. Last line in task before timeout: %s'
                             % proxmox.nodes(vm[0]['node']).tasks(taskid).log.get()[:1])

        time.sleep(1)
    return False


def stop_vm(module, proxmox, vm, vmid, timeout, force):
    if force:
        taskid = getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE)(vmid).status.shutdown.post(forceStop=1)
    else:
        taskid = getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE)(vmid).status.shutdown.post()
    if timeout == 0:
      return taskid
    while timeout:
        if (proxmox.nodes(vm[0]['node']).tasks(taskid).status.get()['status'] == 'stopped' and
                proxmox.nodes(vm[0]['node']).tasks(taskid).status.get()['exitstatus'] == 'OK'):
            return True
        timeout -= 1
        if timeout == 0:
            module.fail_json(msg='Reached timeout while waiting for stopping VM. Last line in task before timeout: %s'
                             % proxmox.nodes(vm[0]['node']).tasks(taskid).log.get()[:1])
        time.sleep(1)
    return False


def proxmox_version(proxmox):
    apireturn = proxmox.version.get()
    return LooseVersion(apireturn['version'])


def main():
    module = AnsibleModule(
        argument_spec=dict(
            proxmox_argument_spec(),
            acpi=dict(type='bool', default='yes'),
            agent=dict(type='bool'),
            args=dict(type='str', default=None),
            autostart=dict(type='bool', default='no'),
            balloon=dict(type='int', default=0),
            bios=dict(choices=['seabios', 'ovmf']),
            boot=dict(type='str', default='cnd'),
            bootdisk=dict(type='str'),
            clone=dict(type='str', default=None),
            cores=dict(type='int', default=1),
            cpu=dict(type='str', default='kvm64'),
            cpulimit=dict(type='int'),
            cpuunits=dict(type='int', default=1000),
            delete=dict(type='str', default=None),
            description=dict(type='str'),
            digest=dict(type='str'),
            force=dict(type='bool', default=None),
            format=dict(type='str', default='qcow2', choices=['cloop', 'cow', 'qcow', 'qcow2', 'qed', 'raw', 'vmdk']),
            freeze=dict(type='bool'),
            full=dict(type='bool', default='yes'),
            hostpci=dict(type='dict'),
            hotplug=dict(type='str'),
            hugepages=dict(choices=['any', '2', '1024']),
            ide=dict(type='dict', default=None),
            keyboard=dict(type='str'),
            kvm=dict(type='bool', default='yes'),
            localtime=dict(type='bool'),
            lock=dict(choices=['migrate', 'backup', 'snapshot', 'rollback']),
            machine=dict(type='str'),
            memory=dict(type='int', default=512),
            migrate_downtime=dict(type='int'),
            migrate_speed=dict(type='int'),
            name=dict(type='str'),
            net=dict(type='dict'),
            newid=dict(type='int', default=None),
            numa=dict(type='dict'),
            numa_enabled=dict(type='bool'),
            node=dict(type='str'),
            onboot=dict(type='bool', default='yes'),
            ostype=dict(default='l26', choices=['other', 'wxp', 'w2k', 'w2k3', 'w2k8', 'wvista', 'win7', 'win8', 'l24', 'l26', 'solaris']),
            parallel=dict(type='dict'),
            pool=dict(type='str'),
            protection=dict(type='bool'),
            reboot=dict(type='bool'),
            revert=dict(type='str', default=None),
            sata=dict(type='dict'),
            scsi=dict(type='dict'),
            scsihw=dict(choices=['lsi', 'lsi53c810', 'virtio-scsi-pci', 'virtio-scsi-single', 'megasas', 'pvscsi']),
            serial=dict(type='dict'),
            shares=dict(type='int'),
            skiplock=dict(type='bool'),
            smbios=dict(type='str'),
            snapname=dict(type='str'),
            sockets=dict(type='int', default=1),
            startdate=dict(type='str'),
            startup=dict(),
            state=dict(default='present', choices=['present', 'absent', 'stopped', 'started', 'restarted', 'current']),
            storage=dict(type='str'),
            tablet=dict(type='bool', default='no'),
            target=dict(type='str'),
            tdf=dict(type='bool'),
            template=dict(type='bool', default='no'),
            timeout=dict(type='int', default=30),
            update=dict(type='bool', default='no'),
            vcpus=dict(type='int', default=None),
            vga=dict(default='std', choices=['std', 'cirrus', 'vmware', 'qxl', 'serial0', 'serial1', 'serial2', 'serial3', 'qxl2', 'qxl3', 'qxl4']),
            virtio=dict(type='dict', default=None),
            vmid=dict(type='int', default=None),
            watchdog=dict(),
        ),
        mutually_exclusive=[('delete', 'revert'), ('delete', 'update'), ('revert', 'update'), ('clone', 'update'), ('clone', 'delete'), ('clone', 'revert')],
        required_one_of=[('name', 'vmid',)]
    )

    if not HAS_PROXMOXER:
        module.fail_json(msg='proxmoxer required for this module')

    api_user = module.params['api_user']
    api_host = module.params['api_host']
    api_password = module.params['api_password']
    clone = module.params['clone']
    cpu = module.params['cpu']
    cores = module.params['cores']
    delete = module.params['delete']
    memory = module.params['memory']
    name = module.params['name']
    newid = module.params['newid']
    node = module.params['node']
    revert = module.params['revert']
    sockets = module.params['sockets']
    state = module.params['state']
    timeout = module.params['timeout']
    update = bool(module.params['update'])
    vmid = module.params['vmid']
    validate_certs = module.params['validate_certs']

    proxmox = connect_to_proxmox(module)
    global VZ_TYPE
    global PVE_MAJOR_VERSION
    PVE_MAJOR_VERSION = 3 if proxmox_version(proxmox) < LooseVersion('4.0') else 4

    if not node:
        node = proxmox.nodes.get()[0]['node']

    # If vmid not set get the Next VM id from ProxmoxAPI
    # If vm name is set get the VM id from ProxmoxAPI
    if not vmid:
        if state == 'present' and (not update and not clone) and (not delete and not revert):
            try:
                vmid = get_nextvmid(module, proxmox)
            except Exception as e:
                module.fail_json(msg="Can't get the next vmid for VM {0} automatically. Ensure your cluster state is good".format(name))
        else:
            try:
                if not clone:
                    vmid = get_vmid(proxmox, name)[0]
                else:
                    vmid = get_vmid(proxmox, clone)[0]
            except Exception as e:
                if not clone:
                    module.fail_json(msg="VM {0} does not exist in cluster.".format(name))
                else:
                    module.fail_json(msg="VM {0} does not exist in cluster.".format(clone))

    if clone is not None:
        if get_vmid(proxmox, name):
            module.exit_json(changed=False, msg="VM with name <%s> already exists" % name)
        if vmid is not None:
            vm = get_vm_by_id(proxmox, vmid)
            if not vm:
                module.fail_json(msg='VM with vmid = %s does not exist in cluster' % vmid)
        if not newid:
            try:
                newid = get_nextvmid(module, proxmox)
            except Exception as e:
                module.fail_json(msg="Can't get the next vmid for VM {0} automatically. Ensure your cluster state is good".format(name))
        else:
            vm = get_vm_by_id(proxmox, newid)
            if vm:
                module.exit_json(changed=False, msg="vmid %s with VM name %s already exists" % (newid, name))

    if delete is not None:
        try:
            settings(module, proxmox, vmid, node, name, timeout, delete=delete)
            module.exit_json(changed=True, msg="Settings has deleted on VM {0} with vmid {1}".format(name, vmid))
        except Exception as e:
            module.fail_json(msg='Unable to delete settings on VM {0} with vmid {1}: '.format(name, vmid) + str(e))
    elif revert is not None:
        try:
            settings(module, proxmox, vmid, node, name, timeout, revert=revert)
            module.exit_json(changed=True, msg="Settings has reverted on VM {0} with vmid {1}".format(name, vmid))
        except Exception as e:
            module.fail_json(msg='Unable to revert settings on VM {0} with vmid {1}: Maybe is not a pending task...   '.format(name, vmid) + str(e))

    if state == 'present':
        try:
            if get_vm_by_id(proxmox, vmid) and not (update or clone):
                module.exit_json(changed=False, msg="VM with vmid <%s> already exists" % vmid)
            elif get_vmid(proxmox, name) and not (update or clone):
                module.exit_json(changed=False, msg="VM with name <%s> already exists" % name)
            elif not (node, name):
                module.fail_json(msg='node, name is mandatory for creating/updating vm')
            elif not node_check(proxmox, node):
                module.fail_json(msg="node '%s' does not exist in cluster" % node)

            retval = create_vm(module, proxmox, vmid, newid, node, name, memory, cpu, cores, sockets, timeout, update,
                      acpi=module.params['acpi'],
                      agent=module.params['agent'],
                      autostart=module.params['autostart'],
                      balloon=module.params['balloon'],
                      bios=module.params['bios'],
                      boot=module.params['boot'],
                      bootdisk=module.params['bootdisk'],
                      cpulimit=module.params['cpulimit'],
                      cpuunits=module.params['cpuunits'],
                      description=module.params['description'],
                      digest=module.params['digest'],
                      force=module.params['force'],
                      freeze=module.params['freeze'],
                      hostpci=module.params['hostpci'],
                      hotplug=module.params['hotplug'],
                      hugepages=module.params['hugepages'],
                      ide=module.params['ide'],
                      keyboard=module.params['keyboard'],
                      kvm=module.params['kvm'],
                      localtime=module.params['localtime'],
                      lock=module.params['lock'],
                      machine=module.params['machine'],
                      migrate_downtime=module.params['migrate_downtime'],
                      migrate_speed=module.params['migrate_speed'],
                      net=module.params['net'],
                      numa=module.params['numa'],
                      numa_enabled=module.params['numa_enabled'],
                      onboot=module.params['onboot'],
                      ostype=module.params['ostype'],
                      parallel=module.params['parallel'],
                      pool=module.params['pool'],
                      protection=module.params['protection'],
                      reboot=module.params['reboot'],
                      sata=module.params['sata'],
                      scsi=module.params['scsi'],
                      scsihw=module.params['scsihw'],
                      serial=module.params['serial'],
                      shares=module.params['shares'],
                      skiplock=module.params['skiplock'],
                      smbios1=module.params['smbios'],
                      snapname=module.params['snapname'],
                      startdate=module.params['startdate'],
                      startup=module.params['startup'],
                      tablet=module.params['tablet'],
                      target=module.params['target'],
                      tdf=module.params['tdf'],
                      template=module.params['template'],
                      vcpus=module.params['vcpus'],
                      vga=module.params['vga'],
                      virtio=module.params['virtio'],
                      watchdog=module.params['watchdog'])

            if not isinstance(retval, bool):
                module.exit_json(changed=True, msg="VM creation asynchrously running", task_id=retval, vmid=newid, node=node)

            if not clone:
                get_vminfo(module, proxmox, node, vmid,
                           ide=module.params['ide'],
                           net=module.params['net'],
                           sata=module.params['sata'],
                           scsi=module.params['scsi'],
                           virtio=module.params['virtio'])
            if update:
                module.exit_json(changed=True, msg="VM %s with vmid %s updated" % (name, vmid))
            elif clone is not None:
                module.exit_json(changed=True, msg="VM %s with newid %s cloned from vm with vmid %s" % (name, newid, vmid))
            else:
                module.exit_json(changed=True, msg="VM %s with vmid %s deployed" % (name, vmid), **results)
        except Exception as e:
            if update:
                module.fail_json(msg="Unable to update vm {0} with vmid {1}=".format(name, vmid) + str(e))
            elif clone is not None:
                module.fail_json(msg="Unable to clone vm {0} from vmid {1}=".format(name, vmid) + str(e))
            else:
                module.fail_json(msg="creation of %s VM %s with vmid %s failed with exception=%s" % (VZ_TYPE, name, vmid, e))

    elif state == 'started':
        try:
            vm = get_vm_by_id(proxmox, vmid)
            if not vm:
                module.fail_json(msg='VM with vmid <%s> does not exist in cluster' % vmid)
            if getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE)(vmid).status.current.get()['status'] == 'running':
                module.exit_json(changed=False, msg="VM %s is already running" % vmid)

            retval = start_vm(module, proxmox, vm, vmid, timeout)
            if retval is True:
                module.exit_json(changed=True, msg="VM %s started" % vmid)
            else:
                module.exit_json(changed=True, msg="VM asynchrously starting", task_id=retval, vmid=vmid, node=vm[0]['node'])
        except Exception as e:
            module.fail_json(msg="starting of VM %s failed with exception: %s" % (vmid, e))

    elif state == 'stopped':
        try:
            vm = get_vm_by_id(proxmox, vmid)
            if not vm:
                module.fail_json(msg='VM with vmid = %s does not exist in cluster' % vmid)

            if getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE)(vmid).status.current.get()['status'] == 'stopped':
                module.exit_json(changed=False, msg="VM %s is already stopped" % vmid)

            retval = stop_vm(module, proxmox, vm, vmid, timeout, force=module.params['force'])
            if retval is True:
                module.exit_json(changed=True, msg="VM %s is shutting down" % vmid)
            else:
                module.exit_json(changed=True, msg="VM asynchrously stopping", task_id=retval, vmid=vmid, node=vm[0]['node'])
        except Exception as e:
            module.fail_json(msg="stopping of VM %s failed with exception: %s" % (vmid, e))

    elif state == 'restarted':
        try:
            vm = get_vm_by_id(proxmox, vmid)
            if not vm:
                module.fail_json(msg='VM with vmid = %s does not exist in cluster' % vmid)
            if getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE)(vmid).status.current.get()['status'] == 'stopped':
                module.exit_json(changed=False, msg="VM %s is not running" % vmid)

            if stop_vm(module, proxmox, vm, vmid, timeout, force=module.params['force']) and start_vm(module, proxmox, vm, vmid, timeout):
                module.exit_json(changed=True, msg="VM %s is restarted" % vmid)
        except Exception as e:
            module.fail_json(msg="restarting of VM %s failed with exception: %s" % (vmid, e))

    elif state == 'absent':
        try:
            vm = get_vm_by_id(proxmox, vmid)
            if not vm:
                module.exit_json(changed=False, msg="VM %s does not exist" % vmid)

            if getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE)(vmid).status.current.get()['status'] == 'running':
                module.exit_json(changed=False, msg="VM %s is running. Stop it before deletion." % vmid)

            taskid = getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE).delete(vmid)
            if timeout == 0:
                module.exit_json(changed=True, msg="VM asynchrously deleting", task_id=taskid, vmid=vmid, node=vm[0]['node'])
            while timeout:
                if (proxmox.nodes(vm[0]['node']).tasks(taskid).status.get()['status'] == 'stopped' and
                        proxmox.nodes(vm[0]['node']).tasks(taskid).status.get()['exitstatus'] == 'OK'):
                    module.exit_json(changed=True, msg="VM %s removed" % vmid)
                timeout -= 1
                if timeout == 0:
                    module.fail_json(msg='Reached timeout while waiting for removing VM. Last line in task before timeout: %s'
                                     % proxmox.nodes(vm[0]['node']).tasks(taskid).log.get()[:1])

                time.sleep(1)
        except Exception as e:
            module.fail_json(msg="deletion of VM %s failed with exception: %s" % (vmid, e))

    elif state == 'current':
        status = {}
        try:
            vm = get_vm_by_id(proxmox, vmid)
            if not vm:
                module.fail_json(msg='VM with vmid = %s does not exist in cluster' % vmid)
            current = getattr(proxmox.nodes(vm[0]['node']), VZ_TYPE)(vmid).status.current.get()['status']
            status['status'] = current
            if status:
                module.exit_json(changed=False, msg="VM %s with vmid = %s is %s" % (name, vmid, current), **status)
        except Exception as e:
            module.fail_json(msg="Unable to get vm {0} with vmid = {1} status: ".format(name, vmid) + str(e))


if __name__ == '__main__':
    main()
