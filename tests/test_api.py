"""Native protocol parsing, identity checks, serialization and recovery."""

import asyncio
import struct
from unittest.mock import AsyncMock, Mock, patch

import pytest
from adb_shell.exceptions import DeviceAuthError

from custom_components.haier_tv.api import (
    READS,
    AuthenticationError,
    CannotConnect,
    HaierClient,
    InvalidResponse,
    UnsupportedDevice,
    WriteNotApplied,
    parcel_int,
    parcel_string,
    parse_identity,
    parse_snapshot,
    split_response,
    volume_percent,
    write_command,
)


def parcel(value, *, long=False):
    if isinstance(value, str):
        encoded = value.encode("utf-16-le")
        data = struct.pack("<ii", 0, len(encoded) // 2) + encoded + b"\0\0"
        data += b"\0" * (-len(data) % 4)
    else:
        data = struct.pack("<iq" if long else "<ii", 0, value)
    words = struct.unpack(f"<{len(data) // 4}I", data)
    return "Result: Parcel(" + " ".join(f"{word:08x}" for word in words) + " '....')"


def framed(values):
    return "".join(f"\n__HAIER_{key}__\n{value}\n" for key, value in values.items())


def snapshot(**overrides):
    values = (
        dict(
            source=16,
            volume=10,
            mute=0,
            backlight=10,
            maxxbass=1,
            screen=1,
            no_signal=0,
            resolution="1080p 60Hz",
        )
        | overrides
    )
    return framed(
        {key: parcel(value, long=key == "source") for key, value in values.items()}
    )


def identity(**overrides):
    return framed(
        dict(
            model="LE40AL88G31R1",
            sdk="19",
            fingerprint="test",
            ethernet="00:11:22:33:44:55",
            wifi="",
            service="tv: [android.app.ITvManager]",
        )
        | overrides
    )


def test_native_parcels():
    assert parcel_int(parcel(-1)) == -1
    assert parcel_int(parcel(18, long=True), long=True) == 18
    assert parcel_string(parcel("1080p 60Hz")) == "1080p 60Hz"
    assert parcel_string(parcel("测试 📺")) == "测试 📺"
    assert parcel_string(parcel(-1)) is None
    assert parse_snapshot(snapshot()).volume == 10
    assert parse_snapshot(snapshot()).maxxbass
    assert parse_identity(identity()).unique_id == "00:11:22:33:44:55"


def test_captured_resolution():
    from pathlib import Path

    assert (
        parcel_string(Path("tests/fixtures/resolution.txt").read_text()) == "1080p 60Hz"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "Permission denied",
        "Result: Parcel(ffffffff 00000000)",
        "Result: Parcel(00000000)",
        "Result: Parcel(xxxxxxxx)",
    ],
)
def test_bad_integer(bad):
    with pytest.raises(InvalidResponse):
        parcel_int(bad)


@pytest.mark.parametrize(
    "bad",
    [
        "Result: Parcel(00000000 fffffffe)",
        "Result: Parcel(00000000 00000002 00300031)",
        "Result: Parcel(00000000 00000001 00010031)",
        "Result: Parcel(00000000 00000001 0000d800)",
    ],
)
def test_bad_string(bad):
    with pytest.raises(InvalidResponse):
        parcel_string(bad)


def test_invalid_native_reading_and_optional_resolution():
    for value in [-1, 101]:
        with pytest.raises(InvalidResponse):
            parse_snapshot(snapshot(volume=value))
    with pytest.raises(InvalidResponse):
        parse_snapshot(snapshot(mute=2))
    output = snapshot().replace(parcel("1080p 60Hz"), "Permission denied")
    assert parse_snapshot(output).resolution is None
    with pytest.raises(InvalidResponse):
        split_response(output + "\n__HAIER_volume__\n0", READS)
    with pytest.raises(InvalidResponse):
        split_response("truncated", READS)


@pytest.mark.parametrize(
    "change",
    [
        {"model": "other"},
        {"sdk": "28"},
        {"service": ""},
        {"ethernet": "02:00:00:00:00:00"},
    ],
)
def test_unsupported_identity(change):
    with pytest.raises(UnsupportedDevice):
        parse_identity(identity(**change))


def test_wifi_identity():
    assert (
        parse_identity(identity(ethernet="", wifi="12:34:56:78:90:ab")).unique_id
        == "12:34:56:78:90:ab"
    )


@pytest.mark.parametrize(
    ("op", "value"),
    [
        ("volume", -1),
        ("volume", 101),
        ("mute", 2),
        ("backlight", 11),
        ("maxxbass", "1; reboot"),
        ("source", "HDMI1; reboot"),
        ("anything", 1),
    ],
)
def test_reject_bad_controls(op, value):
    with pytest.raises(ValueError):
        write_command(op, value)


