#!/usr/bin/env python3
# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Charmed Operator for Ubuntu Sponsoring."""

import logging
import shutil
import socket
from subprocess import CalledProcessError, SubprocessError

import ops
from charmlibs.apt import PackageError, PackageNotFoundError
from charmlibs.systemd import SystemdError
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer as IngressRequirer

from sponsoring import (
    DEFAULT_SYNC_INTERVAL,
    Sponsoring,
)

logger = logging.getLogger(__name__)

PORT = 80


class UbuntuSponsoringCharm(ops.CharmBase):
    """Charmed Operator for Ubuntu Sponsoring."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.ingress = IngressRequirer(self, port=PORT, strip_prefix=True, relation_name="ingress")

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.upgrade_charm, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.sync_now_action, self._on_sync_now)

        framework.observe(self.ingress.on.ready, self._on_config_changed)
        framework.observe(self.ingress.on.revoked, self._on_config_changed)

        self._sponsoring = Sponsoring()

    @property
    def _lpuser_secret(self) -> ops.model.Secret | None:
        secret_id: str = ""

        try:
            secret_id = str(self.config["lpuser_secret_id"])
        except KeyError:
            logger.warning("lpuser_secret_id config not available, unable to extract keys.")
            return None

        try:
            return self.model.get_secret(id=secret_id)
        except (ops.SecretNotFoundError, ops.model.ModelError):
            logger.warning("Failed to get lpuser secret with id %s", secret_id)

        return None

    @property
    def _lpuser_lp_oauthkey(self) -> str | None:
        secret = self._lpuser_secret

        if secret is not None:
            logger.debug("config - got secret id %s, returning key lpoauthkey", secret)
            try:
                return secret.get_content(refresh=True)["lpoauthkey"]
            except KeyError:
                logger.warning("lpoauthkey not found in lpuser secret.")

        return None

    @property
    def _sync_interval(self) -> int:
        return int(self.config.get("sync_interval", DEFAULT_SYNC_INTERVAL))

    def _active_status(self) -> ops.ActiveStatus:
        """Active status reflecting whether reports run authenticated or anonymously."""
        if self._lpuser_lp_oauthkey is not None:
            return ops.ActiveStatus()
        return ops.ActiveStatus("Running in anonymous mode (no Launchpad credentials)")

    def _on_install(self, event: ops.EventBase):
        """Handle install and upgrade events."""
        self.unit.status = ops.MaintenanceStatus("Setting up environment")
        try:
            self._sponsoring.install()
            self._sponsoring.update_source()
            self._sponsoring.setup_systemd_units()
            self._sponsoring.configure_run()
            self._sponsoring.configure_schedule(self._sync_interval)
        except (
            CalledProcessError,
            SubprocessError,
            SystemdError,
            PackageError,
            PackageNotFoundError,
            ValueError,
            IOError,
            OSError,
            shutil.Error,
        ) as e:
            logger.warning("Failed to set up the environment: %s", e)
            self.unit.status = ops.BlockedStatus(
                "Failed to set up the environment. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()

    def _on_start(self, event: ops.StartEvent):
        """Start nginx to serve the generated reports."""
        self.unit.status = ops.MaintenanceStatus("Starting Sponsoring")
        try:
            self._sponsoring.start()
        except (CalledProcessError, SystemdError):
            self.unit.status = ops.BlockedStatus(
                "Failed to start services. Check `juju debug-log` for details."
            )
            return
        self.unit.set_ports(PORT)
        self.unit.status = self._active_status()

    def _on_config_changed(self, event):
        """Update configuration."""
        logger.debug("config changed event")
        self.unit.status = ops.MaintenanceStatus("Updating configuration")

        try:
            self._sponsoring.update_source()
        except (CalledProcessError, SubprocessError) as e:
            logger.warning("Failed to update source checkout: %s", e)
            self.unit.status = ops.BlockedStatus(
                "Failed to update source. Check `juju debug-log` for details."
            )
            return

        self._sponsoring.configure_url(self._get_external_url())
        logger.debug("config change done - url set")

        lp_key_data = self._lpuser_lp_oauthkey
        if lp_key_data is not None:
            logger.debug("config - got lpoauthkey (length %d)", len(lp_key_data))
            if not self._sponsoring.configure_credentials(lp_key_data):
                self.unit.status = ops.BlockedStatus("Failed to update Launchpad credentials.")
                return
        else:
            logger.debug("config - no Launchpad credentials, using anonymous login")
            self._sponsoring.clear_credentials()
        logger.debug("config change done - credentials handled")

        try:
            self._sponsoring.configure_run()
            self._sponsoring.configure_schedule(self._sync_interval)
            self._sponsoring.trigger_run()
        except ValueError:
            self.unit.status = ops.BlockedStatus(
                "Invalid sync_interval. Use a positive number of minutes, e.g. 15 or 60."
            )
            return
        except (IOError, SystemdError):
            self.unit.status = ops.BlockedStatus(
                "Failed to write run configuration. Check `juju debug-log` for details."
            )
            return

        self.unit.status = self._active_status()

    def _on_sync_now(self, event: ops.ActionEvent):
        """Trigger an immediate report generation run."""
        self.unit.status = ops.MaintenanceStatus("Running sponsoring report")

        try:
            event.log("Running sponsoring report")
            self._sponsoring.run_sync()
        except (CalledProcessError, IOError):
            event.log("Sponsoring run failed")
            self.unit.status = ops.ActiveStatus(
                "Failed to run sponsoring report. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()

    def _get_external_url(self) -> str:
        """Report URL to access the Ubuntu sponsoring reports."""
        external_url = f"http://{socket.getfqdn()}:{PORT}"
        if binding := self.model.get_binding("juju-info"):
            unit_ip = str(binding.network.bind_address)
            external_url = f"http://{unit_ip}:{PORT}"
        if self.ingress.url:
            external_url = self.ingress.url
        return external_url


if __name__ == "__main__":  # pragma: nocover
    ops.main(UbuntuSponsoringCharm)
