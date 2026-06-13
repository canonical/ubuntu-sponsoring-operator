# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Unit tests for the charm."""

from subprocess import CalledProcessError
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import ops
import pytest
from charmlibs.apt import PackageError, PackageNotFoundError
from ops.testing import (
    ActiveStatus,
    Address,
    BindAddress,
    BlockedStatus,
    Context,
    Network,
    Relation,
    State,
    TCPPort,
)

from charm import UbuntuSponsoringCharm


@pytest.fixture
def ctx():
    return Context(UbuntuSponsoringCharm)


@pytest.fixture
def base_state():
    return State(leader=True)


@patch("charm.Sponsoring.install")
@patch("charm.Sponsoring.update_source")
@patch("charm.Sponsoring.setup_systemd_units")
@patch("charm.Sponsoring.configure_run")
@patch("charm.Sponsoring.configure_schedule")
def test_install_event_sets_active_status_on_success(
    configure_schedule_mock,
    configure_run_mock,
    setup_units_mock,
    update_source_mock,
    install_mock,
    ctx,
    base_state,
):
    state_in = State(
        leader=True,
        config={
            "sync_interval": 30,
        },
    )

    out = ctx.run(ctx.on.install(), state_in)

    assert out.unit_status == ActiveStatus()
    install_mock.assert_called_once()
    update_source_mock.assert_called_once()
    setup_units_mock.assert_called_once()
    configure_run_mock.assert_called_once_with()
    configure_schedule_mock.assert_called_once_with(30)


@patch("charm.Sponsoring.install")
@pytest.mark.parametrize(
    "exception",
    [
        PackageError,
        PackageNotFoundError,
        CalledProcessError(1, "foo"),
    ],
)
def test_install_event_blocks_charm_on_environment_setup_failure(
    install_mock, exception, ctx, base_state
):
    install_mock.side_effect = exception

    out = ctx.run(ctx.on.install(), base_state)

    assert out.unit_status == BlockedStatus(
        "Failed to set up the environment. Check `juju debug-log` for details."
    )


@patch("charm.Sponsoring.start")
def test_start_event_opens_port_80_and_sets_active_status(start_mock, ctx, base_state):
    out = ctx.run(ctx.on.start(), base_state)

    assert out.unit_status == ActiveStatus("Running in anonymous mode (no Launchpad credentials)")
    start_mock.assert_called_once()
    assert out.opened_ports == {TCPPort(port=80, protocol="tcp")}


@patch("charm.Sponsoring.start")
def test_start_event_blocks_charm_when_service_start_fails(start_mock, ctx, base_state):
    start_mock.side_effect = CalledProcessError(1, "foo")

    out = ctx.run(ctx.on.start(), base_state)

    assert out.unit_status == BlockedStatus(
        "Failed to start services. Check `juju debug-log` for details."
    )
    assert out.opened_ports == frozenset()


@patch(
    "charm.UbuntuSponsoringCharm._lpuser_lp_oauthkey",
    new_callable=PropertyMock,
)
@patch("charm.Sponsoring.update_source")
@patch("charm.Sponsoring.configure_credentials")
@patch("charm.Sponsoring.configure_url")
@patch("charm.Sponsoring.configure_run")
@patch("charm.Sponsoring.configure_schedule")
@patch("charm.Sponsoring.trigger_run")
def test_config_changed_event_configures_source_creds_and_run_mode(
    trigger_run_mock,
    configure_schedule_mock,
    configure_run_mock,
    configure_url_mock,
    configure_creds_mock,
    update_source_mock,
    lp_oauth_prop_mock,
    ctx,
):
    state_in = State(
        leader=True,
        config={"sync_interval": 60},
    )
    lp_oauth_prop_mock.return_value = "fake-token"
    configure_creds_mock.return_value = True

    out = ctx.run(ctx.on.config_changed(), state_in)

    assert out.unit_status == ActiveStatus()
    update_source_mock.assert_called_once()
    configure_url_mock.assert_called_once()
    configure_creds_mock.assert_called_once_with("fake-token")
    configure_run_mock.assert_called_once_with()
    configure_schedule_mock.assert_called_once_with(60)


