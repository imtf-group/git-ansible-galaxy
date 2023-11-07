#!/usr/bin/env python

ANSIBLE_METADATA = {'metadata_version': '1.2',
                    'status': ['stableinterface'],
                    'supported_by': 'Jean-Baptiste Langlois'}

DOCUMENTATION = '''
---
module: partition
short_description: create, resize, list or delete disk partitions
description:
    - create, resize, list or delete disk partitions.
options:
  disk:
    description:
      - disk to partition
    aliases: ['devices']
    required: true
  flags:
    description:
      - add partition flags ('raid', 'boot', 'lba', 'swap', 'lvm', 'hidden', 'root', etc.)
    aliases: ['flag']
  length:
    description:
      - new partition size (in MB). If empty, the remaining space is used.
    aliases: ['size']
  name:
    required: true
    aliases: ['path']
    description:
      - the partition name. optional on list and creation, mandatory on deletion or resize.
  state:
    description:
      - create, resize, list or delete disk partitions
    required: false
    default: 'present'
    choices: ['present', 'absent', 'list']
  resize:
    description:
      - resize an existing partition, rather adding a new one
    type: bool
    default: 'no'
  type:
    description:
      - partition types
    default: 'primary'
    choices: ['primary', 'logical', 'extended', 'free-space', 'metadata']

author:
    - "Jean-Baptiste-Langlois (jeanbaptiste.langlois@gmail.com)"
'''

EXAMPLES = '''
# Creation a LVM partition to use a full disk
- partition:
    device: /dev/sdf
    path: /dev/sdf1
    flags: lvm
    state: present

# Resize an existing partition to 20GB
- partition:
    device: /dev/sdf
    path: /dev/sdf1
    resize: yes
    size: 20000
    state: present

# Delete an existing partition
- partition:
    device: /dev/sdf
    path: /dev/sdf1
    state: absent

# Create a 2GB extended partition with two logical partition in it
- partition:
    device: /dev/sdf
    size: "{{ item.size }}"
    type: "{{ item.type }}"
  loop:
    - { size: 2000, type: extended }
    - { size: 1500, type: logical }
    - { size: 500, type: logical }
'''

import os
import json
import time
from ansible.module_utils.basic import AnsibleModule

try:
    import parted
    import _ped
    HAS_PYPARTED = True
except ImportError:
    HAS_PYPARTED = False


class DiskCommand(object):
    @staticmethod
    def types():
        return {
            parted.PARTITION_NORMAL:    "primary",
            parted.PARTITION_LOGICAL:   "logical",
            parted.PARTITION_EXTENDED:  "extended",
            parted.PARTITION_FREESPACE: "free-space",
            parted.PARTITION_METADATA:  "metadata"
        }

    @staticmethod
    def flags():
        return {
            flag: _ped.partition_flag_get_name(flag) for flag in range(1, 16)
        }

    def __init__(self, name):
        device = parted.getDevice(name)
        try:
            self.disk = parted.Disk(device)
        except (_ped.DiskException, _ped.DiskLabelException):
            self.disk = parted.freshDisk(device, 'msdos')

    def sectors_by_size(self, length):
        if not length:
            return 0
        return parted.sizeToSectors(length,
                                    'MiB',
                                    self.disk.device.sectorSize)

    def partition(self, name=None):
        return Partition(self.disk, name)


