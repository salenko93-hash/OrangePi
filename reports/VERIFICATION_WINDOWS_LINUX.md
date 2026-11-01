# Windows and Linux verification — 2026-11-01

Repository: https://github.com/salenko93-hash/OrangePi
Base: `238273ce7c5ede9e37ac2324fa84343720fcf6ef` (`origin/main`).

## Root causes and changes

The rollback worker used `os.kill(pid, 0)` as a POSIX liveness probe on Windows.
This has different Windows signal semantics and interfered with the running
process tree. Reproduction remained in `rolling_back` before file restoration.
Windows now waits for the supervisor's PID-marker acknowledgement. The POSIX
probe, state transitions, transaction locks and timeout remain unchanged.
The existing local `r+b` fsync fix is preserved; it allows Windows to flush the
staged file through a writable descriptor before atomic replacement.

The watchdog test found System32/bash.exe, which targets the default WSL distro.
That distro was docker-desktop without /bin/bash; Ubuntu worked when selected
explicitly. The Windows fixture now uses Git Bash with quoted forward-slash paths
and bounded subprocess timeouts. The production watchdog is unchanged.

Windows supervisor tests use a Job Object joined before launcher code runs.
Cleanup terminates only that job, waits for its active process count to reach
zero, and closes its handle. Success, exception, timeout and an already-exited
launcher are tested, including removal of the temporary directory.

POSIX cursor modes remain strict (0755/0644). Windows verifies files and content.
Recovery tests cover successful rollback, failed restoration, recovery_required,
a blocked competing update, retry from the same snapshot, and preservation of
local configuration/media. No update was installed on a device.

The official main branch contains newer diagnostic tests than the unpacked local
copy. Their missing Windows geteuid/pwd dependencies are isolated in test mocks;
parser tests use a synthetic UID. Production display/cursor code is unchanged.

A fresh Git checkout exposed a separate CRLF/SHA-256 mismatch in canonical JSON.
.gitattributes enforces LF without changing canonical data or their hashes.
Only task-related files are carried into the branch; newer main files and history
are preserved. Other local hardware/document changes are not overwritten or
published by this PR.

## Final verification of the PR source tree

| Environment | PASS | FAIL / ERROR | SKIP |
| --- | ---: | ---: | ---: |
| Windows | 101 | 0 | 17 |
| Ubuntu WSL | 115 | 0 | 3 |

Both complete VERIFY_PROJECT.py runs succeeded. Windows: Python 3.15.1;
Ubuntu WSL: Python 3.14.4, unprivileged UID 1000. Linux installation-storage,
permission, kiosk-runtime and browser-privilege checks passed. All shipped shell
scripts passed bash -n. These are x86_64 WSL results, not physical ARM hardware.

Ruff 0.14.2: all checks passed for server, scripts, tests, tools, launcher.py and
VERIFY_PROJECT.py. Windows Node 24 checked all 16 JavaScript files and passed all
8 slideshow runtime regressions. Node is absent in Ubuntu; its optional JS stage
was not executed there. JavaScript coverage comes from the Windows run.

## Every skipped test and its reason

### Windows

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
- `test_release_signature_rejects_tamper_unsigned_wrong_key`: requires OpenSSL Ed25519

### Ubuntu WSL

- `test_native_wlroots_default_lookup_and_previous_failure`: optional native wlroots 0.18 library unavailable
- `test_native_probe_reports_transparent_pixels_without_a_display`: optional native wlroots fixture
- `test_supervisor_tree_cleanup_on_exit_error_and_timeout`: Windows process-tree cleanup

No failing test was converted to a skip. Native wlroots checks require the
optional fixture/library; the Windows process-tree cleanup test runs on Windows.

## Release and privacy boundaries

The builder is run only after the mandatory verification above passed, and
reruns VERIFY itself. PACKAGE_SHA256.json is generated inside its ZIP and is
extracted unchanged for the source branch; no digest is hand edited. The builder
verifies archive CRC and every archived SHA-256, and writes a ZIP .sha256 sidecar.
The original unpacked tree has unrelated differences and an older manifest;
the authoritative release artifact is built from this isolated origin/main-based
branch, not by combining that manifest with a different source tree.

The release allowlist and a high-confidence credential-pattern scan passed.
Live data/config.json, uploaded media, diagnostic logs, signing/TLS key material,
local tooling and checkout metadata are excluded. This check is not a guarantee
about the contents of pre-existing public source workbooks. No new live/private
data or credentials are included in this change.

Physical Orange Pi cursor, HDMI, sound and an actual systemd deployment remain
hardware acceptance checks. No deployment, merge or force push is performed.
