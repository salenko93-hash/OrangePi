# Official Orange Pi releases and administrator-controlled updates

Only https://github.com/salenko93-hash/OrangePi is accepted. No update is installed
by checking a release. The first release is `v3.7.5-rc.1`, runtime version 3.7.5.
It is a prerelease: physical Orange Pi acceptance has not been performed.

## Windows installation or upgrade

Extract the official ZIP into a new folder. Use Python 3.10+ and Windows OpenSSH.
The example IP below is documentation-only; replace it with the board address.
The default action is check only. SSH host-key verification remains enabled.

```powershell
.\INSTALL_RELEASE_ORANGEPI.ps1 -BoardHost 192.0.2.10 -BoardUser admin -Tag v3.7.5-rc.1 -AllowPrerelease -CheckOnly
.\INSTALL_RELEASE_ORANGEPI.ps1 -BoardHost 192.0.2.10 -BoardUser admin -Tag v3.7.5-rc.1 -AllowPrerelease -ApproveVersion 3.7.5
```

The first command reads board/model, OS, architecture, dependencies, storage and
ownership through SSH; it does not stage remote files or change services. Failure
prints the failing condition. Missing fresh-install dependencies are resolved by
the native apt installer. Installed systems must already have dependencies and
correct ownership; no automatic recursive permission repair is attempted.

The second command is an explicit administrator installation request. It fetches
metadata from the fixed GitHub repository, requires the GitHub asset digest,
checks the .sha256 sidecar, hashes the ZIP, verifies every manifest member and
rechecks SHA-256 after SSH transfer. For a fresh empty installation it runs the
native Orange Pi installer and exact-version health check. For an existing
installation it invokes the service-owned transactional updater. It never copies
live config/media from Windows, recursively changes live permissions, or reboots.
The historical INSTALL_TO_ORANGEPI.ps1 delegates to this safer entry point.

The bootstrap refuses a partial/non-empty installation that needs manual review.
A fresh install has no prior local state to back up. Existing installations get
a verified private data/media backup and a code snapshot before any code update.

## Direct commands on an already installed Orange Pi

```bash
cd /opt/lyceumtv
sudo -u lyceumtv python3 scripts/github_update.py check
sudo -u lyceumtv python3 scripts/github_update.py check --tag v3.7.5-rc.1 --allow-prerelease
sudo -u lyceumtv python3 scripts/github_update.py apply --tag v3.7.5-rc.1 --allow-prerelease --approve 3.7.5
sudo -u lyceumtv python3 scripts/github_update.py status
```

Stable checks use GitHub Releases/latest. Until a stable release is published,
that command reports no stable release/HTTP 404; preview checks require the
explicit flag. Checking records a journal entry but never installs. Reapplying
the installed version or downgrading via apply is rejected, including UI force
requests. The admin UI uses stable official Releases when ota_manifest_url is
empty. Legacy signed manifests remain supported only as official repository
release assets with the operator-installed root-owned Ed25519 public key.

The supervisor independently requires three consecutive exact-version health
responses, otherwise restores the code snapshot. Local config, current schedules,
overrides and uploaded media are outside the code transaction and are preserved.
Do not replace a valid local config to enable this feature.

## Manual rollback and recovery

```bash
cd /opt/lyceumtv
sudo -u lyceumtv python3 scripts/github_update.py rollback --approve rollback
sudo -u lyceumtv python3 scripts/github_update.py status
sudo journalctl -u lyceumtv -n 80 --no-pager
```

Manual rollback first verifies a new local-data backup, then queues the most
recent retained code snapshot and waits for the supervisor. It restores code,
not local schedules or media. An in-progress or recovery_required transaction
blocks another update/rollback; inspect data/ota_pending and its matching
update_jobs/<job>/result.json. The supervisor retries interrupted recovery from
the retained snapshot. A timeout leaves that state intact and must not be treated
as permission to queue another update.

Private verified data/media backups live in data/backups/pre-github-*.tar.gz.
The returned JSON/journal includes SHA-256; do not publish these private archives.
Code snapshots live in data/update_jobs. Journals: data/logs/github-updates.jsonl,
data/logs/events.jsonl, and systemd journal. Run commands as lyceumtv so newly
created runtime files have the correct owner. No cron or timer auto-installs code.

## Trust and acceptance limits

Release origin is authenticated by HTTPS to the fixed GitHub repository; the
GitHub digest, checksum sidecar, ZIP bytes and all manifest files must agree.
This trusts the official GitHub account/TLS, not an independent hardware-attested
signature. Private signing keys are neither created nor shipped by these tools.
The existing signed-manifest route still requires its independent trust key.

CI and WSL cannot establish actual HDMI/audio/cursor or systemd device behavior.
Perform those physical acceptance checks before calling a release production-ready.
No physical board was accessed or changed during preparation of this release.
