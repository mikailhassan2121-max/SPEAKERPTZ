# SPEAKERPTZ

Portable active-speaker PTZ controller for boardrooms, auditoriums, and meeting spaces.

## v0.8 — local operator dashboard

v0.8 adds a dependency-free operator dashboard at `http://127.0.0.1:8765` while leaving camera authority in the existing main control loop.

```powershell
run_operator_dashboard.bat
```

The dashboard shows AUTO state, active and candidate speakers, confidence, detector reasons, mic/VAD meters, noise floors, audio and Dante/DVS status, camera health, current preset, recent events, uptime, and warnings. It provides AUTO, WIDE, emergency stop/reset, and manual camera/preset controls.

Safety properties:

- The HTTP thread can only queue allowlisted commands. Camera drivers are called only by the main loop.
- The page displays either `SIMULATION / DRY RUN` or a pulsing red `REAL PTZ CONTROL ENABLED` banner.
- Real-mode movement controls require an additional browser confirmation.
- State may be viewed without a token, but every command requires a random per-launch control token embedded only in the same-origin page.
- No permissive CORS headers are emitted.
- The committed host is `127.0.0.1`. A non-loopback host fails configuration validation unless `allow_remote: true` is explicitly set.
- `--no-dashboard` disables the server for console-only operation. `--dashboard-port` can resolve a local port conflict without editing the config.

The dashboard is an operator surface, not a replacement for console hotkeys, event logs, startup checks, emergency-stop logic, or audio/camera fail-safes.

## v0.7 speech detection retained

The v0.7 engine adds local speech/non-speech analysis, confidence smoothing, transient rejection, overlap handling, adaptive noise floors, channel normalization, configurable bleed relationships, disabled-channel support, and operator-facing diagnostic reasons.

### Speech detection model

- Raw audio is analyzed only in memory. It is never queued outside the audio callback, recorded, transcribed, or sent to a cloud service.
- VAD combines energy, zero-crossing rate, speech-band energy, and spectral shape. It does not identify who a voice belongs to; routing still comes only from the configured isolated mic channel.
- A channel must pass both its normalized signal-above-noise gate and the VAD confidence gate.
- Brief impacts and cough-like bursts must survive `transient_rejection_ms` before an initial camera selection.
- Similar simultaneous candidates are treated as ambiguous overlap. The current speaker is held when possible; otherwise no camera move is requested.
- `bleed_pairs` describes known neighboring microphones. If one is clearly stronger, the weaker paired channel is rejected as bleed.
- Adaptive floors follow slow room/HVAC changes only while a channel is not classified as speech.
- Diagnostic reason strings explain why the detector selected, held, rejected, or delayed a channel.

Recommended starting settings are committed in `config/room.yaml` and `config/local.example.yaml`:

```yaml
audio:
  vad_enabled: true
  vad_threshold: 0.55
  vad_weight: 0.45
  confidence_smoothing: 0.35
  transient_rejection_ms: 180
  overlap_margin_db: 2.0
  adaptive_noise_enabled: true
  adaptive_noise_alpha: 0.02
  noise_floor_min_db: -85.0
  noise_floor_max_db: -35.0
  disabled_channels: []
  level_offsets_db: [0.0, 0.0, 0.0, 0.0]
  bleed_pairs: []
  bleed_rejection_db: 6.0
```

Keep `bleed_pairs` empty until the actual room layout is observed. The pair numbers refer to logical SPEAKERPTZ mics after `channel_map`, not physical Dante input numbers.

## v0.6 camera framework retained

The protocol-neutral multi-camera manager, VISCA-over-IP and ONVIF drivers, bounded connectivity checks, manual tester, rate limiting, retries, health reporting, and latched emergency stop remain unchanged.

### Safety boundary

- `real_control_enabled: false` is the committed default.
- When that gate is false, even a configured VISCA or ONVIF entry is replaced at runtime by a simulator; its network driver is not constructed.
- When the gate is true, AUTO still starts off on every launch and must be armed manually with `A`.
- `camera_probe.bat` checks only Camera 1's configured IP. It does not scan a subnet.
- `camera_test.bat` requires both the real-control opt-in and an exact typed confirmation before movement.
- `X` disables AUTO and latches emergency STOP. `R` clears the latch but leaves AUTO off.
- A stale audio callback disables AUTO and latches camera STOP.
- Camera credentials are read only from the named environment variable. Plaintext `password` fields are rejected.

The camera framework is complete but **not field-validated** against the school's unknown PTZ model. Confirm its exact protocol and preset numbering before enabling real control.

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
