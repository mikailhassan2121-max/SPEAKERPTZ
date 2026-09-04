from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

import yaml

from speakerptz.audio.channelmap import normalize_channel_map, required_physical_channels
from speakerptz.core.config import CURRENT_CONFIG_VERSION

from .models import CheckResult, FieldPlan, SeatAssignment, StepStatus, WideShotAssignment


VISCA_PRESET_RANGE = (1, 64)
GENERIC_SEAT_PREFIXES = ("seat ", "mic ", "person ", "channel ")

CONFIG_HEADER = """# SPEAKERPTZ local site configuration.
#
# Written by the guided field setup workflow (field_setup.bat). This file is
# machine specific and is intentionally Git-ignored. Comments from the example
# file are not preserved when the workflow rewrites this file; the committed
# reference remains config/local.example.yaml.
#
# Generated: {generated}
"""


def peak_physical_input(levels, *, min_db: float = -50.0, dominance_db: float = 6.0):
    """Return (1-based physical input, reason) for the input that is clearly loudest.

    Returns (None, reason) when nothing is loud enough, or when the two loudest
    inputs are too close to tell apart. Refusing an ambiguous answer is the
    point: a mis-identified input maps a seat to the wrong camera preset.
    """
    values = [float(value) for value in levels]
    if not values:
        return None, "no input levels available"
    ranked = sorted(range(len(values)), key=lambda index: values[index], reverse=True)
    best = ranked[0]
    if values[best] < float(min_db):
        return None, f"loudest input is {values[best]:.1f} dB, below the {float(min_db):.1f} dB speech gate"
    if len(ranked) > 1:
        margin = values[best] - values[ranked[1]]
        if margin < float(dominance_db):
            return (
                None,
                f"inputs {best + 1} and {ranked[1] + 1} are within {margin:.1f} dB; speak into one mic only",
            )
    return best + 1, f"input {best + 1} peaked at {values[best]:.1f} dB"


