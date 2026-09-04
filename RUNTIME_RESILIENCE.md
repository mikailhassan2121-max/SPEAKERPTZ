# SPEAKERPTZ v0.9 runtime resilience

v0.9 adds bounded recovery and crash-safe operations without changing the v0.8 dashboard, v0.7 detector, or v0.6 camera safety boundary.

## Runtime behavior

- The startup doctor validates Python, configuration, audio availability, writable logs, dashboard scope, and effective camera mode.
- A cross-platform file lock rejects a second controller process.
- Runtime state is written atomically to `logs/runtime-state.json` with a periodic heartbeat. Persistent state never restores AUTO or camera authority.
- Audio dropouts and camera disconnects disable AUTO and latch emergency STOP. Reconnect attempts are paced and bounded, and recovery never silently re-arms AUTO.
- Signal, console, and runtime-loop shutdown paths stop audio, request camera STOP, disconnect devices, stop the dashboard, record clean state, and release the instance lock on a best-effort basis.
- Event logs contain one UTF-8 JSON object per line and rotate at 2 MB with five backups. Raw microphone audio is not logged.

Legacy configuration files without `config_version` are interpreted as schema 1. Unknown or malformed schema versions are rejected. These optional values show the v0.9 defaults:

```yaml
config_version: 1

runtime:
  audio_reconnect_attempts: 3
  audio_reconnect_interval_seconds: 2.0
  health_check_seconds: 1.0
  heartbeat_seconds: 5.0
  instance_lock_file: logs/speakerptz.lock
  state_file: logs/runtime-state.json

camera_control:
  reconnect_interval_seconds: 2.0
  reconnect_attempt_limit: 3
```

## Verification

Run the hardware-free suite before deployment:

```powershell
.\run_tests.bat
.\run_soak_test.bat
.\doctor_school.bat
```

The soak test runs 25,000 deterministic synthetic frames (about 2-3 seconds) covering handoffs, silence, overlap, audio dropout, camera failure, and emergency-stop invariants. Pass `--soak-iterations` to `speakerptz.main --soak-test` to run a different count, for example the original 5,000-frame run.

## Optional Windows sign-in start

Validate the launcher manually first:

```powershell
.\doctor_school.bat
.\start_speakerptz.bat
```

Then preview and install a current-user, at-logon scheduled task from a normal PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows_autostart.ps1 -WhatIf
.\install_windows_autostart.ps1
```

The task runs only after that user signs in, ignores duplicate launches, and performs the startup doctor first. It does not edit configuration or enable real camera transmission. Real-camera mode always launches with AUTO off.

Remove the task with:

```powershell
.\install_windows_autostart.ps1 -Remove
```

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | Clean completion or passing soak test |
| 1 | Other controlled/runtime failure |
| 2 | Configuration/schema failure |
| 3 | Audio device or channel-identifier failure |
| 4 | Camera configuration, probe, or test failure |
| 5 | Dashboard startup failure |
| 6 | Another SPEAKERPTZ instance holds the lock |
| 7 | Soak-test invariant failure |
| 10–11 | Windows launcher is missing its Python environment or local configuration |
