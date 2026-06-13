# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Representation of the Ubuntu sponsoring report generator and published reports."""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from charmlibs import apt, pathops, systemd
from charmlibs.apt import PackageError, PackageNotFoundError

logger = logging.getLogger(__name__)

PACKAGES = [
    "git",
    "nginx-light",
    "python3-bs4",
    "python3-cachetools",
    "python3-launchpadlib",
    "python3-lxml",
]

SERVICE_USER = "ubuntu"
SERVICE_HOME = "/srv/sponsoring"
CHECKOUT_DIR = Path("/srv/sponsoring/checkout")
REPORTS_DIR = Path("/srv/sponsoring/www")
CRED_DIR = Path("/home/ubuntu/.config/ubuntu-sponsoring")
CRED_PATH = CRED_DIR / "sponsoring.credentials"
CACHE_DIR = Path("/home/ubuntu/.cache")

SRV_DIRS = [
    (Path("/srv/sponsoring"), SERVICE_USER, SERVICE_USER),
    (REPORTS_DIR, SERVICE_USER, SERVICE_USER),
    (Path("/home/ubuntu/.config"), SERVICE_USER, SERVICE_USER),
    (CRED_DIR, SERVICE_USER, SERVICE_USER),
    (CACHE_DIR, SERVICE_USER, SERVICE_USER),
]

NGINX_SITE_CONFIG_PATH = Path("/etc/nginx/conf.d/sponsoring.conf")
SPONSORING_SERVICE = "sponsoring"
SPONSORING_RUNNER_PATH = Path("/usr/bin/run-sponsoring")

DEFAULT_SYNC_INTERVAL = 15
SOURCE_REPO = "https://git.launchpad.net/ubuntu-sponsoring"
SOURCE_REF = "main"


