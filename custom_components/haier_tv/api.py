"""Small, asynchronous client for this firmware's native Binder interface.

No Home Assistant imports, Android key simulation, or files on the television.
All reads and writes share one ADB transport and lock. A write and its readback
are one transaction; a failed write is never automatically retried.
"""

import asyncio
import math
import re
import struct
from dataclasses import dataclass

from adb_shell.adb_device_async import AdbDeviceTcpAsync
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from adb_shell.exceptions import (
    AdbCommandFailureException,
    AdbConnectionError,
    AdbTimeoutError,
    DeviceAuthError,
    InvalidChecksumError,
    InvalidCommandError,
    InvalidResponseError,
    TcpTimeoutException,
)

from .const import MODEL, SOURCES

TRANSPORT_ERRORS = (
    OSError,
    TimeoutError,
    AdbCommandFailureException,
    AdbConnectionError,
    AdbTimeoutError,
    InvalidChecksumError,
    InvalidCommandError,
    InvalidResponseError,
    TcpTimeoutException,
)
READS = {
    "source": "service call tv 85",
    "volume": "service call tv 370",
    "mute": "service call tv 372",
    "backlight": "service call tv 232",
    "maxxbass": "service call tv 467",
    "screen": "service call power 11",
    "no_signal": "service call tv 398",
    "resolution": "service call tv 238",
}
IDENTITY_READS = {
    "model": "getprop ro.product.model",
    "sdk": "getprop ro.build.version.sdk",
    "fingerprint": "getprop ro.build.fingerprint",
    "ethernet": "cat /sys/class/net/eth0/address 2>/dev/null",
    "wifi": "cat /sys/class/net/wlan0/address 2>/dev/null",
    "service": "service list | grep 'tv: ' ",
}


class HaierError(Exception):
    """Base error for a device operation."""


class CannotConnect(HaierError):
    """Transport failed or timed out."""


class AuthenticationError(HaierError):
    """The TV has not authorized the ADB key."""


class UnsupportedDevice(HaierError):
    """Native Binder transaction IDs are not known for this device."""


class InvalidResponse(HaierError):
    """The device did not return a usable native state."""


class WriteNotApplied(HaierError):
    """Readback did not match the requested value."""

    def __init__(self, operation: str, expected: int, state: Snapshot) -> None:
        super().__init__(f"{operation} readback did not match {expected}")
        self.state = state


@dataclass(frozen=True)
class DeviceInfo:
    """Stable hardware identity and firmware version."""

    unique_id: str
    model: str
    fingerprint: str


@dataclass(frozen=True)
class Snapshot:
    """A single batch of validated readings, not optimistic state."""

    source: int
    volume: int
    mute: bool
    backlight: int
    maxxbass: bool
    screen: bool
    no_signal: bool
    resolution: str | None


def batch_command(commands: dict[str, str]) -> str:
    """Frame each result so Python can decode the original Parcel bytes."""
    return "; ".join(
        f"printf '\\n__HAIER_{key}__\\n'; {command}"
        for key, command in commands.items()
    )


def split_response(output: str, keys: dict[str, str]) -> dict[str, str]:
    """Require every expected frame once, even for an empty value."""
    parts = re.split(r"(?:^|\n)__HAIER_([a-z_]+)__\r?\n", output)
    names = parts[1::2]
    if len(names) != len(set(names)) or set(names) != set(keys):
        raise InvalidResponse("Missing or duplicate response frames")
    return dict(zip(names, (value.strip() for value in parts[2::2]), strict=True))


def parcel_bytes(text: str) -> bytes:
    """Decode single-line and offset-prefixed Android service Parcel dumps."""
    match = re.fullmatch(r"Result:\s*Parcel\((.*)\)", text.strip(), re.S)
    if not match:
        raise InvalidResponse("Missing Parcel")
    words: list[str] = []
    for line in match[1].splitlines():
        hex_part = re.sub(r"^\s*0x[0-9a-fA-F]+:\s*", "", line.split("'", 1)[0])
        words.extend(hex_part.split())
    if not words or any(not re.fullmatch(r"[0-9a-fA-F]{8}", w) for w in words):
        raise InvalidResponse("Invalid Parcel words")
    data = b"".join(struct.pack("<I", int(word, 16)) for word in words)
    if len(data) < 4 or struct.unpack_from("<i", data)[0] != 0:
        raise InvalidResponse("Binder exception")
    return data[4:]


def parcel_int(text: str, *, long: bool = False) -> int:
    """Read a signed int32 or int64 after the Binder exception header."""
    payload = parcel_bytes(text)
    if len(payload) < (8 if long else 4):
        raise InvalidResponse("Truncated integer Parcel")
    return struct.unpack_from("<q" if long else "<i", payload)[0]


def parcel_string(text: str) -> str | None:
    """Decode String16, respecting its length, terminator and surrogate pairs."""
    payload = parcel_bytes(text)
    if len(payload) < 4:
        raise InvalidResponse("Truncated string length")
    length = struct.unpack_from("<i", payload)[0]
    if length == -1:
        return None
    if not 0 <= length <= 256 or len(payload) < 4 + (length + 1) * 2:
        raise InvalidResponse("Truncated or oversized string Parcel")
    if payload[4 + length * 2 : 6 + length * 2] != b"\0\0":
        raise InvalidResponse("Missing String16 terminator")
    try:
        return payload[4 : 4 + length * 2].decode("utf-16-le") or None
    except UnicodeDecodeError as exc:
        raise InvalidResponse("Invalid String16 encoding") from exc


