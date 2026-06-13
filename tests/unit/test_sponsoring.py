# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Unit tests for `src/sponsoring.py`."""

from subprocess import CalledProcessError
from unittest.mock import Mock

import pytest

import sponsoring
from sponsoring import Sponsoring


def test_install_packages_calls_apt_update_before_adding_packages(monkeypatch):
    called = []

    monkeypatch.setattr(sponsoring.apt, "update", lambda: called.append("update"))
    monkeypatch.setattr(sponsoring.apt, "add_package", lambda pkg: called.append(pkg))
    worker = Sponsoring()

    worker._install_packages()

    assert called[0] == "update"
    assert set(called[1:]) == set(sponsoring.PACKAGES)


def test_install_creates_directories_and_copies_files(monkeypatch):
    monkeypatch.setattr(Sponsoring, "_install_packages", lambda self: None)

    ops = []

    def record_makedirs(dir_path, exist_ok=True):
        ops.append(("makedirs", dir_path))

    def record_chmod(path, mode):
        ops.append(("chmod", str(path)))

    monkeypatch.setattr(sponsoring.os, "makedirs", record_makedirs)
    monkeypatch.setattr(
        sponsoring.shutil, "chown", lambda path, u, g: ops.append(("chown", path, u, g))
    )
    monkeypatch.setattr(sponsoring.shutil, "copy", lambda src, dst: ops.append(("copy", src, dst)))
    monkeypatch.setattr(sponsoring.Path, "unlink", lambda self, missing_ok=True: None)
    monkeypatch.setattr(sponsoring.os, "chmod", record_chmod)

    worker = Sponsoring()
    worker.install()

    assert ("copy", "src/script/run-sponsoring", sponsoring.SPONSORING_RUNNER_PATH) in ops
    assert ("copy", "src/nginx/sponsoring.conf", sponsoring.NGINX_SITE_CONFIG_PATH) in ops
    assert ("makedirs", sponsoring.REPORTS_DIR) in ops


def test_update_source_clones_when_no_checkout(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sponsoring.subprocess,
        "run",
        lambda cmd, **kwargs: calls.append((cmd, kwargs.get("cwd"))),
    )
    monkeypatch.setattr(sponsoring.Path, "is_dir", lambda self: False)

    worker = Sponsoring()
    worker.update_source()

    checkout = str(sponsoring.CHECKOUT_DIR)
    assert calls == [
        (["git", "clone", "-b", sponsoring.SOURCE_REF, sponsoring.SOURCE_REPO, checkout], None)
    ]


def test_update_source_updates_existing_checkout(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sponsoring.subprocess,
        "run",
        lambda cmd, **kwargs: calls.append((cmd, kwargs.get("cwd"))),
    )
    monkeypatch.setattr(sponsoring.Path, "is_dir", lambda self: True)

    worker = Sponsoring()
    worker.update_source()

    checkout = str(sponsoring.CHECKOUT_DIR)
    assert calls == [(["git", "pull"], checkout)]


def test_start_restarts_nginx(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sponsoring.systemd,
        "service_restart",
        lambda *args: calls.append(("restart",) + args),
    )

    worker = Sponsoring()
    worker.start()

    assert ("restart", "nginx") in calls


def test_trigger_run_starts_service_async(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sponsoring.systemd,
        "service_start",
        lambda *args: calls.append(("start",) + args),
    )

    worker = Sponsoring()
    worker.trigger_run()

    assert ("start", "sponsoring.service", "--no-block") in calls


def test_run_sync_starts_service(monkeypatch):
    starts = []
    monkeypatch.setattr(sponsoring.systemd, "service_start", lambda *args: starts.append(args))

    worker = Sponsoring()
    worker.run_sync()

    assert ("sponsoring.service",) in starts


def test_configure_run_uses_anon_when_no_credentials(monkeypatch):
    monkeypatch.setattr(
        sponsoring.Path,
        "read_text",
        lambda self, encoding=None: "#!/bin/sh\nexec python3 -m foo __SPONSORING_ARGS__\n",
    )
    monkeypatch.setattr(sponsoring.Path, "exists", lambda self: False)

    written = {}

    def fake_write_text(self, text, encoding=None):
        written[str(self)] = text

    monkeypatch.setattr(sponsoring.Path, "write_text", fake_write_text)
    monkeypatch.setattr(sponsoring.os, "chmod", lambda path, mode: None)

    worker = Sponsoring()
    worker.configure_run()

    path = str(sponsoring.SPONSORING_RUNNER_PATH)
    assert "--anon" in written[path]


def test_configure_run_authenticated_when_credentials_present(monkeypatch):
    monkeypatch.setattr(
        sponsoring.Path,
        "read_text",
        lambda self, encoding=None: "#!/bin/sh\nexec python3 -m foo __SPONSORING_ARGS__\n",
    )
    monkeypatch.setattr(sponsoring.Path, "exists", lambda self: True)

    written = {}

    def fake_write_text(self, text, encoding=None):
        written[str(self)] = text

    monkeypatch.setattr(sponsoring.Path, "write_text", fake_write_text)
    monkeypatch.setattr(sponsoring.os, "chmod", lambda path, mode: None)

    worker = Sponsoring()
    worker.configure_run()

    path = str(sponsoring.SPONSORING_RUNNER_PATH)
    assert "--anon" not in written[path]


