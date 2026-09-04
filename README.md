# SPEAKERPTZ

Portable active-speaker PTZ controller for boardrooms, auditoriums, and meeting spaces.

## v0.5 — Dante Virtual Soundcard preparation

v0.5 keeps camera control **simulation-only** and strengthens the audio/deployment side for the dedicated school production PC.

### Added in v0.5

- physical Dante/DVS input -> logical SPEAKERPTZ mic mapping with `audio.channel_map`
- support for sparse maps such as `MIC 1 <- DVS 5`, `MIC 2 <- DVS 6`, `MIC 3 <- DVS 9`
- `identify_dante_channels.bat` live physical-input meter for finding which DVS channel belongs to each board microphone
- optional Windows host-API preference when several endpoints share the same device name
- improved startup doctor showing logical/physical channel requirements and host APIs
- live audio callback watchdog; auto-director disables itself if the audio stream goes stale
- audio recovery/stale events written to the normal local event log
- no raw audio recording
- real PTZ transmission is still disabled in this release

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
