# Release 3.7.5-rc.1 verification — 2026-11-01

Official repository: https://github.com/salenko93-hash/OrangePi
PR #1 re-audited and merged as `5e0bfaf8442c220027c7e5f99e3aaa86bbec73b0`.
The previous checked head was `c4de2141f9d1851ba6843a73cd9be94d6c10a34e`.
No unrelated hardware changes or history deletion were included.

## New updater and installer audit

Only official GitHub Releases assets are accepted. GitHub asset digest, sidecar,
ZIP bytes and each manifest member must agree. Redirects cannot downgrade HTTPS
or leave known GitHub asset hosts. ZIP traversal, symlinks, case aliases, duplicate
and unlisted members, live/private data and key material are rejected before
extraction. No private signing key is created or published. The independent
root-owned Ed25519 trust-key check remains for legacy signed official manifests.

Checking never installs. Applying requires the exact approved numeric version,
an explicit tag and a valid Linux supervisor belonging to the installation.
Same/older versions and concurrent pending transactions are rejected. Prereleases
require explicit opt-in. A private data/media backup is fully read/CRC-checked
and SHA-256 recorded before the existing worker snapshots/applies code.
Configuration, live schedules and media remain outside the code transaction.
Three health results are required; automatic rollback behavior is retained.
Manual rollback also backs up local data and checks the restored service version.
An actual temporary Linux launcher/app fixture passed update and manual rollback
with local config, media and schedules byte-preserved.

The PowerShell default is check only. Authenticated SSH transports a read-only
board/OS/architecture/dependency/storage/ownership preflight. Installation needs
explicit approval, transfers only the official verified ZIP and rehashes it.
Fresh installs use an empty destination; existing installs use transactions.
The legacy Windows entry point delegates to this mechanism; native full install
refuses existing/partial live config instead of recursively repairing live data.
PowerShell syntax was parsed without executing SSH or contacting any board.

## Local mandatory verification

| Environment | PASS | FAIL/ERROR | SKIP |
| --- | ---: | ---: | ---: |
| Windows Python 3.15.1 | 107 | 0 | 19 |
| Ubuntu WSL Python 3.14.4 | 123 | 0 | 3 |

Ruff 0.14.2 passed for server/scripts/tests/tools/launcher/VERIFY. All shell scripts
passed bash -n. Windows Node checked all 16 JS files and all 8 runtime scenarios.
Ubuntu has no Node; JS checks were performed on Windows. CI supplies Node on both
runners; its actual result is recorded on GitHub and in the release notes.
GitHub Actions was absent before this task; the new workflow has read-only
contents permissions and tests both Windows and Ubuntu under Python 3.12.
A separate tag-triggered prerelease workflow reuses that verification, then grants
contents:write only to its publication job through the ephemeral GitHub job token.
It requires main ancestry and a matching rc tag, builds twice, compares bytes,
checks every ZIP hash against the committed tree and publishes ZIP/checksum only
after success. It never contacts a board or deploys automatically.

The first GitHub Windows runner exposed CP1252 stdout/default-file encoding;
VERIFY stopped on a Ukrainian source name before tests. The workflow explicitly
sets PYTHONUTF8=1 for consistent cross-platform source and console encoding.
The Ubuntu job of that initial run passed. Subsequent actual CI results are
reported on GitHub; the initial failure is not counted as a successful run.

## All local SKIP reasons

### Windows Python 3.15.1

- `test_real_child_verifies_no_new_privs_and_zero_capability_sets_without_gi`: unprivileged Linux child
- `test_native_theme_lookup_decodes_transparent_pixel`: native libXcursor unavailable
- `test_native_wlroots_default_lookup_and_previous_failure`: optional native wlroots 0.18 library unavailable
- `test_native_probe_reports_transparent_pixels_without_a_display`: optional native wlroots fixture
- `test_custom_calendar_is_preserved_after_permissions_repair`: requires a normal POSIX user and bash to exercise permission failures
- `test_fresh_install_creates_writable_runtime_storage`: requires a normal POSIX user and bash to exercise permission failures
- `test_read_only_upgrade_preserves_config_media_and_live_schedules`: requires a normal POSIX user and bash to exercise permission failures
- `test_fresh_setup_and_upgrade_make_every_parent_private_and_writable`: POSIX directory descriptor operations
- `test_linked_home_is_rejected`: POSIX directory descriptor operations
- `test_linked_parent_is_rejected_without_changing_its_external_target`: POSIX directory descriptor operations
- `test_standalone_repair_contains_the_same_safe_profile_preparation`: POSIX directory descriptor operations
- `test_first_process_launch_and_conflicting_inherited_cursor_settings`: requires unprivileged Linux/bash for real filesystem access failures
- `test_missing_runtime_fails_before_compositor_starts`: requires unprivileged Linux/bash for real filesystem access failures
- `test_private_writable_runtime_starts_compositor_without_leaving_probe`: requires unprivileged Linux/bash for real filesystem access failures
- `test_read_only_runtime_has_clear_error_instead_of_cage_abort`: requires unprivileged Linux/bash for real filesystem access failures
- `test_shared_runtime_is_rejected`: requires unprivileged Linux/bash for real filesystem access failures
- `test_backup_failure_prevents_prepare_and_success_uses_existing_worker`: POSIX supervisor ownership check
- `test_real_official_update_and_manual_rollback_preserve_local_data`: POSIX supervised end-to-end update
- `test_release_signature_rejects_tamper_unsigned_wrong_key`: requires OpenSSL Ed25519

### Ubuntu WSL Python 3.14.4

- `test_native_wlroots_default_lookup_and_previous_failure`: optional native wlroots 0.18 library unavailable
- `test_native_probe_reports_transparent_pixels_without_a_display`: optional native wlroots fixture
- `test_supervisor_tree_cleanup_on_exit_error_and_timeout`: Windows process-tree cleanup

No failing test was converted into a skip. POSIX-supervisor tests execute on Linux;
Windows-specific process-tree cleanup executes on Windows. Native wlroots fixtures
remain unavailable locally. No physical device, actual ARM32 syscall/driver,
HDMI/audio/cursor acceptance, full apt install, real SSH deployment or browser
end-to-end hardware session was performed. These remain prerelease limitations.

## Reproducible artifacts and operator commands

The release generator runs only after mandatory checks pass and reruns VERIFY.
The ZIP uses deterministic paths/timestamps/modes, contains its generated
PACKAGE_SHA256.json, and has a .sha256 sidecar. No hashes are edited by hand.
The artifact is rebuilt from the final merged main and compared to its Git tree.
The release is tagged v3.7.5-rc.1 and published as a prerelease only after checks.

See docs/GITHUB_RELEASE_UPDATES.md for exact check/install/status/rollback
commands and data-recovery boundaries. No board is updated during this task.
Release-asset HTTPS authenticates the GitHub account, not physical hardware or
an independent signing authority. Keep private backups and local logs off GitHub.