def test_clear_credentials_removes_file(monkeypatch):
    unlinked = []
    monkeypatch.setattr(
        sponsoring.Path, "unlink", lambda self, missing_ok=False: unlinked.append(str(self))
    )

    worker = Sponsoring()
    worker.clear_credentials()

    assert str(sponsoring.CRED_PATH) in unlinked


def test_configure_credentials_writes_file(monkeypatch):
    monkeypatch.setattr(sponsoring.os, "makedirs", lambda path, exist_ok=True: None)

    written = {}

    def fake_write_text(self, text, mode=None, user=None, group=None):
        written["path"] = str(self)
        written["text"] = text
        written["mode"] = mode
        written["user"] = user

    monkeypatch.setattr(sponsoring.pathops.LocalPath, "write_text", fake_write_text)

    worker = Sponsoring()
    result = worker.configure_credentials("secret-data")

    assert result is True
    assert written["text"] == "secret-data"
    assert written["mode"] == 0o600
    assert written["user"] == "ubuntu"


def test_configure_credentials_returns_false_on_permission_error(monkeypatch):
    monkeypatch.setattr(sponsoring.os, "makedirs", lambda path, exist_ok=True: None)

    def bad_write(self, text, mode=None, user=None, group=None):
        raise PermissionError("denied")

    monkeypatch.setattr(sponsoring.pathops.LocalPath, "write_text", bad_write)

    worker = Sponsoring()
    result = worker.configure_credentials("secret-data")

    assert result is False


def test_setup_systemd_unit_writes_service_and_timer_with_proxy_environment(monkeypatch):
    monkeypatch.setenv("JUJU_CHARM_HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("JUJU_CHARM_HTTPS_PROXY", "https://secure.example:8443")

    worker = Sponsoring()

    def fake_read_text(self, encoding=None):
        return "[Service]\nExecStart=/bin/true" if self.suffix == ".service" else "[Timer]"

    written = {}

    def fake_write_text(self, text, encoding=None):
        written[str(self)] = text

    monkeypatch.setattr(sponsoring.Path, "read_text", fake_read_text)
    monkeypatch.setattr(sponsoring.Path, "write_text", fake_write_text)
    monkeypatch.setattr(sponsoring.Path, "mkdir", lambda self, parents=False, exist_ok=False: None)
    monkeypatch.setattr(sponsoring.systemd, "service_enable", lambda *args, **kwargs: None)
    monkeypatch.setattr(sponsoring.systemd, "daemon_reload", lambda *args, **kwargs: None)
    monkeypatch.setattr(sponsoring.systemd, "service_restart", lambda *args, **kwargs: None)

    worker.setup_systemd_unit()

    svc_path = "/etc/systemd/system/sponsoring.service"
    assert svc_path in written
    assert "Environment=HTTP_PROXY=http://proxy.example:8080" in written[svc_path]
    assert "Environment=HTTPS_PROXY=https://secure.example:8443" in written[svc_path]


def test_configure_schedule_writes_timer_and_restarts_timer(monkeypatch):
    written = {}
    calls = []

    def fake_write_text(self, text, encoding=None):
        written[str(self)] = text

    monkeypatch.setattr(sponsoring.Path, "write_text", fake_write_text)
    monkeypatch.setattr(
        sponsoring.systemd,
        "daemon_reload",
        lambda *args: calls.append(("reload",) + args),
    )
    monkeypatch.setattr(
        sponsoring.systemd, "service_restart", lambda *args: calls.append(("restart",) + args)
    )

    worker = Sponsoring()
    worker.configure_schedule(30)

    timer_path = "/etc/systemd/system/sponsoring.timer"
    assert timer_path in written
    assert "OnUnitActiveSec=30min" in written[timer_path]
    assert ("reload",) in calls
    assert ("restart", "sponsoring.timer") in calls


def test_configure_schedule_raises_for_zero_interval():
    worker = Sponsoring()

    with pytest.raises(ValueError):
        worker.configure_schedule(0)


def test_configure_schedule_raises_for_negative_interval():
    worker = Sponsoring()

    with pytest.raises(ValueError):
        worker.configure_schedule(-5)


def test_install_packages_raises_when_package_not_found(monkeypatch):
    monkeypatch.setattr(sponsoring.apt, "update", lambda: None)

    def bad_add(_):
        raise sponsoring.PackageNotFoundError("missing")

    monkeypatch.setattr(sponsoring.apt, "add_package", bad_add)
    worker = Sponsoring()

    with pytest.raises(sponsoring.PackageNotFoundError):
        worker._install_packages()


def test_install_packages_raises_when_package_installation_fails(monkeypatch):
    monkeypatch.setattr(sponsoring.apt, "update", lambda: None)

    def bad_add(_):
        raise sponsoring.PackageError("install failed")

    monkeypatch.setattr(sponsoring.apt, "add_package", bad_add)
    worker = Sponsoring()

    with pytest.raises(sponsoring.PackageError):
        worker._install_packages()


def test_start_raises_when_systemd_start_fails(monkeypatch):
    monkeypatch.setattr(
        sponsoring.systemd,
        "service_restart",
        Mock(side_effect=CalledProcessError(1, "systemctl")),
    )

    worker = Sponsoring()

    with pytest.raises(CalledProcessError):
        worker.start()