class Partition(object):
    def __init__(self, disk, name=None):
        self.disk = disk
        self.name = None
        self.number = 0
        if name is not None:
            for partition in self.disk.partitions:
                if partition.path == name:
                    self.update(partition)
                    break
            else:
                raise _ped.PartitionException("Partition not found: %s" % name)

    def update(self, partition):
        self.number = partition.number
        self.active = partition.active
        self.name = partition.path
        self.start = partition.geometry.start
        self.end = partition.geometry.end
        self.length = partition.geometry.length
        self.flags = []
        self.filesystem = (partition.fileSystem.type if partition.fileSystem
                           else None)
        self.type = (DiskCommand.types()[partition.type]
                     if partition.type in DiskCommand.types() else "unknown")
        for f, v in DiskCommand.flags().items():
            if partition.getFlag(f):
                self.flags.append(v)

    def __str__(self):
        return json.dumps(self.facts(), indent=2)

    def facts(self):
        if self.name is None:
            raise ValueError('No partition selected')
        return {
            'number': self.number,
            'active': self.active,
            'path': self.name,
            'geometry': {
                'start': self.start,
                'end': self.end,
                'length': self.length,
            },
            'flags': self.flags,
            'size_mb': (self.length * self.disk.device.sectorSize // 1024**2),
            'filesystem': self.filesystem,
            'type': self.type
        }

    def _compute_geometry(self, length, partition_type=None, resizing=False):
        if partition_type is None:
            partition_type = self.type
        if resizing is True:
            start = self.start
        elif partition_type == 'logical':
            if not self.disk.getExtendedPartition():
                raise _ped.PartitionException(
                    'Cannot create logical partition: No extended partition found')
            start = self.disk.getExtendedPartition().geometry.start + 4 * self.disk.device.sectorSize
            for partition in self.disk.getLogicalPartitions():
                if start >= partition.geometry.start and start <= partition.geometry.end:
                    start = partition.geometry.end + 4 * self.disk.device.sectorSize
        else:
            start = 4 * self.disk.device.sectorSize
            for partition in self.disk.partitions:
                if partition.type in (parted.PARTITION_EXTENDED, parted.PARTITION_NORMAL):
                    if start >= partition.geometry.start and start <= partition.geometry.end:
                        start = partition.geometry.end + 1
        if length > 0:
            if start + length >= self.disk.device.length:
                raise _ped.GeometryException(
                    'No such disk space left on disk (%d MB on %d MB left)' % (
                        length * self.disk.device.sectorSize // 1024**2,
                        (self.disk.device.length - start) * self.disk.device.sectorSize // 1024**2))
            end = start + length
        elif partition_type == 'logical':
            end = self.disk.getExtendedPartition().geometry.end
            for partition in self.disk.getLogicalPartitions():
                if resizing is True and partition.number == self.number:
                    continue
                if start < partition.geometry.start:
                    end = partition.geometry.start - 1
        else:
            end = self.disk.device.length - 1
            for partition in self.disk.partitions:
                if resizing is True and partition.number == self.number:
                    continue
                if partition.type in (parted.PARTITION_EXTENDED, parted.PARTITION_NORMAL):
                    if start < partition.geometry.start:
                        end = partition.geometry.start - 1
        return parted.Geometry(start=start, end=end, device=self.disk.device)

    def delete(self, check_mode=False):
        if self.name is None:
            raise ValueError('No partition selected')
        if self.disk.device.busy:
            raise _ped.DiskException("Resource is busy: %s" % self.disk.device.path)
        for partition in self.disk.partitions:
            if partition.number == self.number:
                break
        else:
            raise _ped.PartitionException("Partition not found: %s" % self.name)
        if not self.disk.deletePartition(partition):
            return False
        if not check_mode:
            loop = 0
            ok = False
            while loop < 5:
                loop += 1
                try:
                    ok = self.disk.commit()
                    break
                except _ped.IOException:
                    time.sleep(2)
            else:
                raise _ped.IOException('Device or resource busy')
            if not ok:
                raise _ped.IOException('Changes could not be commited')
        return True

    def resize(self, length=0, check_mode=False):
        if self.name is None:
            raise ValueError('No partition selected')
        if self.disk.device.busy:
            raise _ped.DiskException("Resource is busy: %s" % self.disk.device.path)
        if self.disk.device.length < length:
            raise _ped.DiskException(
                "The disk size is %d sectors but the 'length' value is %d sectors" % (
                    self.disk.device.length, length))
        if abs(self.length - length) < 2:
            return False
        if length != 0 and length < self.length - 1:
            raise _ped.PartitionException('Cannot reduce partitions')
        for partition in self.disk.partitions:
            if partition.number == self.number:
                break
        else:
            raise _ped.PartitionException("Partition not found: %s" % self.name)

        geom = self._compute_geometry(length, resizing=True)
        if abs(self.length - geom.length) < 2:
            return False
        constraint = parted.Constraint(exactGeom=geom)
        if not self.disk.maximizePartition(partition=partition, constraint=constraint):
            return False
        for partition in self.disk.partitions:
            if partition.path == self.name:
                self.update(partition)
                break
        if not check_mode:
            loop = 0
            ok = False
            while loop < 5:
                loop += 1
                try:
                    ok = self.disk.commit()
                    break
                except _ped.IOException:
                    time.sleep(2)
            else:
                raise _ped.IOException('Device or resource busy')
            if not ok:
                raise _ped.IOException('Changes could not be commited')
        return True

    def create(self, partition_type='primary', length=0, flags=[], check_mode=False):
        if self.disk.device.busy:
            raise _ped.DiskException("Resource is busy: %s" % self.disk.device.path)
        if self.disk.device.length < length:
            raise _ped.DiskException(
                "The disk size is %d sectors but the 'length' value is %d sectors" % (
                    self.disk.device.length, length))
        geom = self._compute_geometry(length, partition_type)
        constraint = parted.Constraint(startAlign=self.disk.device.optimumAlignment,
                                       endAlign=self.disk.device.optimumAlignment,
                                       device=self.disk.device)
        for f, v in DiskCommand.types().items():
            if partition_type == v:
                ptype = f
                break
        else:
            raise _ped.UnknownTypeException('Partition type: %s' % partition_type)
        new_partition = parted.Partition(disk=self.disk, type=ptype, geometry=geom)
        pflags = [key for flag in flags
                  for key, val in DiskCommand.flags().items()
                  if val == flag]
        for pf in pflags:
            new_partition.setFlag(pf)
        self.update(new_partition)
        if not self.disk.addPartition(new_partition, constraint=constraint):
            return False
        if not check_mode:
            loop = 0
            ok = False
            while loop < 5:
                loop += 1
                try:
                    ok = self.disk.commit()
                    break
                except _ped.IOException:
                    time.sleep(2)
            else:
                raise _ped.IOException('Device or resource busy')
            if not ok:
                raise _ped.IOException('Changes could not be commited')
        return True


def main():
    module = AnsibleModule(argument_spec=dict(
            disk=dict(required=True, aliases=['device']),
            flags=dict(required=False, type='list', aliases=['flag'], default=[]),
            length=dict(required=False, type='int', aliases=['size']),
            name=dict(required=False, aliases=['path']),
            state=dict(required=False, default='present', choices=['absent', 'present', 'list']),
            resize=dict(required=False, type='bool', default=False),
            type=dict(required=False, default='primary', choices=list(DiskCommand.types().values()))
        ),
        required_if=[
            ['state', 'absent', ['name']],
            ['resize', True, ['name']],
        ],
        supports_check_mode=True
    )

    if not HAS_PYPARTED:
        module.fail_json(msg='pyparted module required')

    if os.getuid() != 0:
        module.fail_json(msg='root access required to execute this module')

    param_disk = module.params.get('disk')
    param_length = module.params.get('length')
    param_flags = module.params.get('flags')
    param_name = module.params.get('name')
    param_state = module.params.get('state')
    param_type = module.params.get('type')
    param_resize = module.params.get('resize')
    changed = False

    if param_flags:
        for flag in param_flags:
            if flag not in DiskCommand.flags().values():
                module.fail_json(
                    changed=False,
                    msg="value of flags must be one of: %s, got: %s" % (','.join(
                        DiskCommand.flags().values()), flag))

    try:
        dc = DiskCommand(param_disk)
    except Exception as e:
        module.fail_json(changed=False, msg=str(e))
    sector_length = dc.sectors_by_size(param_length)

    if param_state == 'present':
        partition = None
        if param_resize is False:
            if param_name:
                try:
                    partition = dc.partition(param_name)
                except _ped.PartitionException as e:
                    pass
            if partition is None:
                partition = dc.partition()
                try:
                    changed = partition.create(partition_type=param_type,
                                               length=sector_length,
                                               flags=param_flags,
                                               check_mode=module.check_mode)
                except Exception as e:
                    module.fail_json(changed=False, msg=str(e))
        else:
            try:
                partition = dc.partition(param_name)
            except _ped.PartitionException as e:
                module.fail_json(changed=False, msg=str(e))
            try:
                changed = partition.resize(length=sector_length,
                                           check_mode=module.check_mode)
            except Exception as e:
                module.fail_json(changed=False, msg=str(e))
        module.exit_json(changed=changed, partition=partition.facts())

    if param_state == 'list':
        if param_name:
            try:
                partition = dc.partition(param_name)
            except _ped.PartitionException as e:
                module.fail_json(changed=False, msg=str(e))
            module.exit_json(changed=False, partition=partition.facts())
        else:
            partitions = []
            for p in dc.disk.partitions:
                partition = dc.partition(p.path)
                partitions.append(partition.facts())
            module.exit_json(changed=False, partitions=partitions)

    if param_state == 'absent':
        try:
            partition = dc.partition(param_name)
        except _ped.PartitionException as e:
            module.exit_json(changed=False)
        try:
            partition.delete(check_mode=module.check_mode)
        except Exception as e:
            module.fail_json(changed=False, msg=str(e))
        module.exit_json(changed=True)


if __name__ == '__main__':
    main()
