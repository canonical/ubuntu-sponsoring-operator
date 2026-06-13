# Copyright 2025 Canonical
# See LICENSE file for licensing details.

import jubilant
import requests

from . import APPNAME, address, retry


def test_service_state_after_deploy(juju: jubilant.Juju, ubuntu_sponsoring_charm, lpuser_secret):
    """Deploy the charm via jubilant and wait until application is active."""
    juju.deploy(ubuntu_sponsoring_charm, app=APPNAME)

    if lpuser_secret:
        juju.config(APPNAME, {"lpuser_secret_id": lpuser_secret})
    # Without a credentials secret the charm falls back to anonymous report runs.

    juju.wait(jubilant.all_active, timeout=1200)


@retry(retry_num=24, retry_sleep_sec=10)
def test_reports_are_served(juju: jubilant.Juju):
    """Check that the report publication endpoint is served by nginx."""
    response = requests.get(f"http://{address(juju)}:80/", timeout=60)
    assert response.status_code == 200
