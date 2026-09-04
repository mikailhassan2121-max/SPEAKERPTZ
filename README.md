# SPEAKERPTZ

Portable active-speaker PTZ controller for boardrooms, auditoriums, and meeting spaces.

## v0.3 status

v0.3 is still **camera-safe / simulation-only**, but the audio side is much closer to production:

- simulated or real Windows multichannel audio
- automatic per-channel quiet-room calibration at startup
- selects by signal rise above each mic's own floor, not raw loudness alone
- crosstalk-aware speaker handoff with a dominance margin
- confidence score
- short-interjection rejection via delayed handoff
- active-speaker hold and silence-to-wide behavior
- manual operator controls from the keyboard
- mic -> person -> camera/preset mapping in YAML
- real PTZ commands intentionally remain disabled

## First run on Windows

From a normal Command Prompt or PowerShell in this folder:

```powershell
setup_windows.bat
```

No PowerShell activation command is required; every launcher calls `.venv\\Scripts\\python.exe` directly.

### Simulation

```powershell
run_simulation.bat
```

Stay quiet during the first 3 seconds while the detector calibrates.

### List Windows audio devices

```powershell
list_audio_devices.bat
```

### Real-audio home test

`run_real_audio_test.bat` currently defaults to device 1 and 4 channels. Edit `DEVICE` and `CHANNELS` inside that file if Windows assigns different numbers.

## Operator hotkeys

While SPEAKERPTZ is running on Windows:

- `A` — toggle auto director on/off
- `W` — request the configured wide shot
- `1` through `9` — request that person's mapped preset and turn auto off
- `Q` — quit

All camera requests are still simulated in v0.3.

## School / Dante direction

Later, Dante Virtual Soundcard can appear to Windows as the multichannel input. SPEAKERPTZ will use the same real-audio path, only with isolated board-mic channels instead of a laptop microphone array.

Do **not** alter a live Dante routing matrix or production camera network until the existing routes and clocking have been documented.

## Room configuration

Edit `config/room.yaml` to map:

- input channel
- person's display name
- camera number
- preset number
- wide-shot preset

The audio thresholds are also there so they can be tuned for the actual room after a live read-only test.
