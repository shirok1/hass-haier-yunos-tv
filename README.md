# Haier TV — native ADB

Home Assistant custom integration for **Haier LE40AL88G31R1, YunOS / Android API 19**. Controls the TV's native `android.app.ITvManager` service rather than simulating remote buttons or changing Android's unrelated music-stream volume.

This is a local development repository, not a published HACS integration. The first implementation is tested against **Home Assistant 2026.9.4 / Python 3.14.2+**. Other HA versions and Haier firmware variants are not validated.

## What appears in Home Assistant

One device with these entities:

| Entity | Function |
|---|---|
| Media player | Native input selection, volume 0–100, mute, screen on/off state |
| Number | Backlight 0–10 for the currently selected input |
| Switches | MaxxBass, mute |
| Sensors | Current input, input resolution |
| Binary sensors | Screen enabled, signal present, native connection |
| Button | Refresh all native states |

HDMI1/2/3 use the verified source IDs 16/17/18. ATV, DTV, AV and component input use firmware-derived mappings; those physical inputs have not all been signal-tested. Android is a reported internal state, not a selectable hardware input.

The integration does not expose unverified power/wake, sleep timer, or screen-blanking commands. It leaves the fixed picture profile and flattened EQ alone. MaxxBass is the TV's SRS-backed switch; off does not imply that every other SRS path is bypassed.

## Install and migrate from the YAML prototype

1. Copy `custom_components/haier_tv` into your HA configuration directory's `custom_components/` directory.
2. Remove the previous `haier-tv.yaml` package / Nix-generated package and its poll automation, if installed. **Disable the existing Android Debug Bridge integration for this TV.** This old TV's adbd accepts only one direct client; this integration owns the connection instead of reusing the old entity.
3. Restart HA. Open **Settings → Devices & services → Add integration → Haier TV (native ADB)**.
4. Enter the TV's LAN host and ADB port (normally 5555). Approve the TV's debugging authorization prompt and retry if prompted.
5. Add the created entities to the dashboard. Entity IDs are assigned by HA; no external entity references or scripts are required.

The ADB key is generated off the event loop and stored as `.storage/haier_tv_adbkey` and `.storage/haier_tv_adbkey.pub`. Preserve the key when moving your HA installation. There is no root requirement, APK installation, television-side script, external ADB server, or Internet requirement on the television.

A setup flow refuses to connect when it sees an enabled built-in Android Debug Bridge config entry for the same host. It cannot detect other computers, alternate hostnames, or external ADB clients. Stop those connections yourself; otherwise both integrations may repeatedly disconnect one another.

Use the integration's **Reconfigure** menu to change the host/port. The hardware MAC identifies the device; reconfiguration cannot silently substitute a different television. ADB authorization failures start HA's reauthentication flow.

## NixOS

A local package and module are supplied in `nix/`. With this repository available to your NixOS configuration, import its module:

```nix
{
  imports = [ ./ha-haier-tv/nix/module.nix ];
}
```

It uses nixpkgs' `buildHomeAssistantComponent`, packages only the component directory, and adds `adb-shell` plus its async extras from HA's Python package set. It does not enable another ADB integration or create YAML entities. After rebuilding/restarting, add the device through HA's UI as above. Use nixpkgs providing HA 2026.9.4 / Python 3.14 or newer; only 2026.9.4 is currently tested. The Nix files were checked against upstream builder definitions but **have not been evaluated/built locally** because this machine has no Nix installation.

## Behavior and failure handling

- `adb-shell[async]==0.4.4`, the same ADB library version used by HA Core's Android Debug Bridge integration.
- A `DataUpdateCoordinator` polls every 10 seconds and supplies every entity. Reading entity properties never performs network I/O.
- One client and one lock serialize reads, writes, readback and connection closure. A write is followed immediately by a full snapshot. UI state is not optimistic.
- Failed writes are reported to HA callers and are **not replayed automatically**. If readback differs, the UI receives the actual state and the action reports an error.
- When the native connection fails, controls become unavailable and the connection binary sensor becomes off. Polling reconnects and verifies model, SDK, Binder service and saved MAC before using transaction IDs.
- Core numeric readings are required; invalid or truncated data never becomes zero. Resolution failure affects only that sensor. A no-signal indication makes resolution unavailable.
- Input switching opens `RootActivity` only if outside the recognized TV source activities, and skips the switch transaction when already at the requested source. No Home key is sent.
- Unloading the entry or stopping HA closes the transport. Loading the integration only reads state; it does not apply preferences.

This is bounded polling, not a hardware event subscription. “Signal present” means the firmware's no-signal flag is clear, not an independent HDMI lock measurement. Network loss cannot be used to distinguish standby, power loss and a disconnected cable.

## Architecture

- `api.py`: HA-independent ADB client, validated Binder parsing, identity guard and control/readback transactions.
- `coordinator.py`: key initialization, HA polling and user-facing operation errors.
- `config_flow.py`: UI setup, duplicate detection, existing-ADB-owner check, address changes, authorization retry.
- Entity platforms: HA's standard media player, number, switch, sensor, binary sensor and button APIs.
- `diagnostics.py`: native readings and device metadata with host/MAC redacted; no keys or raw shell output.

Official reference implementation: [Home Assistant Core Android Debug Bridge, 2026.9.4](https://github.com/home-assistant/core/tree/2026.9.4/homeassistant/components/androidtv). The design uses documented HA APIs and the same ADB dependency; it does not import the built-in integration's private objects or copy its unrelated app-discovery logic. See [NOTICE](NOTICE) and [LICENSE](LICENSE) for attribution/licensing. Until this repository has a public documentation URL, the manifest links to the upstream ADB transport documentation; this README is the installation guide for this custom integration.

## Development and validation

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest --cov=custom_components.haier_tv --cov-report=term-missing
```

Tests load the **real HA 2026.9.4 config flow and all six platforms**, with the ADB transport mocked. They exercise service calls, readback rejection, availability/recovery, duplicate/conflict checks, reconfigure/reauth, key persistence, unload/stop cleanup, command serialization, and UTF-16 Parcel decoding. The resolution fixture was captured from the actual television.

The custom integration itself has **not yet been deployed to HA or exercised against the live TV**. Earlier ADB research validated the native source, volume, mute and backlight operations; MaxxBass has static native-code evidence and a readable state, but the new integration's live toggle still needs acceptance testing. Local test coverage is not HA Integration Quality Scale certification.

After installing, verify source switching while already watching HDMI, volume/mute, backlight, MaxxBass on/off, and remote-originated state changes. Then check disconnect/recovery and unloading. Do not run the old YAML polling alongside this integration.
