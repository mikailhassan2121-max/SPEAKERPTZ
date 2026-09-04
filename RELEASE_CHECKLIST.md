# SPEAKERPTZ release checklist

This tracks exactly what is required for the current release candidate,
**SPEAKERPTZ v1.0-rc1**, and what additionally must happen before it can be
promoted to stable **v1.0.0**. It is intentionally short and checkable — most
rows are things a command either passes or fails.

## v1.0-rc1 — software-verifiable release candidate

All of these are re-checkable at any time with no school hardware:

- [ ] `run_tests.bat` (`pytest`) passes completely, on this machine, from a
      clean `.venv`.
- [ ] `doctor_school.bat` (or `--doctor`) passes against a config in
      `simulate` mode.
- [ ] `run_soak_test.bat` passes (`passed: true`, `invariant_failures: 0`).
- [ ] `real_control_enabled` is `false` in every committed config
      (`config/room.yaml`, `config/local.example.yaml`).
- [ ] In real-camera mode (`real_control_enabled: true`), AUTO starts OFF on
      every launch, regardless of the previous session's persisted state.
      (In simulator mode, or with `real_control_enabled: false`, AUTO may
      start ON per `runtime.auto_start` — there is no real camera to move,
      so this is not a safety gate; see `speakerptz/main.py`'s
      `auto_enabled` computation.)
- [ ] Emergency stop (`X`) latches a STOP on every camera and disables AUTO;
      reset (`R`) clears the latch but leaves AUTO off.
- [ ] No secrets, camera passwords, or committed `config/local.yaml` in the
      repository or its Git history (`git log --all -p`, `git ls-files`).
- [ ] `config/local.yaml`, `logs/`, `.venv/`, and other local artifacts are
      excluded by `.gitignore` and confirmed absent from `git ls-files`.
- [ ] A clean clone/ZIP install (no pre-existing `.venv`, no `.git` directory)
      succeeds: `setup_school_windows.bat` (or the manual venv + `pip
      install -r requirements.txt` equivalent), then `doctor_school.bat`,
      then `run_tests.bat`.
- [ ] Documentation (`README.md`, `FIELD_SETUP.md`, `RUNTIME_RESILIENCE.md`)
      accurately describes current commands and behavior; every command it
      references actually exists.
- [ ] `field_setup.bat`'s guided walkthrough, `rehearsal_check.bat`, and
      `field_readiness.bat` all run with no hardware and no `runtime.mode:
      real` / `real_control_enabled: true` required.
- [ ] `identify_dante_channels.bat`, `calibrate_room.bat`, `camera_probe.bat`,
      and `camera_test.bat` each fail with a clear, non-crashing error
      message (not a traceback) when run against the default simulator
      config, since each of these requires real audio (`runtime.mode: real`)
      or real camera control (`real_control_enabled: true`) by design.
- [ ] Version strings across the running program (`speakerptz.main.VERSION`,
      `speakerptz.__version__`, dashboard banner, setup/field-setup console
      banners) agree with the release being cut.
- [ ] Known limitations (see below) are documented, not silently omitted.
- [ ] `git status` is clean before tagging.

## Promotion to stable v1.0.0 — requires physical school validation

None of these can be verified from this development machine. They are listed
in [FIELD_SETUP.md](FIELD_SETUP.md) as **REQUIRED SCHOOL VALIDATION** and must
each reach `HUMAN CONFIRMED` or `PASS` in `field_readiness.bat`'s report
before v1.0.0 is declared:

- [ ] The school's actual Dante network/subscriptions confirmed and mapped.
- [ ] Dante Virtual Soundcard tested on the actual production PC.
- [ ] Allen & Heath / microphone routing to DVS channels confirmed at the
      school (`identify_dante_channels.bat`).
- [ ] Real per-seat calibration completed in the actual room
      (`calibrate_room.bat`).
- [ ] The exact PTZ camera model and protocol (VISCA or ONVIF) confirmed;
      `camera_probe.bat` and `camera_test.bat` pass against it.
- [ ] Coexistence with the school's existing physical joystick/controller
      confirmed (`--field-confirm physical_joystick`).
- [ ] Manual keyboard/dashboard override confirmed during a rehearsal
      (`--field-confirm manual_override`).
- [ ] A controlled real-PTZ rehearsal completed with an operator watching the
      cameras directly (`--field-confirm real_ptz_rehearsal`), per
      [FIELD_SETUP.md §13](FIELD_SETUP.md#13-controlled-real-ptz-rehearsal).
- [ ] At least one full real meeting run supervised by an operator, with AUTO
      OFF and the physical joystick as the demonstrated fallback.

**Do not mark v1.0.0 stable based on simulator or laptop-microphone testing
alone.** Only `field_readiness.bat` reporting every row above as `PASS` or
`HUMAN CONFIRMED` (with "Real PTZ rehearsal" also complete) reflects a school
that has actually run the full sequence.

## Known limitations (v1.0-rc1)

- The console's Windows-legacy-codepage handling degrades non-ASCII device
  names to `?`/`�` rather than crashing; this is accepted graceful
  degradation, not a bug, and does not affect audio routing or channel
  identification (which are index-based).
- `run_real_audio_test.bat` hardcodes a development laptop's device index and
  channel count in its two `set` lines; it is a manual ad hoc tool, not part
  of the guided school workflow, and is documented in-file as needing local
  edits.
- `requirements.txt` uses lower-bound (`>=`) version pins rather than exact
  pins; this keeps the school install current with security fixes but means
  a future transitive dependency major bump could require re-validation.