@patch(
    "charm.UbuntuSponsoringCharm._lpuser_lp_oauthkey",
    new_callable=PropertyMock,
)
@patch("charm.Sponsoring.clear_credentials")
@patch("charm.Sponsoring.update_source")
@patch("charm.Sponsoring.configure_url")
@patch("charm.Sponsoring.configure_run")
@patch("charm.Sponsoring.configure_schedule")
def test_config_changed_event_blocks_charm_on_invalid_schedule(
    configure_schedule_mock,
    configure_run_mock,
    configure_url_mock,
    update_source_mock,
    clear_creds_mock,
    lp_oauth_prop_mock,
    ctx,
):
    state_in = State(
        leader=True,
        config={"sync_interval": 0},
    )
    lp_oauth_prop_mock.return_value = None
    configure_schedule_mock.side_effect = ValueError("invalid")

    out = ctx.run(ctx.on.config_changed(), state_in)

    assert out.unit_status == BlockedStatus(
        "Invalid sync_interval. Use a positive number of minutes, e.g. 15 or 60."
    )


@patch(
    "charm.UbuntuSponsoringCharm._lpuser_lp_oauthkey",
    new_callable=PropertyMock,
)
@patch("charm.Sponsoring.trigger_run")
@patch("charm.Sponsoring.configure_schedule")
@patch("charm.Sponsoring.configure_run")
@patch("charm.Sponsoring.configure_url")
@patch("charm.Sponsoring.clear_credentials")
@patch("charm.Sponsoring.update_source")
def test_config_changed_event_active_and_anonymous_when_no_creds(
    update_source_mock,
    clear_creds_mock,
    configure_url_mock,
    configure_run_mock,
    configure_schedule_mock,
    trigger_run_mock,
    lp_oauth_prop_mock,
    ctx,
    base_state,
):
    lp_oauth_prop_mock.return_value = None

    out = ctx.run(ctx.on.config_changed(), base_state)

    assert out.unit_status == ActiveStatus("Running in anonymous mode (no Launchpad credentials)")
    clear_creds_mock.assert_called_once()
    configure_run_mock.assert_called_once_with()


@patch("charm.Sponsoring.update_source")
def test_config_changed_event_blocks_charm_when_source_update_fails(
    update_source_mock, ctx, base_state
):
    update_source_mock.side_effect = CalledProcessError(1, "git")

    out = ctx.run(ctx.on.config_changed(), base_state)

    assert out.unit_status == BlockedStatus(
        "Failed to update source. Check `juju debug-log` for details."
    )


@patch("charm.Sponsoring.run_sync")
def test_sync_now_action_triggers_run_and_logs_message(run_sync_mock, ctx, base_state):
    out = ctx.run(ctx.on.action("sync-now"), base_state)

    assert ctx.action_logs == ["Running sponsoring report"]
    assert out.unit_status == ActiveStatus()
    run_sync_mock.assert_called_once()


@patch("charm.Sponsoring.run_sync")
def test_sync_now_action_sets_status_message_when_run_fails(run_sync_mock, ctx, base_state):
    run_sync_mock.side_effect = CalledProcessError(1, "sync")

    out = ctx.run(ctx.on.action("sync-now"), base_state)

    assert out.unit_status == ActiveStatus(
        "Failed to run sponsoring report. Check `juju debug-log` for details."
    )


