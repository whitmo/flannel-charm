#!/usr/bin/env python

import json
import httplib
import os
import time
import subprocess
import urllib
import urlparse


FLANNEL_TEMPLATE = os.path.join(
    os.environ.get('CHARM_DIR', ''), 'files', 'flannel.upstart')

LXC_NET_TEMPLATE = os.path.join(
    os.environ.get('CHARM_DIR', ''), "files", "default-lxc-net.template")

LXC_CONF_TEMPLATE = os.path.join(
    os.environ.get('CHARM_DIR', ''), "files", "default-lxc.template")

FLANNEL_SETTINGS = "/run/flannel/subnet.env"


def config_changed():
    """Validate config and install either lxc or docker."""
    svc_config = _conf()

    ctype = svc_config.get('container_type')
    if ctype not in ('lxc', 'docker'):
        raise ValueError("Invalid Container Type Configured %s" % (
            ctype))

    if ctype == 'lxc':
        return subprocess.check_output([
            'apt-get', 'install', '-qy', 'lxc'])

    origin = svc_config['docker_origin']
    if origin not in ('upstream', 'distro'):
        raise ValueError("Invalid docker origin configured %s" % (
            origin))

    if origin == 'upstream':
        _install_docker_upstream()
    else:
        subprocess.check_output([
            'apt-get', 'install', '-qy', 'docker.io'])
    subprocess.check_output([
        'usermod', '-a', '-G', 'docker', 'ubuntu'])


def _conf():
    return json.loads(subprocess.check_output([
        "config-get", "--format=json"]))


def _install_docker_upstream():
    subprocess.check_output([
        'apt-key', 'adv',
        '--keyserver', 'hkp://keyserver.ubuntu.com:80',
        '--recv-keys', '36A1D7869245C8950F966E92D8576A8BA88D21E9'])
    with open('/etc/apt/sources.list.d/docker.list', 'w') as fh:
        fh.write('deb https://get.docker.io/ubuntu docker main\n')
    subprocess.check_output(['apt-get', 'update'])
    subprocess.check_output(['apt-get', 'install', '-yq', 'lxc-docker'])


def db_relation_changed():
    result = write_config()

    if not result:
        return

    subprocess.check_output(['service', 'flannel', 'restart'])

    # Wait for flannel to initialize, this is generally immediate.
    while True:
        if os.path.exists(FLANNEL_SETTINGS):
            print("Flannel initialized.")
            break
        time.sleep(2)
        print("Waiting for flannel to initialize...")

    svc_config = _conf()
    ctype = svc_config['container_type']

    if ctype == 'lxc':
        initialize_lxc()
    elif ctype == 'docker':
        initialize_docker()
    else:
        raise ValueError(
            "Invalid container type configured %s" % ctype)

    # notify extant network relations
    network_changed()


def _flannel_conf():
    if not os.path.exists(FLANNEL_SETTINGS):
        return
    with open(FLANNEL_SETTINGS) as fh:
        net_info = dict([l.lower().strip().split('=')
                         for l in fh.readlines()])
    return net_info


def network_changed():
    """Notify extant network relations that the network is configured.
    """
    conf = _flannel_conf()
    if not conf:
        return

    ids = json.loads(subprocess.check_output(
        ['relation-ids', '--format=json', 'network']))

    for i in ids:
        subprocess.check_output(
            ['relation-set', '-r', i,
             'bridge_name=docker0',
             'overlay_type=udp',
             'bridge_cidr=%s' % conf['flannel_subnet'],
             'bridge_mtu=%s' % conf['flannel_mtu']])


def write_config():
    """ Write the flannel config.
    """
    remote_data = json.loads(subprocess.check_output([
        "relation-get", "--format=json"]))

    unit_data = json.loads(subprocess.check_output([
        "relation-get", "--format=json", "-", os.environ['JUJU_UNIT_NAME']]))

    # TODO: Update this when we get relation-broken, or relation-departed
    # albeit how is interesting...
    if unit_data.get('etcd_endpoint'):
        return

    if not "port" in remote_data:
        return

    etcd_endpoint = "http://%(hostname)s:%(port)s" % remote_data
    template_data = {}
    template_data = {"etcd_endpoint": etcd_endpoint}

    with open(FLANNEL_TEMPLATE) as fh:
        template = fh.read()

    config = template % template_data

    initialize_etcd(etcd_endpoint)

    with open('/etc/init/flannel.conf', 'w') as fh:
        fh.write(config)

    subprocess.check_output(
        ['relation-set', 'etcd_endpoint=%s' % etcd_endpoint])
    return True


def initialize_docker():
    net_info = _flannel_conf()
    tmpl = 'DOCKER_OPTS="$DOCKER_OPTS --bip=%s --mtu=%s"\n'
    opts = tmpl % (net_info['flannel_subnet'], net_info['flannel_mtu'])

    svc_config = _conf()
    name = svc_config['docker_origin'] == 'distro' and 'docker.io' or 'docker'
    path = "/etc/default/%s" % name

    # Sanity check first
    with open(path) as fh:
        lines = fh.readlines()
        if opts.strip() in lines:
            print("Docker already initialized.. skipping")
            return

    with open('/etc/default/%s' % name, 'a') as fh:
        fh.write(opts)

    # So docker is immediately running post package install, and
    # pre-configures a bridge. Stopping docker doesn't remove the
    # bridge. So post configuring flannel...
    # We need to stop docker, bring the bridge interface down, and
    # delete the old bridge before we bring docker back up to
    # configure the new bridge.
    try:
        subprocess.check_output(["service", name, "stop"])
    except subprocess.CalledProcessError:
        # if already down we've reached the same state.
        pass
    subprocess.check_output(["ifconfig", "docker0", "down"])
    subprocess.check_output(["brctl", "delbr", "docker0"])

    subprocess.check_output(["service", name, "restart"])
    print("Docker Initialized")


def initialize_lxc():
    net_info = _flannel_conf()
    cidr = net_info['flannel_subnet']
    net_info['bridge_addr'], netmask = cidr.split('/')
    net_info['dhcp_start'] = "%s.2" % cidr.rsplit('.', 1)[0]
    net_info['dhcp_end'] = "%s.254" % cidr.rsplit('.', 1)[0]
    net_info['network_cidr'] = net_info['flannel_subnet']
    net_info['network_mtu'] = net_info['flannel_mtu']

    with open(LXC_NET_TEMPLATE) as fh:
        template = fh.read()
        rendered = template % net_info
        with open("/etc/default/lxc-net", "w") as fh:
            fh.write(rendered)

    with open(LXC_CONF_TEMPLATE) as fh:
        template = fh.read()
        rendered = template % net_info
        with open("/etc/lxc/default.conf", "w") as fh:
            fh.write(rendered)
    subprocess.check_output(["service", "lxc-net", "restart"])
    print("LXC Initialized")


def initialize_etcd(endpoint,
                    flannel_prefix="/coreos.com/network",
                    flannel_network="10.10.0.0/16"):

    parsed = urlparse.urlparse(endpoint)
    params = urllib.urlencode(
        {"value": json.dumps({'Network': flannel_network})})
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    path = "/v2/keys%s/config" % flannel_prefix
    conn = httplib.HTTPConnection(parsed.hostname, parsed.port)
    conn.request("PUT", path, params, headers)
    response = conn.getresponse()
    data = json.loads(response.read())
    print("Initialize Etcd Network %s %s" % (response.status, response.reason))
    print(data)
