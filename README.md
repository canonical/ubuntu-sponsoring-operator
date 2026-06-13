# Ubuntu Sponsoring Operator

**Ubuntu Sponsoring Operator** is a [charm](https://juju.is/charms-architecture)
that generates the [Ubuntu sponsoring report](http://sponsoring-reports.ubuntu.com/)
on a schedule and publishes the generated static reports on an HTTP endpoint.

The report generator is a Python batch job that queries the Launchpad API and
writes static HTML/JSON files. This charm checks out the source from Launchpad,
runs it on a systemd timer as the `ubuntu` user, and serves the generated
reports with nginx.

## Behavior

- Source is checked out from `https://git.launchpad.net/ubuntu-sponsoring`
  and refreshed on start and on configuration changes.
- Scheduled report generation every `sync_interval` minutes (default 15) via
  `sponsoring.timer`.
- Generated reports are published at `http://<unit-ip>/`.
- Manual trigger action `sync-now`.
- Falls back to an anonymous Launchpad login automatically when no credentials
  are configured.

## Basic usage

```bash
juju deploy ubuntu-sponsoring
```

The charm runs as the `ubuntu` user and serves reports on port 80.

On first start up, the charm installs dependencies, checks out the source, and
installs a systemd timer to regenerate the report on a regular basis.

Configure the Launchpad credentials secret for authenticated runs:

```bash
juju add-secret lpuser_secret_id lpoauthkey#file=/path/to/sponsoring.credentials
# returns secret:<uuid>
juju grant-secret lpuser_secret_id ubuntu-sponsoring
juju config ubuntu-sponsoring lpuser_secret_id=secret:<uuid>
```

Without a credentials secret the report is generated using an anonymous
Launchpad login.

Change the regeneration interval (in minutes, e.g. 60 for hourly):

```bash
juju config ubuntu-sponsoring sync_interval=60
```

Trigger a manual run:

```bash
juju run ubuntu-sponsoring/0 sync-now
```

## Service inspection

```bash
systemctl list-timers --all sponsoring.timer
systemctl status sponsoring.service
journalctl -u sponsoring.service
```

## Testing

For information on tests and development workflows, see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Ubuntu Sponsoring Operator is released under the [GPL-3.0 license](LICENSE).
