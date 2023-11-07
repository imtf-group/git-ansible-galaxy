#!/usr/bin/env python

import os
import re
import requests
import time
try:
    from proxmoxer import ProxmoxAPI
    import proxmoxer.backends
    HAS_PROXMOXER = True
except ImportError:
    HAS_PROXMOXER = False


def proxmox_tags_to_dict(str_tag):
    if not str_tag:
        return {}
    try:
        return {
            t.split('-')[0]: t.split('-', 1)[1].replace('..', ':'
                ).replace('_', ' ').replace('--', '/')
            for t in str_tag.split(',')}
    except IndexError:
        return {}


def dict_to_proxmox_tags(dict_tag):
    return ','.join([
        '{0}-{1}'.format(k, v.replace(':', '..'
            ).replace(' ', '_').replace('/', '--'))
        for k, v in dict_tag.items()])


def proxmox_argument_spec():
    return dict(
        api_host=dict(),
        api_user=dict(),
        api_password=dict(no_log=True),
        validate_certs=dict(type='bool', default=False)
    )

def connect_to_proxmox(module):
    if not HAS_PROXMOXER:
        module.fail_json(msg='proxmoxer module required')

    if module.params['api_host'] is None and 'PROXMOX_HOST' not in os.environ:
        module.fail_json('mandatory parameter "api_host" is missing')

    if module.params['api_user'] is None and 'PROXMOX_USER' not in os.environ:
        module.fail_json('mandatory parameter "api_user" is missing')

    if module.params['api_password'] is None and 'PROXMOX_PASSWORD' not in os.environ:
        module.fail_json('mandatory parameter "api_password" is missing')

    api_host = module.params.get('api_host', os.environ.get('PROXMOX_HOST'))
    api_user = module.params.get('api_user', os.environ.get('PROXMOX_USER'))
    api_pass = module.params.get('api_password', os.environ.get('PROXMOX_PASSWORD'))
    elapsed = 0

    while elapsed < 3:
        try:
            proxmox = ProxmoxAPI(api_host,
                                 user=api_user,
                                 password=api_pass,
                                 verify_ssl=module.params['validate_certs'])
            break
        except requests.exceptions.RequestException:
            proxmox = None
            elapsed += 1
            time.sleep(1)
        except proxmoxer.backends.https.AuthenticationError as e:
            module.fail_json(
                msg='authorization on proxmox cluster failed with exception: %s' % e)

    if proxmox is None:
        raise requests.exceptions.ConnectTimeout(api_host)

    return proxmox


def get_vm_by_id(proxmox, vmid):
    return [vm for vm in proxmox.cluster.resources.get(type='vm') if vm['vmid'] == int(vmid)]


def get_vm_by_name(proxmox, name):
    return [vm for vm in proxmox.cluster.resources.get(type='vm') if vm['name'] == name]


def get_vmid(proxmox, name):
    return [vm['vmid'] for vm in proxmox.cluster.resources.get(type='vm') if vm.get('name') == name]


def serialize_disk(disk_value):
    regexp = re.search('(.*):(.*),(.*)=(.*)', disk_value)
    size = regexp.group(4)
    if re.search('(.*)G', size):
        size = re.search('(.*)G', size).group(1)
    return {
        'storage': regexp.group(1),
        'name': regexp.group(2),
        regexp.group(3): size}


def wait_for(node, taskid, timeout=30):
    retval = node.tasks(taskid).status.get()
    elapsed = 0
    while elapsed < timeout:
        if retval['status'] == 'stopped':
            break
        time.sleep(1)
        elapsed += 1
        retval = node.tasks(taskid).status.get()
    if elapsed > timeout or retval.get('exitstatus', 'KO') != 'OK':
        return False
    return True


def get_vm_config(proxmox, vm):
    results = {}
    mac = {}
    devices = {}
    config = proxmox.nodes('{node}/{type}/{vmid}'.format(**vm)).config.get()
    for key in config:
        if re.match('scsi[0-9]+', key) or re.match('sata[0-9]+', key) or \
                re.match('ide[0-9]+', key) or re.match('virtio[0-9]+', key):
            device = k
            k = vm[k]
            k = re.search('(.*?),', k).group(1)
            devices[device] = k
        if re.match('net[0-9]+', k):
            interface = k
            k = vm[k]
            k = re.search('=(.*?),', k).group(1)
            mac[interface] = k

    results['mac'] = mac
    results['devices'] = devices
    results['vmid'] = int(vmid)
    return results
