# SPEAKERPTZ

Portable active-speaker PTZ controller for boardrooms, auditoriums, and meeting spaces.

## v0.6 — fail-safe camera-control framework

v0.6 adds a protocol-neutral multi-camera manager, documented VISCA-over-IP and standard ONVIF preset drivers, bounded connectivity checks, manual camera testing, command pacing, retries, health reporting, and a latched emergency stop.

### Safety boundary

- `real_control_enabled: false` is the committed default.
- When that gate is false, even a configured VISCA or ONVIF entry is replaced at runtime by a simulator; its network driver is not constructed.
- When the gate is true, AUTO still starts off on every launch and must be armed manually with `A`.
- `camera_probe.bat` checks only Camera 1's configured IP. It does not scan a subnet.
- `camera_test.bat` requires both the real-control opt-in and an exact typed confirmation before movement.
- `X` disables AUTO and latches emergency STOP. `R` clears the latch but leaves AUTO off.
- A stale audio callback disables AUTO and latches camera STOP.
- Camera credentials are read only from the named environment variable. Plaintext `password` fields are rejected.

This release is camera-framework complete but **not field-validated** against the school's unknown PTZ model. Confirm its exact protocol and preset numbering before enabling real control.

## Camera configuration

The committed example remains safe:

```yaml
real_control_enabled: false

camera_control:
  command_interval_seconds: 0.10
  movement_cooldown_seconds: 0.75
  retry_count: 1
  retry_backoff_seconds: 0.10

cameras:
  - id: 1
    name: Camera 1
    driver: simulator       # visca or onvif only after model confirmation
    host: null
    port: null              # VISCA default 52381; ONVIF default 80
    username: null
    password_env: null
    profile_token: null
    timeout_seconds: 1.0
    enabled: true
```

For ONVIF, put only an environment-variable name in YAML, such as `password_env: SPEAKERPTZ_CAMERA_1_PASSWORD`, then set its value locally in Windows. Never commit the value.

After configuring the exact camera while no meeting is in progress:

```powershell
doctor_school.bat
camera_probe.bat
camera_test.bat
```

`camera_probe.bat` performs a read-only camera check. The manual tester supports `P <preset>`, `W`, `H`, `S`, and `Q` after confirmation.

## Important Dante model

SPEAKERPTZ does **not** implement the Dante network protocol itself. Dante Virtual Soundcard (DVS) presents subscribed Dante channels to Windows as a multichannel audio interface; SPEAKERPTZ opens that Windows audio interface. Dante subscriptions and clocking remain managed separately in the existing Dante environment.

## School computer workflow

After cloning the repository:

```powershell
setup_school_windows.bat
doctor_school.bat
```

Edit `config/local.yaml` for the actual machine. A typical starting point is:

```yaml
runtime:
  mode: real
  device_name: "Dante Virtual Soundcard"
  device_index: null
  hostapi_name: null

audio:
  sample_rate: 48000
  channels: 8
  channel_map: [1, 2, 3, 4, 5, 6, 7, 8]
  identifier_channels: 8
```

If the board microphones are not on consecutive DVS inputs, use a sparse map. For example:

```yaml
audio:
  channels: 4
  channel_map: [5, 6, 9, 10]
```

That means:

```text
SPEAKERPTZ MIC 1 <- physical DVS input 5
SPEAKERPTZ MIC 2 <- physical DVS input 6
SPEAKERPTZ MIC 3 <- physical DVS input 9
SPEAKERPTZ MIC 4 <- physical DVS input 10
```

## Discover the board mic channels

After `doctor_school.bat` passes, run:

```powershell
identify_dante_channels.bat
```

Speak into **one board microphone at a time** and note which `PHYS ##` meter peaks. Then put those physical input numbers into `audio.channel_map` in `config/local.yaml`.

This identifier does not modify Dante routing and does not send any PTZ commands.

## Safe dry run

```powershell
run_school_dry_run.bat
```

The dry run can receive real multichannel audio and generate simulated camera preset requests. It cannot transmit real camera commands.

## Operator hotkeys

- `A` — auto director on/off
- `W` — wide-shot request
- `1` through `9` — manual logical mic/seat preset request and auto off
- `Q` — quit

## Logs and privacy

Each run writes event-only logs to `logs/speakerptz-YYYYMMDD.log`. Logs include startup/shutdown, active-speaker handoffs, manual overrides, and audio-health events. **SPEAKERPTZ does not record or save raw microphone audio.**

## Development

```powershell
setup_windows.bat
run_simulation.bat
run_tests.bat
```
