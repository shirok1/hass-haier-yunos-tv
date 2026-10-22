# Power methods on LE40AL88G31R1

Evidence collected on 2026-10-23 from this television's `android.policy.jar`,
`services.jar`, `framework.jar`, offline downloader APK, and prior native dumps.
These are firmware-specific implementations, not interchangeable Android APIs.

| Method | Interface | Behavior / evidence | Status |
|---|---|---|---|
| Vendor remote power off | `service call tv 5` | `ITvManager.stopRpcServer()`: mute, panel off, power-off watchdog, stop vendor RPC server | Command tested; owner confirmed normal power-off and remote power-on |
| Android orderly shutdown | `service call power 13 i32 0 i32 0` | `shutdown(false, false)` runs ShutdownThread, then the same vendor stopRpcServer path | Tested: shell UID 2000 is denied android.permission.REBOOT; no shutdown occurred |
| Vendor suspend-to-RAM | `service call tv 4` | Mute, panel off, NotifySuspendComingSoon, LED red; waits for TV app exit and package `com.android.settings`, then SuspendToRam | Not tested; can wait indefinitely after blanking the panel |
| Download-mode screen off | Downloader's `WarningDialog` / `SystemUtils.gotoSleep` | Sets `runtime.yunos.tv.offdown.sleep=sleeping`, closes backlight; later power/OK key causes a reboot in policy code | Specialized download workflow, not normal standby; not exposed |
| Android screen sleep | `IPowerManager.goToSleep` (transaction 9) | Updates Android wakefulness/display state; bypasses the normal TV power-button path | Rejected after owner reported black screen; next remote power key shut down instead of waking |
| Vendor RPC pause/resume | `tv 7` / `tv 8` | SuspendRpcServer / ResumeRpcServer only | No evidence of complete system power management; not exposed as power controls |

## Why `tv 5` matches the remote

`PhoneWindowManager.interceptKeyBeforeQueueing`, case 26, broadcasts
`MediaScannerSuspend` and, on key-down in the ordinary non-download path, calls
`TvManager.stopRpcServer()`. There are separate setup/download/property branches;
the direct Binder call reproduces the shutdown operation, not every key-side
broadcast or policy condition.

The ITvManager stub handles transaction 5 with no arguments and a void reply.
The proxy also uses `transact(5, ...)`. TvManagerService performs:

```java
pushBoolean(true);  invoke("SetMute");
pushBoolean(false); invoke("SetPanelOn");
invoke("EnablePowerOffWatchDog");
invoke("StopRpcServer");
```

The native StopRpcServer handler sets its stop flag and signals a worker event.
A successful Binder reply only acknowledges the request; HA still waits for
screen-off or loss of the native connection. The direct command was issued once,
returned `Result: Parcel(00000000)`, and the owner confirmed the physical cycle.

## Android orderly shutdown converges on the same vendor endpoint

`IPowerManager` transaction 13 accepts `boolean confirm, boolean wait`.
`PowerManagerService.shutdown` requires REBOOT permission and dispatches
`ShutdownThread`. Its run method sends ACTION_SHUTDOWN, calls ActivityManager
shutdown, shuts down radios, and calls MountService shutdown before low-level
power-off. In this firmware `PowerManagerService.lowLevelShutdown()` obtains
`TvManager` and calls `stopRpcServer()`; it does not use generic `sys.powerctl`
for this final shutdown operation. The offline downloader's `SystemUtils.shutDown`
also calls `pm.shutdown(false, false)`.

This makes it a distinct candidate for users with Android apps or attached
storage: extra orderly shutdown steps, with the same final vendor power path.
A direct Binder trial returned SecurityException: shell UID 2000 lacks `android.permission.REBOOT`. It did not shut down. This is not a usable ordinary-ADB option. Prior research established a debuggable system-UID helper with REBOOT permission, but JDWP injection through that helper would require a separate application/debugging workflow; it is not implemented in this integration.

## Why `tv 4` is not a ready-made alternative

`TvManagerService.suspendToRam()` changes audio, panel and LED state first. It
then contains unbounded loops waiting for `com.tsb.tv.Tv_strategy` to disappear
(on STD-capable systems) and for `mPackageName` to equal `com.android.settings`.
Its base `enableAtvBeforeSuspend()` is empty and the vendor `TvManagerServicePolicy` override only logs. Live package inventory has `com.haier.settings` but no `com.android.settings`; the global `SuspendToRam` setting is absent and `/sys/realtek_boards/STD/std` does not exist. Calling
this transaction without its expected surrounding UI/policy flow can leave the
panel dark while the Binder worker waits. No attempt was made to execute it.

## Local source locations

Under `/Users/shiroki/Codex/2026-09-20/adb/work/`:

- `power-dump-research/PhoneWindowManager.java`: power key policy.
- `power-dump-research/TvManagerServicePolicy.java`: vendor suspend hook (logging only).
- `power-dump-research/ITvManager.java`: native TV Binder IDs and argument types.
- `tv-control/TvManagerService.java`: vendor shutdown and suspend sequences.
- `power-dump-research/IPowerManager.java`: Android power Binder IDs.
- `power-dump-research/PowerManagerService.java`: Android sleep and low-level shutdown.
- `power-dump-research/ShutdownThread.java`: orderly application/storage shutdown.
- `power-dump-research/offline/sources/`: downloader-specific pseudo-sleep workflow.
- `tv-native/server.dis`: native RPC handlers.

## Historical timestamp bug

The removed Android-sleep path parsed `mLastWakeTime` from `dumpsys power`.
PowerManagerService.dump calls TimeUtils.formatUptime, which appends `(N ms ago)`,
`(in N ms)` or `(now)`. The 0.2.1 parser fix addressed this format, but could not
make Android sleep equivalent to vendor shutdown. The captured power fixture
remains as historical evidence; the integration no longer uses that timestamp.