@patch(
    "charm.UbuntuSponsoringCharm._lpuser_lp_oauthkey",
    new_callable=PropertyMock,
)
@patch("charm.Sponsoring.update_source")
@patch("charm.Sponsoring.configure_credentials")
@patch("charm.Sponsoring.configure_url")
@patch("charm.Sponsoring.configure_run")
@patch("charm.Sponsoring.configure_schedule")
@patch("charm.socket.getfqdn")
@patch("ops.model.Model.get_binding")
@patch("charm.Sponsoring.trigger_run")
def test_get_external_url_uses_fqdn_when_no_network_binding_or_ingress(
    trigger_run_mock,
    get_binding_mock,
    getfqdn_mock,
    configure_schedule_mock,
    configure_run_mock,
    configure_url_mock,
    configure_creds_mock,
    update_source_mock,
    lp_oauth_prop_mock,
    ctx,
):
    get_binding_mock.return_value = None
    getfqdn_mock.return_value = "test-host.example.com"
    lp_oauth_prop_mock.return_value = "fake-token"
    configure_creds_mock.return_value = True

    out = ctx.run(ctx.on.config_changed(), State(leader=True))

    assert out.unit_status == ActiveStatus()
    configure_url_mock.assert_called_once_with("http://test-host.example.com:80")


@patch(
    "charm.UbuntuSponsoringCharm._lpuser_lp_oauthkey",
    new_callable=PropertyMock,
)
@patch("charm.Sponsoring.update_source")
@patch("charm.Sponsoring.configure_credentials")
@patch("charm.Sponsoring.configure_url")
@patch("charm.Sponsoring.configure_run")
@patch("charm.Sponsoring.configure_schedule")
@patch("charm.Sponsoring.trigger_run")
def test_get_external_url_uses_juju_info_binding_ip_when_available(
    trigger_run_mock,
    configure_schedule_mock,
    configure_run_mock,
    configure_url_mock,
    configure_creds_mock,
    update_source_mock,
    lp_oauth_prop_mock,
    ctx,
):
    state = State(
        leader=True,
        networks={
            Network(
                "juju-info",
                bind_addresses=[BindAddress(addresses=[Address("192.168.1.10")])],
            ),
        },
    )
    lp_oauth_prop_mock.return_value = "fake-token"
    configure_creds_mock.return_value = True

    out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ActiveStatus()
    configure_url_mock.assert_called_once_with("http://192.168.1.10:80")


@patch(
    "charm.UbuntuSponsoringCharm._lpuser_lp_oauthkey",
    new_callable=PropertyMock,
)
@patch("charm.Sponsoring.update_source")
@patch("charm.Sponsoring.configure_credentials")
@patch("charm.Sponsoring.configure_url")
@patch("charm.Sponsoring.configure_run")
@patch("charm.Sponsoring.configure_schedule")
@patch("charm.Sponsoring.trigger_run")
def test_get_external_url_prioritizes_ingress_url_over_binding(
    trigger_run_mock,
    configure_schedule_mock,
    configure_run_mock,
    configure_url_mock,
    configure_creds_mock,
    update_source_mock,
    lp_oauth_prop_mock,
    ctx,
):
    ingress_relation = Relation(
        endpoint="ingress",
        interface="ingress",
        remote_app_name="traefik",
        remote_app_data={"ingress": '{"url": "https://ingress.example.com/"}'},
    )
    state = State(
        leader=True,
        networks={
            Network(
                "juju-info",
                bind_addresses=[BindAddress(addresses=[Address("192.168.1.10")])],
            ),
        },
        relations={ingress_relation},
    )
    lp_oauth_prop_mock.return_value = "fake-token"
    configure_creds_mock.return_value = True

    out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ActiveStatus()
    configure_url_mock.assert_called_once_with("https://ingress.example.com/")


def test_lpuser_secret_property_returns_none_when_secret_not_found():
    dummy = SimpleNamespace()
    dummy.config = {"lpuser_secret_id": "missing"}
    dummy.model = MagicMock()
    dummy.model.get_secret.side_effect = ops.SecretNotFoundError

    result = UbuntuSponsoringCharm._lpuser_secret.fget(dummy)

    assert result is None


def test_lpuser_lp_oauthkey_property_returns_none_when_key_missing_from_secret():
    dummy = SimpleNamespace()
    fake_secret = MagicMock()
    fake_secret.get_content.return_value = {}
    dummy._lpuser_secret = fake_secret

    result = UbuntuSponsoringCharm._lpuser_lp_oauthkey.fget(dummy)

    assert result is None
