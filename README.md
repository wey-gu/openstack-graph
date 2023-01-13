## OpenStack Graph Demo

I would like to create a demo project on how the graph tech helps Ops of the Infra, and I will start from a system like OpenStack to do the job.

**Resource monitoring**(push)

We could watch the component where resources being created will naturally report to, in OpenStack, subscribing to the message bus on specific topics per each service (nova, neutron, Aodh and heat, etc) will do the job.

Luckily, OpenStack Vitrage already provides this capability out of the box! With it, we could have the resources/alarms in a single graph view from [one vitrage API call](https://docs.openstack.org/vitrage/zed/contributor/vitrage-api.html#get-topology).

We could do equivalent things for other infra systems like K8s.

![](https://user-images.githubusercontent.com/1651790/212026019-6f06683c-f3ad-4d32-bb88-56d2b4c129de.png)

**Resource fetching**(pull)

Vitrage collects the resource from the OpenStack cluster in a push way(from OpenStack to Entity Graph of Vitrage), while, we could also do it in a pull fashion, in a real-world case, it will be finally orchestrated by some DAG tools, but here I just create a script to demonstrate so.

Currently, the script will fetch the below relations, which were not collected by vitrage for now.

- glance_used_by:
  `image -[:used_by]-> instance (get from instance)`
- glance_created_from:
  `image -[:created_from]-> volume (get from image)`
- nova_keypair_used_by:
  `keypair -[:used_by]-> instance (get from instance)`
- cinder_snapshot_created_from:
  `volume snapshot -[:created_from]-> volume (get from snapshot)`
- cinder_volume_created_from:
  `volume -[:created_from]-> volume snapshot (get from volume)`
- cinder_volume_created_from:
  `volume -[:created_from]-> image (get from volume)`

**Graph ETL**

- For the push pattern, I created a demo [utils/vitrage_to_graph.py](utils/vitrage_to_graph.py) to call vitrage API to generate a full graph of the whole Infra, and then create DDL and DML queries to load data into NebulaGraph in Batch, this is only for demo/PoC purposes, in a real-world case, we could do streaming things in similar ways, too.

And the infra resources look like this:

![](https://user-images.githubusercontent.com/1651790/212024265-ca374ea0-fd60-4e68-84e2-512f5f3ff9a6.png)

- For the pull pattern, I created a demo script [utils/pull_resources_to_graph.py](utils/pull_resources_to_graph.py) to fetch nova, cinder, and glance API to construct Graph Data ready for NebulaGraph.

And after this data is added on top of the previous graph, it looks like this:

![](https://user-images.githubusercontent.com/1651790/212102993-849fd470-1e44-4706-af3f-dfb8500bd978.png)

**How to leverage the Graph**

English: TBD

Chinese: https://www.siwei.io/graph-enabled-infra-ops/

## Demo

> Please follow the Environment Setup steps first.

### Parse resources from the whole infra

The steps will be:

- Call `utils/vitrage_to_graph.py` from OpenStack controller: node0 to generate a graph ready for NebulaGraph
- Call `utils/pull_resources_to_graph.py` from OpenStack controller: node0 to have more data ready for NebulaGraph
- Load data into NebulaGraph
- Get insights from the Graph

#### Parse resources from OpenStack

##### The push pattern(vitrage)

```bash
ssh stack@node0_ip
cd devstack
wget https://raw.githubusercontent.com/wey-gu/openstack-graph/main/utils/vitrage_to_graph.py
wget https://raw.githubusercontent.com/wey-gu/openstack-graph/main/utils/pull_resources_to_graph.py.py
python3 vitrage_to_graph.py
python3 pull_resources_to_graph.py
```

Then we could see new files generated:

```bash
$ git status
On branch stable/zed
Your branch is up to date with 'origin/stable/zed'.

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	edges/
	schema.ngql
	vitrage_to_graph.py
	vertices/

# sudo apt install tree -y
edges
|-- attached.csv
|-- attached.ngql
|-- cinder.snapshot.created_from.ngql
|-- cinder.volume.created_from.ngql
|-- contains.csv
|-- contains.ngql
|-- glance.image.created_from.ngql
|-- glance.image.used_by.ngql
`-- nova.keypair.used_by.ngql
vertices
|-- cinder.volume.csv
|-- cinder.volume.ngql
|-- cinder.volume_snapshot.ngql
|-- glance.image.ngql
|-- neutron.network.csv
|-- neutron.network.ngql
|-- neutron.port.csv
|-- neutron.port.ngql
|-- nova.host.csv
|-- nova.host.ngql
|-- nova.instance.csv
|-- nova.instance.ngql
|-- nova.keypair.ngql
|-- nova.zone.csv
|-- nova.zone.ngql
|-- openstack.cluster.csv
`-- openstack.cluster.ngql
```

Where:

- `schema.ngql` is the DDL schema
- `edges` contains all edges, and the corresponding `ngql` file is the DDL/DML to load the data, `csv` is the raw data
- `vertices` contains all vertices, and the corresponding `ngql` file is the DML to load the data, `csv` is the raw data


#### Load it to NebulaGraph

Here I put the generated data into `sample_data` of this repo for reference purposes, too.

- Install a NebulaGraph in one command with [Nebula-Up](https://github.com/wey-gu/nebula-up)
- Following [here](https://github.com/wey-gu/openstack-graph/tree/main/sample_data) to load the Graph Data into [NebulaGraph](https://github.com/vesoft-inc/nebula)


## Environment Setup

### Prepare for multiple nodes in a single Linux Server

Here I will prepare multiple nodes in Ubuntu 20.04 with libvirt and Linux bridge so that I can run multiple VMs in a single Linux Server.

In this demo, I will use 2 VMs, one for OpenStack Controller & Compute, and one for OpenStack Compute only.

- node0, controller & compute
- node1, compute

#### Install libvirt

```bash
sudo apt install libvirt-daemon-system libvirt-clients bridge-utils virtinst
```

#### Prepare images

```bash
mkdir -p ~/libvirt && cd ~/libvirt

wget https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img

sudo apt install cloud-utils whois -y

mkdir -p images

# this may not work in zsh
bash
VM_NAME="node0"
VM_USERNAME="stack"
VM_PASSWORD="stack"

mkdir -p images/$VM_NAME
sudo qemu-img convert \
  -f qcow2 \
  -O qcow2 \
  focal-server-cloudimg-amd64.img \
  images/$VM_NAME/root-disk.qcow2

sudo qemu-img resize \
  images/$VM_NAME/root-disk.qcow2 \
  50G

# cloud-init
sudo echo "#cloud-config
system_info:
  default_user:
    name: $VM_USERNAME
    home: /home/$VM_PASSWORD

password: $VM_PASSWORD
chpasswd: { expire: False }
hostname: $VM_NAME

# configure sshd to allow users logging in using password 
# rather than just keys
ssh_pwauth: True
" | sudo tee images/$VM_NAME/cloud-init.cfg

sudo cloud-localds \
  images/$VM_NAME/cloud-init.iso \
  images/$VM_NAME/cloud-init.cfg

# node2
VM_NAME="node0"

mkdir -p images/$VM_NAME
sudo qemu-img convert \
  -f qcow2 \
  -O qcow2 \
  focal-server-cloudimg-amd64.img \
  images/$VM_NAME/root-disk.qcow2

sudo qemu-img resize \
  images/$VM_NAME/root-disk.qcow2 \
  50G

# cloud-init
sudo echo "#cloud-config
system_info:
  default_user:
    name: $VM_USERNAME
    home: /home/$VM_PASSWORD

password: $VM_PASSWORD
chpasswd: { expire: False }
hostname: $VM_NAME

# configure sshd to allow users logging in using password 
# rather than just keys
ssh_pwauth: True
" | sudo tee images/$VM_NAME/cloud-init.cfg

sudo cloud-localds \
  images/$VM_NAME/cloud-init.iso \
  images/$VM_NAME/cloud-init.cfg
```

#### Create networks

```bash
sudo virsh net-define /dev/stdin <<EOF
<network>
  <name>network0</name>
  <bridge name="virbr_0"/>
  <forward mode="nat"/>
  <ip address="10.10.0.1" netmask="255.255.255.0">
    <dhcp>
      <range start="10.10.0.1" end="10.10.0.254"/>
    </dhcp>
  </ip>
</network>
EOF

sudo virsh net-define /dev/stdin <<EOF
<network>
  <name>network1</name>
  <bridge name="virbr_1"/>
  <forward mode="nat"/>
  <ip address="10.10.1.1" netmask="255.255.255.0">
    <dhcp>
      <range start="10.10.1.1" end="10.10.1.254"/>
    </dhcp>
  </ip>
</network>
EOF

sudo virsh net-start network0
sudo virsh net-start network1
```

#### Create VMs

I'll show examples of only node0, node1 is similar.

```bash
VM_NAME="node0"
sudo virt-install --name $VM_NAME \
    --memory 16384 --vcpus 8 \
    --network network=network0,model=virtio \
    --network network=network1,model=virtio \
    --os-type linux \
    --os-variant ubuntu20.04 \
    --virt-type kvm \
    --disk images/$VM_NAME/root-disk.qcow2,device=disk,bus=virtio \
    --disk images/$VM_NAME/cloud-init.iso,device=cdrom \
    --graphics none \
    --console pty,target_type=serial \
    --import -v
```

Then login with the credential we placed in cloud-init config(`stack:stack`), and configure the network manually:

```bash
# Check the mac address of the interfaces
ip a

# say they are 52:54:00:6a:52:fa and 52:54:00:ca:84:35

# Edit /etc/netplan/50-cloud-init.yaml
network:
    ethernets:
        enp1s0:
            dhcp4: true
            match:
                macaddress: 52:54:00:6a:52:fa
            set-name: enp1s0
        enp2s0:
            dhcp4: true
            match:
                macaddress: 52:54:00:ca:84:35
            set-name: enp2s0
    version: 2

# Apply the changes
sudo netplan apply

# Now we should see networks like this, but adresses should be different.

stack@node0:~$ ip a
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host
       valid_lft forever preferred_lft forever
2: enp1s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 52:54:00:6a:52:fa brd ff:ff:ff:ff:ff:ff
    inet 10.10.0.39/24 brd 10.10.0.255 scope global dynamic enp1s0
       valid_lft 2472sec preferred_lft 2472sec
    inet6 fe80::5054:ff:fe6a:52fa/64 scope link
       valid_lft forever preferred_lft forever
3: enp2s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 52:54:00:ca:84:35 brd ff:ff:ff:ff:ff:ff
    inet 10.10.1.176/24 brd 10.10.1.255 scope global dynamic enp2s0
       valid_lft 2224sec preferred_lft 2224sec
    inet6 fe80::5054:ff:feca:8435/64 scope link
       valid_lft forever preferred_lft forever
4: virbr0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN group default qlen 1000
    link/ether 52:54:00:97:b5:a6 brd ff:ff:ff:ff:ff:ff
    inet 192.168.122.1/24 brd 192.168.122.255 scope global virbr0
       valid_lft forever preferred_lft forever
```

Till now, we are doing things inside the VM via the `virsh console` under the hood during the virt-install.
We could exit the virsh console by pressing `Ctrl+]` and then login to the VM via ssh after this step.


### Install OpenStack

We will leverage the devstack to install OpenStack. The devstack is a set of scripts that can be used to install OpenStack on a single machine or a cluster of machines for development and testing purposes.

Here we are basically following the [multinode-lab guide](https://docs.openstack.org/devstack/zed/guides/multinode-lab.html) for release: stable/zed.

One more thing is, we will enable OpenStack Vitrage to help watching the message bus of the cluster and parse resources into a graph.

Let's ssh to them from the host and install OpenStack.

#### Controller, node0

```bash
ssh stack@node0_ip

# Install devstack
git clone https://opendev.org/openstack/devstack
cd devstack
git checkout stable/zed
cp sample/local.conf .

# edit local.conf
vim local.conf

# enable vitrage and conf for controller node
[[local|localrc]]
enable_plugin vitrage https://opendev.org/openstack/vitrage stable/zed

HOST_IP=10.10.0.39
FIXED_RANGE=10.4.128.0/20
FLOATING_RANGE=10.10.1.128/25
LOGFILE=/opt/stack/logs/stack.sh.log
ADMIN_PASSWORD=labstack
DATABASE_PASSWORD=supersecret
RABBIT_PASSWORD=supersecret
SERVICE_PASSWORD=supersecret

# this should be at the tailing part of the conf
# following https://github.com/openstack/vitrage/blob/master/devstack/README.rst

[[post-config|$NOVA_CONF]]
[DEFAULT]
notification_topics = notifications,vitrage_notifications
notification_driver = messagingv2

[notifications]
versioned_notifications_topics = versioned_notifications,vitrage_notifications
notification_driver = messagingv2
notification_format = both

[[post-config|$NEUTRON_CONF]]
[DEFAULT]
notification_topics = notifications,vitrage_notifications
notification_driver = messagingv2

[[post-config|$CINDER_CONF]]
[DEFAULT]
notification_topics = notifications,vitrage_notifications
notification_driver = messagingv2

[[post-config|$HEAT_CONF]]
[DEFAULT]
notification_topics = notifications,vitrage_notifications
notification_driver = messagingv2
policy_file = /etc/heat/policy.yaml

[[post-config|$AODH_CONF]]
[oslo_messaging_notifications]
driver = messagingv2
topics = notifications,vitrage_notifications
```

Then, let's run `stack.sh` to install DevStack on node0.

```bash
./stack.sh
```

#### Compute, node1

Let's do similar things to node1, but with different devstack conf.

```bash
# exit the node0
exit
# ssh to node1
ssh stack@node1_ip

git clone https://opendev.org/openstack/devstack
cd devstack
git checkout stable/zed
cp sample/local.conf .

# Edit local.conf
vim local.conf

# below are lines to be added
HOST_IP=10.10.0.86 # change this per compute node, here node1_ip is 10.10.0.86
FIXED_RANGE=10.4.128.0/20
FLOATING_RANGE=10.10.1.128/25
LOGFILE=/opt/stack/logs/stack.sh.log
ADMIN_PASSWORD=labstack
DATABASE_PASSWORD=supersecret
RABBIT_PASSWORD=supersecret
SERVICE_PASSWORD=supersecret
DATABASE_TYPE=mysql
SERVICE_HOST=10.10.0.39 # this is the ip of node0_ip
MYSQL_HOST=$SERVICE_HOST
RABBIT_HOST=$SERVICE_HOST
GLANCE_HOSTPORT=$SERVICE_HOST:9292
ENABLED_SERVICES=n-cpu,c-vol,placement-client,ovn-controller,ovs-vswitchd,ovsdb-server,q-ovn-metadata-agent
NOVA_VNC_ENABLED=True
NOVNCPROXY_URL="http://$SERVICE_HOST:6080/vnc_lite.html"
VNCSERVER_LISTEN=$HOST_IP
VNCSERVER_PROXYCLIENT_ADDRESS=$VNCSERVER_LISTEN
```

Then, let's run `stack.sh` to install DevStack on node1.

```bash
./stack.sh
```

#### Create resources on OpenStack

We will create a couple of different resources on OpenStack to see how Vitrage can help us to watch the message bus of the cluster and parse resources into a graph.

```bash
# ssh to node0
ssh stack@node0_ip

cd devstack

# credentials
source openrc admin admin
# suppress warnings
export PYTHONWARNINGS="ignore"


cinder create 1 --display-name volume-0
cinder create 1 --display-name volume-1 \
    --image-id c2f047f0-faf9-4985-ae4f-bbccf9ae25dc
cinder snapshot-create --name snapshot-202301111800-volume-1 volume-1
cinder upload-to-image volume-1 cirros_mod_from_volume-1

cinder type-create multiattach
cinder type-key multiattach set multiattach="<is> True"
cinder create 1 --display-name volume-2 \
    --volume-type $(openstack volume type show multiattach -f value -c id)

# create a server, whose image is cirros_mod_from_volume-1
# with one NIC in network: shared
openstack server create --flavor m1.nano \
    --image cirros_mod_from_volume-1 \
    --nic net-id=$(neutron net-show shared -f value -c id) \
    --wait server-0

# create a server with two networks: shared and private
# boot from volume
openstack server create --flavor m1.nano \
    --image cirros-0.5.2-x86_64-disk \
    --boot-from-volume 1 \
    --nic net-id=$(neutron net-show shared  -f value -c id) \
    --nic net-id=$(neutron net-show private -f value -c id) \
    --wait server-1

ssh-keygen
openstack keypair create \
    --public-key /home/stack/.ssh/id_rsa.pub key-0

# create a server with ssh-key, boot from volume, in public network
# force to be placed on node1
openstack --os-compute-api-version 2.74 server create --flavor m1.nano \
    --image cirros-0.5.2-x86_64-disk \
    --boot-from-volume 1 \
    --nic net-id=$(neutron net-show public -f value -c id) \
    --key-name key-0 \
    --host node1 \
    --wait server-2

openstack server create --flavor m1.nano \
    --snapshot snapshot-202301111800-volume-1 \
    --nic net-id=$(neutron net-show private -f value -c id) \
    --wait server-3

openstack server create --flavor m1.nano \
    --image cirros_mod_from_volume-1 \
    --nic net-id=$(neutron net-show public -f value -c id) \
    --key-name key-0 \
    --wait server-4

openstack server add volume \
    $(openstack server show server-4 -f value -c id) \
    $(openstack volume show volume-2 -f value -c id) \
    --device /dev/vdb

openstack server add volume \
    $(openstack server show server-3 -f value -c id) \
    $(openstack volume show volume-2 -f value -c id) \
    --device /dev/vdb

# let's then create two AZ and place two compute hosts there

openstack aggregate create --zone zone_a zone_a
openstack aggregate add host zone_a node0

openstack aggregate create --zone zone_b zone_b
openstack aggregate add host zone_b node1

openstack server create --flavor m1.nano \
    --image cirros-0.5.2-x86_64-disk \
    --nic net-id=$(neutron net-show public -f value -c id) \
    --key-name key-0 \
    --availability-zone zone_b \
    --wait server-5
```

Now we have created a bunch of resources on OpenStack. Let's check the resources on OpenStack.

```bash
$ nova list --fields name,OS-EXT-AZ:availability_zone,OS-EXT-SRV-ATTR:hypervisor_hostname
+--------------------------------------+----------+------------------------------+--------------------------------------+
| ID                                   | Name     | OS-EXT-AZ: Availability Zone | OS-EXT-SRV-ATTR: Hypervisor Hostname |
+--------------------------------------+----------+------------------------------+--------------------------------------+
| 89021f42-8339-439b-83b7-7e5e95eb1836 | server-0 | zone_a                       | node0                                |
| f00389e2-a8e7-4bd8-bfd7-dc8723b1afd9 | server-1 | zone_a                       | node0                                |
| a2a7989c-06d5-4324-9b74-cc5dff0b201a | server-2 | zone_b                       | node1                                |
| 22e3f5ab-270f-405d-9a20-9649d380abd7 | server-3 | zone_a                       | node0                                |
| 89bf047c-841f-4f13-b4a9-10411e7bee37 | server-4 | zone_a                       | node0                                |
| 3c90be50-d786-4230-9017-3927b0319de7 | server-5 | zone_b                       | node1                                |
+--------------------------------------+----------+------------------------------+--------------------------------------+

$ cinder list
+--------------------------------------+-----------+----------+------+-------------+----------+---------------------------------------------------------------------------+
| ID                                   | Status    | Name     | Size | Volume Type | Bootable | Attached to                                                               |
+--------------------------------------+-----------+----------+------+-------------+----------+---------------------------------------------------------------------------+
| 5d4bc7eb-bbc3-464e-9782-315683c2b097 | available | volume-0 | 1    | lvmdriver-1 | false    |                                                                           |
| 6f3873ad-cb1a-43cc-b5f1-73f796eb2088 | in-use    | volume-2 | 1    | multiattach | false    | 89bf047c-841f-4f13-b4a9-10411e7bee37,22e3f5ab-270f-405d-9a20-9649d380abd7 |
| 99187cfc-ceea-496a-a572-a9bb14e586ed | in-use    |          | 1    | lvmdriver-1 | true     | a2a7989c-06d5-4324-9b74-cc5dff0b201a                                      |
| c9db7c2e-c712-49d6-8019-14b82de8542d | in-use    |          | 1    | lvmdriver-1 | true     | 22e3f5ab-270f-405d-9a20-9649d380abd7                                      |
| eeb520cd-b253-4c2c-beaf-5b2e7cd1c4b7 | available | volume-1 | 1    | lvmdriver-1 | true     |                                                                           |
| ffaeb199-47f4-4d95-89b2-97fba3c1bcfe | in-use    |          | 1    | lvmdriver-1 | true     | f00389e2-a8e7-4bd8-bfd7-dc8723b1afd9                                      |
+--------------------------------------+-----------+----------+------+-------------+----------+---------------------------------------------------------------------------+

$ neutron port-list
+--------------------------------------+------+----------------------------------+-------------------+-------------------------------------------------------------------------------------------------------------+
| id                                   | name | tenant_id                        | mac_address       | fixed_ips                                                                                                   |
+--------------------------------------+------+----------------------------------+-------------------+-------------------------------------------------------------------------------------------------------------+
| 0a6b617a-dacb-4540-9965-83df911a8885 |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:9c:6d:b8 | {"subnet_id": "3586c7ba-c2ae-411d-8e15-bc246603b0a8", "ip_address": "192.168.233.2"}                        |
| 2de6d2fa-6f3c-4435-a8de-5bd2c4653f0f |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:87:9e:92 | {"subnet_id": "5fcd14d7-fbbe-4222-8991-c165a0e78744", "ip_address": "10.10.1.173"}                          |
|                                      |      |                                  |                   | {"subnet_id": "1548035e-4013-42a7-8b7b-81ced707f9bb", "ip_address": "2001:db8::d1"}                         |
| 2e607bec-eb83-4742-9501-9608a267780c |      | c2e03819f3464450b0181e1572ea5bc3 | fa:16:3e:f5:c0:73 | {"subnet_id": "7398f0b4-d5e4-45b4-8289-536142ba84a6", "ip_address": "10.0.0.1"}                             |
| 344ebd38-374d-4dd5-bade-356d0cbf364c |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:18:e9:82 | {"subnet_id": "7398f0b4-d5e4-45b4-8289-536142ba84a6", "ip_address": "10.0.0.13"}                            |
|                                      |      |                                  |                   | {"subnet_id": "65e28ce8-01db-40ea-89d0-d0e599094960", "ip_address": "fd65:2b3b:e473:0:f816:3eff:fe18:e982"} |
| 3a4458b5-2f07-44da-bfc3-fd35c0e32b3f |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:40:84:6e |                                                                                                             |
| 44a7a252-f149-43cc-8cf6-4572bec5500f |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:3b:7d:82 | {"subnet_id": "3586c7ba-c2ae-411d-8e15-bc246603b0a8", "ip_address": "192.168.233.39"}                       |
| 56d2d86a-f071-4cf6-99fc-f3fce740444f |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:d2:c6:97 | {"subnet_id": "5fcd14d7-fbbe-4222-8991-c165a0e78744", "ip_address": "10.10.1.219"}                          |
|                                      |      |                                  |                   | {"subnet_id": "1548035e-4013-42a7-8b7b-81ced707f9bb", "ip_address": "2001:db8::40"}                         |
| 6734d4a1-3342-4f9f-87b5-ca365689dd39 |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:16:a6:fc | {"subnet_id": "7398f0b4-d5e4-45b4-8289-536142ba84a6", "ip_address": "10.0.0.34"}                            |
|                                      |      |                                  |                   | {"subnet_id": "65e28ce8-01db-40ea-89d0-d0e599094960", "ip_address": "fd65:2b3b:e473:0:f816:3eff:fe16:a6fc"} |
| 9365b209-7e8a-4425-8614-a5d201c03a6b |      | c2e03819f3464450b0181e1572ea5bc3 | fa:16:3e:a2:13:bb | {"subnet_id": "65e28ce8-01db-40ea-89d0-d0e599094960", "ip_address": "fd65:2b3b:e473::1"}                    |
| 96db053b-fe6a-44b6-8041-06403b871953 |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:09:02:09 | {"subnet_id": "3586c7ba-c2ae-411d-8e15-bc246603b0a8", "ip_address": "192.168.233.111"}                      |
| a1891c56-1e5d-4c59-b83d-2c24b3e90dcf |      | c2e03819f3464450b0181e1572ea5bc3 | fa:16:3e:d2:61:5e | {"subnet_id": "7398f0b4-d5e4-45b4-8289-536142ba84a6", "ip_address": "10.0.0.2"}                             |
|                                      |      |                                  |                   | {"subnet_id": "65e28ce8-01db-40ea-89d0-d0e599094960", "ip_address": "fd65:2b3b:e473:0:f816:3eff:fed2:615e"} |
| d27355a1-23cd-4955-89d0-dd2515113444 |      | 02ac3511dfdc468ea64c15a16f456964 | fa:16:3e:4a:a4:8b | {"subnet_id": "5fcd14d7-fbbe-4222-8991-c165a0e78744", "ip_address": "10.10.1.171"}                          |
|                                      |      |                                  |                   | {"subnet_id": "1548035e-4013-42a7-8b7b-81ced707f9bb", "ip_address": "2001:db8::1b"}                         |
| db9c574a-114e-45a2-b150-1d4cd852b966 |      |                                  | fa:16:3e:94:b7:22 | {"subnet_id": "5fcd14d7-fbbe-4222-8991-c165a0e78744", "ip_address": "10.10.1.245"}                          |
|                                      |      |                                  |                   | {"subnet_id": "1548035e-4013-42a7-8b7b-81ced707f9bb", "ip_address": "2001:db8::378"}                        |
+--------------------------------------+------+----------------------------------+-------------------+-------------------------------------------------------------------------------------------------------------+
```

Or we could verify the resources from OpenStack Dashboard(http://node0_ip/), with user: admin, password: labstack.

<img width="2032" alt="Dashboard view Openstack Network Resources" src="https://user-images.githubusercontent.com/1651790/212019987-f89362b1-5dcc-4107-a443-e60b642c0e04.png">


We could generate resource graph with vitrage client:

```bash
vitrage topology show --all-tenants
```