def parse_snapshot(output: str) -> Snapshot:
    """Treat required native reading failures as unavailable, never as zero."""
    fields = split_response(output, READS)
    values = {
        key: parcel_int(fields[key], long=key == "source")
        for key in READS
        if key != "resolution"
    }
    for key, maximum in {
        "volume": 100,
        "backlight": 10,
        "mute": 1,
        "maxxbass": 1,
        "screen": 1,
        "no_signal": 1,
    }.items():
        if not 0 <= values[key] <= maximum:
            raise InvalidResponse(f"Invalid {key} reading")
    if not 0 <= values["source"] <= 255:
        raise InvalidResponse("Invalid source reading")
    try:
        resolution = parcel_string(fields["resolution"])
    except InvalidResponse:
        resolution = None
    return Snapshot(
        source=values["source"],
        volume=values["volume"],
        mute=bool(values["mute"]),
        backlight=values["backlight"],
        maxxbass=bool(values["maxxbass"]),
        screen=bool(values["screen"]),
        no_signal=bool(values["no_signal"]),
        resolution=resolution,
    )


def parse_identity(output: str) -> DeviceInfo:
    """Reject other models before issuing any firmware-specific transaction."""
    fields = split_response(output, IDENTITY_READS)
    if (
        fields["model"] != MODEL
        or fields["sdk"] != "19"
        or "[android.app.ITvManager]" not in fields["service"]
    ):
        raise UnsupportedDevice("Requires LE40AL88G31R1, API 19 and ITvManager")
    for name in ("ethernet", "wifi"):
        mac = fields[name].lower()
        if re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac) and mac not in {
            "00:00:00:00:00:00",
            "ff:ff:ff:ff:ff:ff",
            "02:00:00:00:00:00",
        }:
            return DeviceInfo(mac, fields["model"], fields["fingerprint"])
    raise UnsupportedDevice("No stable Ethernet or Wi-Fi MAC address")


def write_command(operation: str, value: int | str) -> tuple[str, int]:
    """Validate values before generating shell; return expected readback."""
    if operation == "source":
        if value not in SOURCES:
            raise ValueError("Unknown input source")
        source = SOURCES[value]
        return (
            f"settings put system PlayingSource11 {source}; "
            "dumpsys activity activities | grep mResumedActivity | "
            "grep -Eq 'com\\.haier\\.settings/(\\.RootActivity|"
            "\\.sources\\.(NoSignalActivity|SourceInFoActivity))' || "
            "am start -W -n com.haier.settings/.RootActivity >/dev/null; "
            f'service call tv 85 | grep -q "Parcel(00000000 {source:08x} " || '
            f"service call tv 69 i32 {source} >/dev/null; "
            f"settings put system PlayingSource11 {source}",
            source,
        )
    setters = {
        "volume": (333, 100),
        "mute": (335, 1),
        "backlight": (186, 10),
        "maxxbass": (466, 1),
    }
    if operation not in setters:
        raise ValueError("Unknown control")
    transaction, maximum = setters[operation]
    if not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{operation} must be an integer from 0 to {maximum}")
    return f"service call tv {transaction} i32 {int(value)} >/dev/null", int(value)


def volume_percent(level: float) -> int:
    """Convert HA volume without accepting NaN, infinity or out-of-range input."""
    if not math.isfinite(level) or not 0 <= level <= 1:
        raise ValueError("Volume level must be between 0 and 1")
    return round(level * 100)


class HaierClient:
    """One direct TCP connection; no hidden access to HA's Android TV objects."""

    def __init__(
        self,
        host: str,
        port: int,
        signer: PythonRSASigner,
        expected_id: str | None = None,
    ) -> None:
        self._device = AdbDeviceTcpAsync(host, port, default_transport_timeout_s=5)
        self._signer = signer
        self._expected_id = expected_id
        self._lock = asyncio.Lock()
        self._closed = False
        self.info: DeviceInfo | None = None

    async def _shell(self, command: str) -> str:
        return await self._device.shell(command, read_timeout_s=15)

    async def _connect(self) -> None:
        if self._device.available:
            return
        if not await self._device.connect(
            rsa_keys=[self._signer], auth_timeout_s=10, read_timeout_s=15
        ):
            raise CannotConnect("ADB connect returned false")
        info = parse_identity(await self._shell(batch_command(IDENTITY_READS)))
        if self._expected_id is not None and info.unique_id != self._expected_id:
            raise UnsupportedDevice("The address now belongs to a different TV")
        self.info = info

    async def async_read(self) -> Snapshot:
        """Reconnect if needed, then read one complete snapshot."""
        return await self._transaction()

    async def async_write(self, operation: str, value: int | str) -> Snapshot:
        """Apply one explicit value and read back under the same lock."""
        command, expected = write_command(operation, value)
        state = await self._transaction(command)
        if getattr(state, operation) != expected:
            raise WriteNotApplied(operation, expected, state)
        return state

    async def _transaction(self, command: str | None = None) -> Snapshot:
        async with self._lock:
            if self._closed:
                raise CannotConnect("The client has been closed")
            try:
                async with asyncio.timeout(30):
                    await self._connect()
                    shell = batch_command(READS)
                    if command is not None:
                        shell = f"{command}; {shell}"
                    return parse_snapshot(await self._shell(shell))
            except DeviceAuthError as exc:
                await self._device.close()
                raise AuthenticationError("Authorize this computer on the TV") from exc
            except TRANSPORT_ERRORS as exc:
                await self._device.close()
                raise CannotConnect("ADB communication failed") from exc
            except HaierError, asyncio.CancelledError:
                await self._device.close()
                raise

    async def async_close(self) -> None:
        """Reject queued work, finish the active transaction, then release ADB."""
        self._closed = True
        async with self._lock:
            await self._device.close()
