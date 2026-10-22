# Native protocol scope and evidence

This module is specific to the LE40AL88G31R1's API 19 vendor framework. Binder transaction numbers are not a public cross-firmware API. Model/API/service checks reduce accidental misuse but cannot prove that every build of the same model has identical transaction numbering. Validate a new firmware before extending support.

| Field | Get | Set | Wire type / range |
|---|---:|---:|---|
| Input | tv 85 | tv 69 | getter int64; setter int32 |
| Volume | tv 370 | tv 333 | int32, 0–100 |
| Mute | tv 372 | tv 335 | boolean as int32 |
| Backlight | tv 232 | tv 186 | int32, 0–10 |
| MaxxBass | tv 467 | tv 466 | boolean as int32 |
| Screen enabled | power 11 | — | boolean as int32 |
| No signal | tv 398 | — | boolean as int32 |
| Resolution | tv 238 | — | String16 |

Input codes: ATV=1, DTV=3, AV=5, component=10, HDMI1=16, HDMI2=17, HDMI3=18. Code 24 is internal STORAGE/Android state. Source changes save `PlayingSource11` before/after switching and conditionally enter `com.haier.settings/.RootActivity`.

The client accepts Parcel words only from `Result: Parcel(...)`, discards the ASCII rendering, checks the exception header, and decodes little-endian signed int32/int64 or length-prefixed UTF-16LE. All snapshot blocks must be present once. Failed resolution parsing is isolated; failed core numeric fields invalidate the snapshot.

MaxxBass is a boolean vendor entry point. Native analysis found that enabling it selects SRS TruBass gain parameter 50; disabling it selects mode 0. It is not equivalent to an EQ bass slider or guaranteed global DSP bypass. This integration does not call the misleading TrueBass setter or expose unverified internal gain levels.

## Local research provenance

Derived from the user's prior on-device and firmware investigation in the `2026-09-20/adb` workspace:

- `outputs/tv-control/binder-catalog.csv` and `NATIVE-CONTROL.md` — interface signatures and round-trip control checks.
- `outputs/tv-source/README.md` — foreground-preserving source switching.
- `outputs/tv-audio/MAXXBASS.md` — native SRS call chain and limitations.
- `outputs/tv-control/extra-readings.txt` — source of `tests/fixtures/resolution.txt`.

Firmware binaries, private device state, keys and debloat tools are intentionally not required by this repository.


## Native standby (optional, not hardware-tested)

The extracted firmware interface identifies transaction 9 as
`IPowerManager.goToSleep(long eventTime, int reason)`. The client reads
`mLastWakeTime` from `dumpsys power`, splits that nonnegative int64 timestamp
into signed low/high int32 words for the old `service` CLI, and sends reason 0.
It validates the Binder exception header and separately confirms screen-off
or loss of ADB. An absent timestamp is an error; there is no key-event fallback.

Using the last wake timestamp avoids substituting host wall-clock time or Linux
`/proc/uptime` (which includes suspend) for Android's uptime clock. Android 4.4
accepts an event time equal to the last wake time and rejects future times:
[AOSP PowerManagerService](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-4.4.4_r2/services/java/com/android/server/power/PowerManagerService.java).
If the TV wakes again between the dump and the call, the old event can be ignored;
the confirmation timeout surfaces that instead of replaying the command.
