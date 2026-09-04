# SPEAKERPTZ v1.0-rc1 — School Field Setup Guide

This is the step-by-step guide for installing and calibrating SPEAKERPTZ at an
actual school board room, from a fresh clone through a controlled hardware
rehearsal. It assumes no prior familiarity with the source code.

Follow it in order the first time. Every tool it references can also be
re-run independently later (for example, after a microphone is moved).

**Definitions used throughout this guide and in tool output:**

| Term | Meaning |
|---|---|
| IMPLEMENTED | The code exists and is committed. |
| SOFTWARE TESTED | Covered by the automated test suite (`run_tests.bat`), no hardware involved. |
| SIMULATOR TESTED | Exercised against SPEAKERPTZ's own simulated audio/camera drivers. |
| LAPTOP TESTED | Run against a real laptop microphone/audio device, not the school's Dante network. |
| SCHOOL HARDWARE TESTED | Run against the actual school Dante network and PTZ cameras. |
| FIELD VALIDATED | The full sequence in this guide has been physically completed at the school. |

The school field-setup toolkit referenced throughout this guide was added in
v0.10 and is unchanged in v1.0-rc1. As of v1.0-rc1, SPEAKERPTZ is
**IMPLEMENTED, SOFTWARE TESTED, and SIMULATOR TESTED**. It has **not** been
FIELD VALIDATED — the school's exact Dante routing and PTZ camera model have
not yet been physically confirmed. Nothing in this guide should be read as
claiming otherwise; `field_readiness.bat` will tell you exactly which of
those levels the current install has reached.

---

## 1. Prerequisites

- A Windows PC that will run SPEAKERPTZ, with Python 3.12 available as `py -3.12`.
- Dante Virtual Soundcard (DVS) installed and licensed, with the board
  microphone channels already subscribed in Dante Controller. SPEAKERPTZ does
  not manage Dante routing — DVS presents the subscribed channels to Windows
  as an ordinary multichannel audio device, and SPEAKERPTZ opens that device.
- At least one PTZ camera with presets already set up in the camera's own web
  interface or remote control, reachable by a fixed IP address on the same
  network as this PC.
- The existing physical joystick/controller for the cameras, still connected
  and working. SPEAKERPTZ is an additional automatic layer; it does not
  replace or disable the joystick.
- A `git clone` of this repository on the school PC (or a USB copy).

## 2. First installation

From the repository folder in PowerShell:

```powershell
.\setup_school_windows.bat
```

This creates a Python virtual environment, installs dependencies, and copies
`config\local.example.yaml` to `config\local.yaml` the first time (an
existing `config\local.yaml` is left alone on later runs). `config\local.yaml`
is machine-specific and is intentionally **not** committed to Git — it is
listed in `.gitignore` along with `logs\`, and confirmed camera credentials
never belong in it (see [Camera setup](#7-camera-setup)).

Then run the startup doctor, which never moves a camera or transmits audio
anywhere:

```powershell
.\doctor_school.bat
```

Fix anything marked `FAIL` before continuing. A `WARN` is worth reading but
is not necessarily blocking.

## 3. The guided workflow

```powershell
.\field_setup.bat
```

This is the single entry point for everything below (steps 4–11 map to menu
letters `D` through `M`, and steps 12–14 map to `N` through `S`). It never
enables real camera control — that remains a manual, explicit edit to
`config\local.yaml` plus the typed confirmation in `camera_test.bat`. You can
re-run `field_setup.bat` at any time; it shows the status of every step and
lets you redo any of them.

The individual tools it drives (`identify_dante_channels.bat`,
`calibrate_room.bat`, `camera_probe.bat`, `camera_test.bat`,
`rehearsal_check.bat`, `field_readiness.bat`) also work standalone, so you can
re-run just one of them later without going through the full menu.

Confirm before you start:

- **No live meeting is happening right now** (menu item `A`).
- **Real PTZ control is off** — `real_control_enabled: false` in
  `config\local.yaml` (menu item `B`; this is also the committed default).

## 4. Verify Dante Virtual Soundcard

Menu item `D`, or standalone:

```powershell
.\doctor_school.bat
```

Confirms Windows can see an audio input device, and if `runtime.device_name`
in `config\local.yaml` mentions "Dante", warns if the resolved device name
doesn't actually contain "Dante" (a common sign of an unrelated audio device
being picked up instead).

## 5. Identify each physical mic channel

Menu item `E`, or standalone:

```powershell
.\identify_dante_channels.bat
```

Walk to **one board microphone at a time**, speak into it, and note which
`PHYS ##` meter peaks. This works even when the subscribed Dante channels are
not consecutive, for example:

```text
Seat 1 <- DVS input 5
Seat 2 <- DVS input 6
Seat 3 <- DVS input 9
Seat 4 <- DVS input 10
```

## 6. Map each mic to a seat, and calibrate

