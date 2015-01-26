Flannel
=======

A tunneling overlay network for containers.

One of the common issues when using containers in clouds is the
inability to do cross host communication between the containers as
they default to using a local bridge.

flannel uses the Universal TUN/TAP device and creates an overlay
network using UDP to encapsulate IP packets. The subnet allocation is
done with the help of etcd which maintains the overlay subnet to host
mappings.

This charm uses flannel to setup an overlay network and configures lxc
or docker containers on that host to use the overlay.

https://github.com/coreos/flannel
https://coreos.com/blog/introducing-rudder/


Usage
-----

Before we can deploy containers, we must setup the overlay.

First we need to deploy etcd:

  $ juju deploy cs:~hazmat/trusty/etcd

Now we can deploy a few units of flannel:

  $ juju deploy -n 2 cs:~hazmat/trusty/flannel

And relate flannel to etcd so it can coordinate the subnet assignment:

  $ juju add-relation flannel etcd

Congrats we now have a multi-host overlay network. Each host machine
will have a 10.10.x.0/24 subnet on it suitable for up to 253
containers. We can check the health and readiness of the overlay using
juju run:

  $ juju run --service=flannel ./health
  - MachineId: "0"
    Stdout: ready lxcbr:10.10.16.1 subnet:10.10.16.1/24 mtu:1472
    UnitId: flannel/2
  - MachineId: "2"
    Stdout: ready lxcbr:10.10.65.1 subnet:10.10.65.1/24 mtu:1472
    UnitId: flannel/0
  - MachineId: "3"
    Stdout: ready lxcbr:10.10.19.1 subnet:10.10.19.1/24 mtu:1472
    UnitId: flannel/1

A machine which isn't ready will have its output beging with
'not-ready'.


Now we can create containers on the various machines. Through juju
this is simply:

  $ juju add-machine lxc:2
  $ juju add-machine lxc:3


We can see the machines and their containers come up on their selected
subnets via juju status:

 $ juju status

 environment: ocean
 machines:
  "0":
    agent-state: started
    agent-version: 1.20.6
    dns-name: 104.131.201.155
    instance-id: 'manual:'
    series: trusty
    hardware: arch=amd64 cpu-cores=2 mem=2001M
    state-server-member-status: has-vote
  "1":
    agent-state: started
    agent-version: 1.20.6
    dns-name: 162.243.16.9
    instance-id: manual:162.243.16.9
    series: trusty
    hardware: arch=amd64 cpu-cores=2 mem=2001M
  "2":
    agent-state: started
    agent-version: 1.20.6
    dns-name: 162.243.51.21
    instance-id: manual:162.243.51.21
    series: trusty
    containers:
      2/lxc/0:
        agent-state: started
        agent-version: 1.20.6
        dns-name: 10.10.65.3
        instance-id: juju-machine-2-lxc-0
        series: precise
        hardware: arch=amd64
    hardware: arch=amd64 cpu-cores=2 mem=2001M
  "3":
    agent-state: started
    agent-version: 1.20.6
    dns-name: 162.243.123.121
    instance-id: manual:162.243.123.121
    series: trusty
    containers:
      3/lxc/1:
        agent-state: started
        agent-version: 1.20.6
        dns-name: 10.10.19.192
        instance-id: juju-machine-3-lxc-1
        series: precise
        hardware: arch=amd64
    hardware: arch=amd64 cpu-cores=2 mem=2001M


The overlay network is only configured on hosts where flannel is deployed.


To use juju ssh with these containers, we have to deploy the flannel
charm to the juju state server and the environment has to have the
proxy-ssh configuration set to true:

 $ juju deploy --to=0 flannel

Check that its running via juju-run and then we can:

 $ juju ssh 2/lxc/0

And now from this container, we can ping the container on the
otherhost to verify cross host container communication:

   ubuntu@juju-machine-2-lxc-0:~$ ping 10.10.19.192
   PING 10.10.19.192 (10.10.19.192) 56(84) bytes of data.
   64 bytes from 10.10.19.192: icmp_req=1 ttl=60 time=1.03 ms
   64 bytes from 10.10.19.192: icmp_req=2 ttl=60 time=1.01 ms
   ^C


Caveats
-------

- Juju does not support container cgroup constraints. See
  http://pad.lv/1242783 for the accompanying bug.

Charm Notes
-----------

Due to sensitivity of runtime changes and networkingc connectivity
this charm does not permit mutations to the configured network space
or key for networking.

The network is currently hardcoded to 10.10.0.0/16 (64k addresses) and
the default flannel etcd key "/coreos.com/network/config"


Credits
-------

Original charm by @kapilt
