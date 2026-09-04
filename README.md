# SPEAKERPTZ

Portable active-speaker PTZ controller for boardrooms, auditoriums, and meeting spaces.

## v0.4 development branch

v0.4 focuses on making the proven v0.3 detector easy and safe to deploy on a dedicated school production PC.

### Added in v0.4

- per-computer `config/local.yaml` that is intentionally **not committed to Git**
- audio-device selection by stable **device-name substring** as well as numeric index
- `doctor_school.bat` startup self-test before a meeting
- rotating local event logs under `logs/`
- safer one-click school setup and dry-run launchers
- validation for duplicate/out-of-range mic mappings
- camera driver remains **simulator-only**; this branch cannot control a real PTZ yet

## Development quick start

```powershell
setup_windows.bat
run_simulation.bat
run_tests.bat
```

## School computer install

After cloning the repository on the dedicated production computer:

```powershell
setup_school_windows.bat
```

That creates `.venv`, installs dependencies, and creates `config/local.yaml` from `config/local.example.yaml` if a local file does not already exist.

Edit `config/local.yaml` for the real installation. For a Dante Virtual Soundcard installation, the intended starting point is:

```yaml
runtime:
  mode: real
  device_name: "Dante Virtual Soundcard"
```

Then run:

```powershell
doctor_school.bat
```

Only after the doctor passes should you start:

```powershell
run_school_dry_run.bat
```

The school launcher still uses the **simulated camera driver**. It can receive real multichannel audio and generate camera requests in software, but it cannot transmit real camera commands yet.

## Operator hotkeys

- `A` — auto director on/off
- `W` — wide-shot request
- `1` through `9` — manual seat preset request and auto off
- `Q` — quit

## Logs

Each run writes event-only logs to `logs/speakerptz-YYYYMMDD.log`. Logs include startup/shutdown, active-speaker handoffs, manual overrides, and simulated camera requests. Raw microphone audio is **not recorded** by SPEAKERPTZ.

## Dante note

SPEAKERPTZ sees Dante Virtual Soundcard as a normal multichannel Windows audio device. Dante routing itself should be documented and configured separately with the school's existing Dante tools. Do not alter a live Dante routing matrix or clocking configuration blindly.
