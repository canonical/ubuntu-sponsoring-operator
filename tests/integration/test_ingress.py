# Copyright 2025 Canonical
# See LICENSE file for licensing details.

import jubilant
from requests import Session

from . import APPNAME, HAPROXY, SSC, DNSResolverHTTPSAdapter, address, retry


def deploy_ha_wait_func(status):
    """Wait on juju status until deployed and started."""
    return (
        status.apps[APPNAME].is_active
        and status.apps[HAPROXY].is_active
        and status.apps[SSC].is_active
    )


def test_service_state_after_ha_deploy(juju: jubilant.Juju, ubuntu_sponsoring_charm):
    """Deploy the charm with haproxy and wait until active."""
    juju.deploy(ubuntu_sponsoring_charm, app=APPNAME)
    juju.deploy(
        HAPROXY,
        channel="2.8/edge",
        config={"external-hostname": "ubuntu-sponsoring.internal"},
    )
    juju.deploy(SSC, channel="1/edge")

    juju.integrate(APPNAME, HAPROXY)
    juju.integrate(f"{HAPROXY}:certificates", f"{SSC}:certificates")

    juju.wait(deploy_ha_wait_func, timeout=3600)


@retry(retry_num=24, retry_sleep_sec=10)
def test_reports_are_served_over_ingress(juju: jubilant.Juju):
    """Check the sponsoring report endpoint through haproxy ingress."""
    model_name = juju.model
    assert model_name is not None

    haproxy_ip = address(juju, app=HAPROXY)
    external_hostname = "ubuntu-sponsoring.internal"

    session = Session()
    session.mount("https://", DNSResolverHTTPSAdapter(external_hostname, haproxy_ip))
    response = session.get(
        f"https://{haproxy_ip}/{model_name}-{APPNAME}/",
        headers={"Host": external_hostname},
        verify=False,
        timeout=60,
    )

    assert response.status_code == 200