def test_source_preserves_tv_foreground():
    command, value = write_command("source", "HDMI3")
    assert value == 18
    assert "|| am start" in command and "keyevent" not in command
    assert "SourceInFoActivity" in command and "NoSignalActivity" in command
    assert command.count("settings put system PlayingSource11 18") == 2
    assert "service call tv 69 i32 18" in command


def test_volume_and_setters():
    assert volume_percent(0.23) == 23
    for v in [float("nan"), float("inf"), -1, 2]:
        with pytest.raises(ValueError):
            volume_percent(v)
    for op, tx in [
        ("volume", 333),
        ("mute", 335),
        ("backlight", 186),
        ("maxxbass", 466),
    ]:
        assert f"service call tv {tx} i32 1" in write_command(op, 1)[0]


@pytest.fixture
def transport():
    device = Mock()
    device.available = False

    async def connect(**kwargs):
        device.available = True
        return True

    async def close():
        device.available = False

    device.connect = AsyncMock(side_effect=connect)
    device.close = AsyncMock(side_effect=close)
    device.shell = AsyncMock(
        side_effect=lambda cmd, **kwargs: (
            identity() if "__HAIER_model__" in cmd else snapshot()
        )
    )
    with patch("custom_components.haier_tv.api.AdbDeviceTcpAsync", return_value=device):
        yield device


async def test_connect_read_and_release(transport):
    client = HaierClient("192.0.2.1", 5555, Mock())
    assert (await client.async_read()).volume == 10
    assert client.info.model == "LE40AL88G31R1"
    await client.async_read()
    transport.connect.assert_awaited_once()
    await client.async_close()
    assert not transport.available
    with pytest.raises(CannotConnect):
        await client.async_read()
    assert transport.connect.await_count == 1


async def test_transport_failure_reconnects_without_replaying_write(transport):
    client = HaierClient("192.0.2.1", 5555, Mock())
    await client.async_read()
    transport.shell.side_effect = OSError("connection reset")
    with pytest.raises(CannotConnect):
        await client.async_write("maxxbass", 0)
    transport.close.assert_awaited_once()
    assert transport.connect.await_count == 1
    transport.shell.side_effect = lambda cmd, **kwargs: (
        identity() if "__HAIER_model__" in cmd else snapshot()
    )
    await client.async_read()
    assert transport.connect.await_count == 2
    assert "service call tv 466" not in transport.shell.call_args.args[0]


async def test_auth_and_wrong_device(transport):
    client = HaierClient("192.0.2.1", 5555, Mock(), "other-id")
    with pytest.raises(UnsupportedDevice):
        await client.async_read()
    assert transport.shell.await_count == 1  # Never touched native transactions.
    transport.connect.side_effect = DeviceAuthError("not authorized")
    with pytest.raises(AuthenticationError):
        await client.async_read()


async def test_writes_are_serialized_with_readback(transport):
    client = HaierClient("192.0.2.1", 5555, Mock())
    await client.async_read()
    active = 0
    peak = 0

    async def shell(cmd, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return snapshot()

    transport.shell.side_effect = shell
    await asyncio.gather(
        client.async_write("volume", 10),
        client.async_read(),
        client.async_write("maxxbass", 1),
    )
    assert peak == 1
    with pytest.raises(WriteNotApplied) as err:
        await client.async_write("maxxbass", 0)
    assert err.value.state.maxxbass is True


async def test_cancellation_releases_connection(transport):
    client = HaierClient("192.0.2.1", 5555, Mock())
    await client.async_read()
    transport.shell.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await client.async_read()
    assert not transport.available


@pytest.mark.parametrize(
    "activity",
    [
        "com.haier.settings/.RootActivity",
        "com.haier.settings/.sources.NoSignalActivity",
        "com.haier.settings/.sources.SourceInFoActivity",
        "other.launcher/.Home",
    ],
)
@pytest.mark.parametrize("current", [16, 18])
def test_source_shell_branches(activity, current):
    """Run the actual source shell with mocked Android commands, never the TV."""
    import subprocess

    command, _ = write_command("source", "HDMI3")
    mocks = (
        f"dumpsys() {{ echo 'mResumedActivity: {activity}'; }}; "
        "am() { echo ENTER_TV >&2; }; "
        "settings() { :; }; "
        'service() { if [ "$3" = 85 ]; then '
        f"echo 'Result: Parcel(00000000 {current:08x} 00000000)'; "
        "else echo SWITCH_SOURCE >&2; fi; }; "
    )
    result = subprocess.run(
        ["bash", "-c", mocks + command], capture_output=True, text=True, check=True
    )
    assert ("ENTER_TV" in result.stderr) == activity.startswith("other")
    assert ("SWITCH_SOURCE" in result.stderr) == (current != 18)