Menu items `F` (seat mapping) and `G` (calibration) in `field_setup.bat`.

Seat mapping asks for `<physical input> <seat/person name> [camera id] [preset]`
for every seat, for example `5 Board Chair 1 1`, using the physical inputs you
found in step 5.

Calibration then asks you to stay quiet for a few seconds (room noise floor),
then to speak into each mic in turn. It stores only derived numbers per
channel — noise floor, speech level, and signal-to-noise ratio — and prints
suggested `config\local.yaml` values:

```text
SUGGESTED config/local.yaml VALUES (review before applying):
  audio.absolute_threshold_db: -56.5
  audio.level_offsets_db: [-0.3, 0.0, 12.0, 0.0]
  audio.signal_margin_db: 6.0
```

**No raw audio is ever recorded or stored** — calibration only ever sees the
same in-memory dB levels the live detector already computes. It also flags:

- **Dead channels** — a mic that was spoken into but produced no signal
  above the noise floor, meaning its DVS input is likely unsubscribed or
  muted in Dante Controller.
- **Low-SNR channels** — speech barely above the room noise floor; check
  gain at the Avantis.
- **Hot channels** — speech close to clipping; reduce gain at the console.
- **Possible bleed** — one mic picking up a neighboring one; consider
  `audio.bleed_pairs` once the seating is confirmed.

## 7. Camera setup

Menu items `I` (camera entry) and `J` (connectivity). SPEAKERPTZ never scans
the network for cameras — it only ever talks to the one IP address you type
in, one camera at a time.

Enter the camera's id, name, driver (`visca` or `onvif` once the exact model
is confirmed; `simulator` until then), IP address, and — for ONVIF — a
username plus the **name of an environment variable** that will hold the
password. Never put a plaintext `password:` field in the YAML; SPEAKERPTZ
refuses to load a config that contains one.

Set the actual password once, in Windows (System Properties → Environment
Variables), not in this repository:

```powershell
[Environment]::SetEnvironmentVariable("SPEAKERPTZ_CAMERA_1_PASSWORD", "the-real-password", "User")
```

Then test connectivity to that one camera:

```powershell
.\camera_probe.bat
```

This is read-only — it connects and checks health, and sends no movement
command.

## 8. Manually verify camera presets

Menu item `K`, standalone:

```powershell
.\camera_test.bat
```

This requires `real_control_enabled: true` in `config\local.yaml` and an
exact typed confirmation (`MOVE CAMERA <id>`) before anything moves. Step
through each preset you plan to use (`P <preset>`), confirm the framing is
correct in the camera's own preview, then `S` to stop and `Q` to quit. Set
`real_control_enabled` back to `false` afterward unless you are about to do
the rehearsal in [step 12](#12-controlled-real-ptz-rehearsal).

## 9. Map each seat to its camera/preset

Menu item `L`. This reuses the same seats from step 6 and lets you confirm or
adjust each seat's camera id and preset, plus the wide shot's camera/preset.
It validates the whole plan — no duplicate physical inputs, every camera
reference valid, VISCA presets in range, a wide shot configured — before
offering to write it to `config\local.yaml` (keeping a timestamped backup of
the file it replaces).

## 10. Configure and verify the wide shot

Also menu item `L`/`M`. The wide shot is what SPEAKERPTZ requests after a
silence timeout with no clear active speaker. Confirm its camera and preset
show the whole room, and use `camera_test.bat`'s `W` command to check it.

## 11. Dry run

Menu item `N`:

```powershell
.\run_school_dry_run.bat
```

This runs against real multichannel audio and computes real active-speaker
decisions, but — because `real_control_enabled` should still be `false` at
this point — every camera command it generates is handled by the simulator,
never transmitted to a real camera.

## 12. Rehearsal

Menu items `O`/`P`, or standalone:

```powershell
.\rehearsal_check.bat
```

This runs an automated scenario suite (sustained speech, handoff, brief
interjections, transient/cough rejection, overlapping speakers, silence to
wide, manual AUTO off, audio dropout, camera unavailable, and application
restart) against the same detector and camera-manager code the live
controller uses — no hardware required.

Two items in the rehearsal checklist can **never** be an automated `PASS`,
because software cannot observe them:

- **Physical joystick / manual operation** — have a person move a camera
  with the physical joystick while SPEAKERPTZ is running, and confirm it
  still responds.
- (During the actual rehearsal session) manual override at the keyboard/dashboard.

Confirm these in person, then record them:

```powershell
.venv\Scripts\python.exe -m speakerptz.main --field-confirm physical_joystick --operator "Your Name"
.venv\Scripts\python.exe -m speakerptz.main --field-confirm manual_override --operator "Your Name"
```

(`field_setup.bat` menu item `Q` prompts for the joystick confirmation, and
menu item `P` prompts for the manual-override confirmation right after
running the rehearsal scenarios.)

Also rehearse with real people: one sustained speaker, a handoff between two
people, a short interjection that should be ignored, two people talking over
each other, and silence.

## 13. Controlled real-PTZ rehearsal

Only after every other item in the readiness report (below) is satisfied,
and with explicit operator approval:

1. Set `real_control_enabled: true` in `config\local.yaml`.
2. Run `camera_test.bat` again and confirm each preset one more time.
3. Run a short live rehearsal meeting with `run_school_dry_run.bat` (which now
   drives the real cameras once `real_control_enabled` is true) while someone
   watches the cameras directly.
4. Record the confirmation:

   ```powershell
   .venv\Scripts\python.exe -m speakerptz.main --field-confirm real_ptz_rehearsal --operator "Your Name"
   ```

If anything looks wrong, set `real_control_enabled` back to `false`
immediately — this always takes effect on the next launch, and AUTO always
starts OFF regardless of what was persisted from a previous run.

## 14. Readiness report

```powershell
.\field_readiness.bat
```

Prints a concise summary of every check above, for example:

```text
SPEAKERPTZ FIELD READINESS
============================================================
Python                     PASS
Configuration              PASS
Dante/DVS                  PASS
Mic mapping                PASS
Mic calibration            PASS
Camera config              PASS
Camera connectivity        PASS
Preset mappings            PASS
Wide shot                  PASS
Dry-run rehearsal          PASS
Manual override            HUMAN CONFIRMATION REQUIRED
Physical joystick          HUMAN CONFIRMATION REQUIRED
Real PTZ rehearsal         NOT YET COMPLETED

STATUS:
NOT YET READY FOR CONTROLLED HARDWARE REHEARSAL
```

A human-confirmed item is always shown as `HUMAN CONFIRMED`, never as an
automated `PASS` — this report cannot be made to claim field validation on
its own. `field_readiness.bat` exits with code `0` once every row except
"Real PTZ rehearsal" is satisfied (ready for a controlled hardware
rehearsal), and non-zero otherwise.

---

## Normal meeting startup

Once setup is complete and `real_control_enabled: true` has been deliberately
set:

```powershell
.\start_speakerptz.bat
```

This always runs the startup doctor first, and **always starts with AUTO
off**, regardless of the previous session's state — press `A` (or use the
operator dashboard) to arm it once the room is ready. To make this start
automatically at sign-in instead, see `install_windows_autostart.ps1` in
`RUNTIME_RESILIENCE.md`.