def validate_plan(plan: FieldPlan, cameras: dict | None = None) -> list[CheckResult]:
    """Validate seat/preset assignments before they are written to configuration."""
    cameras = cameras or {}
    results: list[CheckResult] = []

    def fail(key: str, label: str, detail: str) -> None:
        results.append(CheckResult(key, label, StepStatus.FAIL, detail))

    def warn(key: str, label: str, detail: str) -> None:
        results.append(CheckResult(key, label, StepStatus.WARN, detail))

    seats = list(plan.seats)
    if not seats:
        fail("plan_seats", "Seat assignments", "No seats have been mapped yet.")
        return results

    logical = [seat.logical_channel for seat in seats]
    if sorted(logical) != list(range(1, len(seats) + 1)):
        fail(
            "plan_seats",
            "Seat assignments",
            f"Logical mic channels must be 1..{len(seats)} with no gaps; got {sorted(logical)}.",
        )
    else:
        results.append(
            CheckResult("plan_seats", "Seat assignments", StepStatus.PASS, f"{len(seats)} seat(s) mapped.")
        )

    physical = [seat.physical_input for seat in seats]
    duplicates = sorted({value for value in physical if physical.count(value) > 1})
    if duplicates:
        fail(
            "plan_physical_inputs",
            "Physical input map",
            f"Physical DVS input(s) {duplicates} are assigned to more than one seat.",
        )
    elif any(value < 1 for value in physical):
        fail("plan_physical_inputs", "Physical input map", "Physical inputs must be 1-based positive numbers.")
    else:
        results.append(
            CheckResult(
                "plan_physical_inputs",
                "Physical input map",
                StepStatus.PASS,
                f"Physical inputs {physical} (highest opened input: {max(physical)}).",
            )
        )

    unnamed = [seat.logical_channel for seat in seats if not str(seat.name).strip()]
    if unnamed:
        fail("plan_names", "Seat names", f"Seats {unnamed} have no name.")
    else:
        generic = [
            seat.logical_channel
            for seat in seats
            if str(seat.name).strip().lower().startswith(GENERIC_SEAT_PREFIXES)
        ]
        if len(generic) == len(seats):
            warn(
                "plan_names",
                "Seat names",
                "Every seat still uses a generic placeholder name; use the real seat or board-member labels.",
            )
        else:
            duplicate_names = sorted(
                {
                    seat.name.strip().lower()
                    for seat in seats
                    if [other.name.strip().lower() for other in seats].count(seat.name.strip().lower()) > 1
                }
            )
            if duplicate_names:
                warn("plan_names", "Seat names", f"Duplicate seat name(s): {duplicate_names}.")
            else:
                results.append(CheckResult("plan_names", "Seat names", StepStatus.PASS, "All seats are named."))

    shots = [(seat.camera, seat.preset) for seat in seats if seat.enabled]
    duplicate_shots = sorted({shot for shot in shots if shots.count(shot) > 1})
    if duplicate_shots:
        warn(
            "plan_presets",
            "Preset mappings",
            "Camera/preset pairs shared by more than one seat: "
            + ", ".join(f"camera {camera} preset {preset}" for camera, preset in duplicate_shots)
            + ". Only keep this if two seats intentionally share one shot.",
        )
    else:
        results.append(
            CheckResult("plan_presets", "Preset mappings", StepStatus.PASS, f"{len(shots)} distinct shot(s).")
        )

    camera_problems: list[str] = []
    for seat in seats:
        if cameras and seat.camera not in cameras:
            camera_problems.append(f"Seat {seat.logical_channel} references unknown camera {seat.camera}.")
            continue
        entry = cameras.get(seat.camera, {})
        if entry and entry.get("enabled", True) is not True:
            camera_problems.append(f"Seat {seat.logical_channel} references disabled camera {seat.camera}.")
        driver = str(entry.get("driver", "simulator")).lower()
        if seat.preset < 1:
            camera_problems.append(f"Seat {seat.logical_channel} preset must be 1 or greater.")
        elif driver == "visca" and not VISCA_PRESET_RANGE[0] <= seat.preset <= VISCA_PRESET_RANGE[1]:
            camera_problems.append(
                f"Seat {seat.logical_channel} VISCA preset {seat.preset} is outside "
                f"{VISCA_PRESET_RANGE[0]}-{VISCA_PRESET_RANGE[1]}."
            )
    if camera_problems:
        fail("plan_cameras", "Seat camera references", " ".join(camera_problems))
    else:
        results.append(
            CheckResult("plan_cameras", "Seat camera references", StepStatus.PASS, "Every seat targets a valid camera.")
        )

    wide = plan.wide_shot
    if wide is None:
        fail("plan_wide_shot", "Wide shot", "No wide shot has been mapped.")
    elif cameras and wide.camera not in cameras:
        fail("plan_wide_shot", "Wide shot", f"Wide shot references unknown camera {wide.camera}.")
    elif wide.preset < 1:
        fail("plan_wide_shot", "Wide shot", "Wide-shot preset must be 1 or greater.")
    else:
        driver = str(cameras.get(wide.camera, {}).get("driver", "simulator")).lower()
        if driver == "visca" and not VISCA_PRESET_RANGE[0] <= wide.preset <= VISCA_PRESET_RANGE[1]:
            fail(
                "plan_wide_shot",
                "Wide shot",
                f"Wide-shot VISCA preset {wide.preset} is outside "
                f"{VISCA_PRESET_RANGE[0]}-{VISCA_PRESET_RANGE[1]}.",
            )
        elif (wide.camera, wide.preset) in shots:
            warn(
                "plan_wide_shot",
                "Wide shot",
                f"Wide shot uses camera {wide.camera} preset {wide.preset}, which a seat also uses.",
            )
        else:
            results.append(
                CheckResult(
                    "plan_wide_shot",
                    "Wide shot",
                    StepStatus.PASS,
                    f"Camera {wide.camera} preset {wide.preset}.",
                )
            )

    disabled = sorted({int(value) for value in plan.disabled_channels})
    if disabled:
        invalid = [value for value in disabled if value not in logical]
        if invalid:
            fail(
                "plan_disabled_channels",
                "Disabled channels",
                f"Disabled channel(s) {invalid} are not mapped logical mics.",
            )
        elif len(disabled) == len(seats):
            fail("plan_disabled_channels", "Disabled channels", "Every mapped channel is disabled.")
        else:
            results.append(
                CheckResult(
                    "plan_disabled_channels",
                    "Disabled channels",
                    StepStatus.WARN,
                    f"Channel(s) {disabled} are configured but will be ignored by the detector.",
                )
            )
    return results


def plan_from_config(cfg: dict) -> FieldPlan:
    audio = cfg.get("audio", {})
    channels = int(audio.get("channels", 0) or 0)
    channel_map = normalize_channel_map(audio.get("channel_map"), channels) if channels else []
    seats = []
    for person in cfg.get("people", []) or []:
        logical = int(person["mic_channel"])
        physical = channel_map[logical - 1] if 0 < logical <= len(channel_map) else logical
        seats.append(
            SeatAssignment(
                logical_channel=logical,
                physical_input=int(physical),
                name=str(person.get("name", "")),
                camera=int(person["camera"]),
                preset=int(person["preset"]),
                enabled=logical not in {int(value) for value in audio.get("disabled_channels", []) or []},
            )
        )
    seats.sort(key=lambda seat: seat.logical_channel)
    wide_cfg = cfg.get("wide_shot") or {}
    wide = (
        WideShotAssignment(int(wide_cfg["camera"]), int(wide_cfg["preset"]))
        if "camera" in wide_cfg and "preset" in wide_cfg
        else None
    )
    return FieldPlan(
        seats=seats,
        wide_shot=wide,
        disabled_channels=sorted(int(value) for value in audio.get("disabled_channels", []) or []),
    )