class Sponsoring:
    """Represent an instance generating and publishing the Ubuntu sponsoring report."""

    def __init__(self):
        logger.debug("Sponsoring class init")
        self.env = os.environ.copy()
        self.proxies = {}
        juju_http_proxy = self.env.get("JUJU_CHARM_HTTP_PROXY")
        juju_https_proxy = self.env.get("JUJU_CHARM_HTTPS_PROXY")
        if juju_http_proxy:
            logger.debug("Setting HTTP_PROXY env to %s", juju_http_proxy)
            self.env["HTTP_PROXY"] = juju_http_proxy
            self.proxies["http"] = juju_http_proxy
        if juju_https_proxy:
            logger.debug("Setting HTTPS_PROXY env to %s", juju_https_proxy)
            self.env["HTTPS_PROXY"] = juju_https_proxy
            self.proxies["https"] = juju_https_proxy

    def _install_packages(self):
        """Install required apt packages."""
        apt.update()
        logger.debug("Apt index refreshed.")

        for package in PACKAGES:
            try:
                apt.add_package(package)
                logger.debug("Package %s installed", package)
            except PackageNotFoundError:
                logger.error("Failed to find package %s in package cache", package)
                raise
            except PackageError as e:
                logger.error("Failed to install %s: %s", package, e)
                raise

    def install(self):
        """Set up environment required for report generation and publishing."""
        self._install_packages()

        for dir_path, dir_user, dir_group in SRV_DIRS:
            os.makedirs(dir_path, exist_ok=True)
            if dir_user is not None:
                shutil.chown(dir_path, dir_user, dir_group)

        shutil.copy("src/script/run-sponsoring", SPONSORING_RUNNER_PATH)
        shutil.copy("src/nginx/sponsoring.conf", NGINX_SITE_CONFIG_PATH)
        os.chmod(SPONSORING_RUNNER_PATH, 0o755)

        Path("/etc/nginx/sites-enabled/default").unlink(missing_ok=True)

    def update_source(self):
        """Clone or update the ubuntu-sponsoring checkout."""
        if not CHECKOUT_DIR.is_dir():
            logger.debug("Cloning %s (%s) into %s", SOURCE_REPO, SOURCE_REF, CHECKOUT_DIR)
            subprocess.run(
                ["git", "clone", "-b", SOURCE_REF, SOURCE_REPO, str(CHECKOUT_DIR)],
                check=True,
                env=self.env,
                capture_output=True,
                text=True,
            )
        else:
            logger.debug("Updating existing checkout in %s", CHECKOUT_DIR)
            subprocess.run(
                ["git", "pull"],
                cwd=str(CHECKOUT_DIR),
                check=True,
                env=self.env,
                capture_output=True,
                text=True,
            )

    def start(self):
        """Restart nginx to serve the generated reports."""
        systemd.service_restart("nginx")

    def trigger_run(self):
        """Trigger an asynchronous report generation run."""
        systemd.service_start(f"{SPONSORING_SERVICE}.service", "--no-block")

    def configure_url(self, url: str):
        """URL is defined externally - this is a no-op for now."""
        logger.debug("configure_url: The url in use is %s", url)

    def configure_credentials(self, cred_data: str) -> bool:
        """Create or refresh the Launchpad credentials file."""
        cred_file = pathops.LocalPath(CRED_PATH)
        os.makedirs(cred_file.parent, exist_ok=True)

        success = False
        try:
            cred_file.write_text(
                cred_data,
                mode=0o600,
                user=SERVICE_USER,
                group=SERVICE_USER,
            )
            success = True
        except (FileNotFoundError, NotADirectoryError) as e:
            logger.error("Failed to write credentials due to directory issues: %s", str(e))
        except LookupError as e:
            logger.error("Failed to write credentials due to issues with the user: %s", str(e))
        except PermissionError as e:
            logger.error("Failed to write credentials due to permission issues: %s", str(e))
        logger.debug(
            "configure_credentials: credentials write success=%s (length %d) to %s",
            success,
            len(cred_data),
            cred_file,
        )
        return success

    def clear_credentials(self):
        """Remove the Launchpad credentials file so the report runs anonymously."""
        CRED_PATH.unlink(missing_ok=True)

    def configure_run(self):
        """Write the run wrapper, using anonymous login when no credentials are present."""
        args = "" if CRED_PATH.exists() else "--anon"

        template = Path("src/script/run-sponsoring").read_text(encoding="utf-8")
        script = template.replace("__SPONSORING_ARGS__", args)
        SPONSORING_RUNNER_PATH.write_text(script, encoding="utf-8")
        os.chmod(SPONSORING_RUNNER_PATH, 0o755)

    def _validate_interval(self, interval: int) -> str:
        """Validate the sync interval in minutes and return a systemd time span."""
        minutes = int(interval)
        if minutes <= 0:
            raise ValueError(f"invalid sync interval: {interval!r}")
        return f"{minutes}min"

    def configure_schedule(self, sync_interval: int):
        """Write the timer unit from the configured interval and restart the timer."""
        interval = self._validate_interval(sync_interval)

        template = Path(f"src/systemd/{SPONSORING_SERVICE}.timer").read_text(encoding="utf-8")
        timer_content = template.replace("__SYNC_INTERVAL__", interval)

        timer_path = Path(f"/etc/systemd/system/{SPONSORING_SERVICE}.timer")
        timer_path.write_text(timer_content, encoding="utf-8")
        systemd.daemon_reload()
        systemd.service_restart(f"{SPONSORING_SERVICE}.timer")

    def run_sync(self):
        """Trigger a blocking execution of the report generation service."""
        systemd.service_start(f"{SPONSORING_SERVICE}.service")

    def setup_systemd_unit(self):
        """Set up the sponsoring service and timer with proxy configuration."""
        systemd_unit_location = Path("/etc/systemd/system")
        systemd_unit_location.mkdir(parents=True, exist_ok=True)

        service_content = Path(f"src/systemd/{SPONSORING_SERVICE}.service").read_text(
            encoding="utf-8"
        )
        timer_content = Path(f"src/systemd/{SPONSORING_SERVICE}.timer").read_text(encoding="utf-8")
        timer_content = timer_content.replace(
            "__SYNC_INTERVAL__", self._validate_interval(DEFAULT_SYNC_INTERVAL)
        )

        proxy_env_vars = ""
        if "http" in self.proxies:
            proxy_env_vars += "\nEnvironment=HTTP_PROXY=" + self.proxies["http"]
        if "https" in self.proxies:
            proxy_env_vars += "\nEnvironment=HTTPS_PROXY=" + self.proxies["https"]

        service_content += proxy_env_vars
        (systemd_unit_location / f"{SPONSORING_SERVICE}.service").write_text(
            service_content, encoding="utf-8"
        )
        (systemd_unit_location / f"{SPONSORING_SERVICE}.timer").write_text(
            timer_content, encoding="utf-8"
        )

        systemd.daemon_reload()
        systemd.service_enable(f"{SPONSORING_SERVICE}.timer")
        systemd.service_restart(f"{SPONSORING_SERVICE}.timer")

    def setup_systemd_units(self):
        """Set up the sponsoring service and timer."""
        self.setup_systemd_unit()