## Manual takeover

At any point:

- Press `A` to toggle AUTO on/off from the console, or use the dashboard at
  `http://127.0.0.1:8765`.
- Press `X` for an emergency stop (disables AUTO and latches a stop on every
  camera); `R` clears the latch but leaves AUTO off.
- Press `1`–`9` to manually recall a seat's preset (this also disables AUTO).
- The **physical joystick continues to work independently at all times** —
  SPEAKERPTZ only sends discrete preset-recall commands, and only while AUTO
  is on or a manual key/dashboard action is used.

## Troubleshooting

| Symptom | Try |
|---|---|
| `doctor_school.bat` fails on audio | Re-check `runtime.device_name` in `config\local.yaml` against `list_audio_devices.bat`. |
| A seat never becomes active | Re-run `calibrate_room.bat` for that seat; check `audio.disabled_channels` doesn't include it by mistake. |
| Camera never connects | `camera_probe.bat`, then confirm the camera's IP, that its own remote-control feature is enabled, and (ONVIF) that its password environment variable is actually set in this Windows session. |
| Two seats seem to fight for the camera | Check `field_readiness.bat`'s mic-calibration warnings for suspected bleed; consider `audio.bleed_pairs`. |
| Wrong camera moves | Re-run `field_setup.bat` menu item `L` and re-verify the plan before saving. |
| Need to undo a config change | Every write from the guided workflow keeps a timestamped backup next to it: `config\local.yaml.bak-YYYYMMDD-HHMMSS`. Copy the desired backup back over `config\local.yaml`. |

## Shutdown

Press `Q` in the console, or close the window / Ctrl+C. Shutdown always
stops audio, requests a camera STOP, disconnects camera drivers, and records
a clean-shutdown flag — the next startup will not report an unclean prior
run.

## Rollback / recovery

- **Config rollback**: restore the desired `config\local.yaml.bak-*` file (see
  Troubleshooting above), or re-copy `config\local.example.yaml`.
- **Immediately stop automatic camera control**: press `X` (emergency stop)
  or set `real_control_enabled: false` and restart — the joystick keeps
  working the whole time.
- **Suspect a bad install**: `setup_school_windows.bat` is safe to re-run; it
  reuses the existing `config\local.yaml` and only reinstalls the Python
  environment and dependencies.
- **Uninstall the autostart task**: `.\install_windows_autostart.ps1 -Remove`.