def apply_plan(cfg: dict, plan: FieldPlan) -> dict:
    """Return a copy of cfg with the field plan applied. Never mutates cfg."""
    updated = copy.deepcopy(cfg)
    updated.setdefault("config_version", CURRENT_CONFIG_VERSION)
    audio = updated.setdefault("audio", {})
    seats = sorted(plan.seats, key=lambda seat: seat.logical_channel)
    if not seats:
        raise ValueError("A field plan needs at least one seat before it can be applied.")

    channel_map = [int(seat.physical_input) for seat in seats]
    normalize_channel_map(channel_map, len(seats))
    audio["channels"] = len(seats)
    audio["channel_map"] = channel_map
    audio["identifier_channels"] = max(
        int(audio.get("identifier_channels", 0) or 0), required_physical_channels(channel_map)
    )
    audio["disabled_channels"] = sorted(
        {int(value) for value in plan.disabled_channels}
        | {seat.logical_channel for seat in seats if not seat.enabled}
    )

    offsets = audio.get("level_offsets_db") or []
    if offsets and len(offsets) != len(seats):
        audio["level_offsets_db"] = [0.0] * len(seats)

    pairs = []
    for pair in audio.get("bleed_pairs") or []:
        try:
            first, second = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 1 <= first <= len(seats) and 1 <= second <= len(seats) and first != second:
            pairs.append([first, second])
    audio["bleed_pairs"] = pairs

    updated["people"] = [
        {
            "mic_channel": seat.logical_channel,
            "name": seat.name,
            "camera": seat.camera,
            "preset": seat.preset,
        }
        for seat in seats
    ]
    if plan.wide_shot is not None:
        updated["wide_shot"] = plan.wide_shot.to_dict()
    return updated


def apply_calibration(cfg: dict, calibration, *, apply_offsets: bool = True, apply_bleed: bool = False) -> dict:
    """Return a copy of cfg with reviewed calibration values applied.

    A `calibration.recommended` payload is frozen at the moment calibration
    ran, against however many seats were mapped at that time. If the seat
    count has since changed (e.g. the operator went back and added a seat),
    any recommendation that is keyed by channel count or number is silently
    dropped here rather than written -- otherwise it can produce a
    config.local.yaml that load_config immediately rejects.
    """
    updated = copy.deepcopy(cfg)
    audio = updated.setdefault("audio", {})
    recommended = dict(getattr(calibration, "recommended", {}) or {})
    channels = int(audio.get("channels") or len(audio.get("channel_map") or []) or 0)

    for key in ("absolute_threshold_db", "signal_margin_db"):
        if key in recommended:
            audio[key] = recommended[key]
    if apply_offsets and "level_offsets_db" in recommended:
        offsets = list(recommended["level_offsets_db"])
        if not channels or len(offsets) == channels:
            audio["level_offsets_db"] = offsets
    if "disabled_channels" in recommended:
        stale_safe = {
            int(value) for value in recommended["disabled_channels"] if not channels or 1 <= int(value) <= channels
        }
        audio["disabled_channels"] = sorted(
            {int(value) for value in audio.get("disabled_channels", []) or []} | stale_safe
        )
    if apply_bleed and "bleed_pairs" in recommended:
        stale_safe_pairs = [
            list(pair)
            for pair in recommended["bleed_pairs"]
            if not channels or all(1 <= int(value) <= channels for value in pair)
        ]
        audio["bleed_pairs"] = stale_safe_pairs
    return updated


def set_camera_entry(cfg: dict, entry: dict) -> dict:
    """Insert or replace one camera entry by id, returning a copy of cfg."""
    updated = copy.deepcopy(cfg)
    cameras = list(updated.get("cameras") or [])
    camera_id = int(entry["id"])
    replaced = False
    for index, existing in enumerate(cameras):
        if int(existing.get("id", -1)) == camera_id:
            cameras[index] = dict(entry)
            replaced = True
            break
    if not replaced:
        cameras.append(dict(entry))
    updated["cameras"] = sorted(cameras, key=lambda item: int(item.get("id", 0)))
    return updated


def backup_config(path: str, *, now=None) -> Path | None:
    """Copy an existing config next to itself before it is rewritten."""
    source = Path(path)
    if not source.exists():
        return None
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = source.with_name(f"{source.name}.bak-{stamp}")
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def write_config(path: str, cfg: dict, *, backup: bool = True, now=None) -> Path | None:
    """Atomically write configuration, keeping a timestamped backup by default."""
    target = Path(path)
    backup_path = backup_config(path, now=now) if backup else None
    target.parent.mkdir(parents=True, exist_ok=True)
    header = CONFIG_HEADER.format(generated=(now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"))
    body = yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False, allow_unicode=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(header + "\n" + body, encoding="utf-8")
    temporary.replace(target)
    return backup_path
