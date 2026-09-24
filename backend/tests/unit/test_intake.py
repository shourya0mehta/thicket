import asyncio
import hashlib

import pytest

from thicket.api.schemas import ErrorCode
from thicket.errors import ThicketError
from thicket.services import intake

WAV_HEAD = b"RIFF\x24\x08\x00\x00WAVEfmt "


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (WAV_HEAD, "wav"),
        (b"RF64\xff\xff\xff\xffWAVEds64", "wav"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x00\x00\x00", "id3"),
        (b"\xff\xfb\x90\x64" + b"\x00" * 8, "mp3"),
        (b"\xff\xf3\x90\x64" + b"\x00" * 8, "mp3"),
        (b"\x00\x00\x00\x20ftypM4A \x00\x00", "m4a"),
        (b"fLaC\x00\x00\x00\x22" + b"\x00" * 4, "flac"),
        (b"OggS\x00\x02" + b"\x00" * 6, "ogg"),
        (b"RIFF\x24\x08\x00\x00AVI LIST", None),
        (b"\x00\x01\x02\x03" * 3, None),
        (b"", None),
    ],
)
def test_sniff_signature(head, expected):
    assert intake.sniff_signature(head) == expected


@pytest.mark.parametrize(
    ("kind", "head", "ok"),
    [
        ("wav", WAV_HEAD, True),
        ("mp3", b"ID3\x04" + b"\x00" * 8, True),
        ("mp3", WAV_HEAD, False),
        ("flac", b"ID3\x04" + b"\x00" * 8, True),
        ("m4a", b"fLaC" + b"\x00" * 8, False),
        ("ogg", b"OggS" + b"\x00" * 8, True),
        ("wav", b"OggS" + b"\x00" * 8, False),
    ],
)
def test_signature_matches_extension(kind, head, ok):
    assert intake.signature_matches(kind, head) is ok


def test_extension_kind():
    assert intake.extension_kind("Dawn Chorus.WAV") == (".wav", "wav")
    assert intake.extension_kind("a.ogg") == (".ogg", "ogg")
    for bad in ("a.txt", "noext", "", None, "a.wav.exe"):
        with pytest.raises(ThicketError) as e:
            intake.extension_kind(bad)
        assert e.value.code == ErrorCode.unsupported_file_type
        assert e.value.status_code == 415


def test_sanitize_filename():
    assert intake.sanitize_filename("../../etc/passwd.wav") == "passwd.wav"
    assert intake.sanitize_filename("C:\\Users\\me\\x.wav") == "x.wav"
    assert intake.sanitize_filename("a\x00b\nc.wav") == "abc.wav"
    assert intake.sanitize_filename("") == "recording"
    assert intake.sanitize_filename("..") == "recording"
    assert len(intake.sanitize_filename("x" * 500 + ".wav")) == 200


def test_upload_sink_hash_and_random_name(tmp_path):
    body = WAV_HEAD + b"\x01" * 1000
    sink = intake.UploadSink(tmp_path, "../../evil name.wav", max_bytes=10_000)
    for i in range(0, len(body), 7):
        sink.write(body[i : i + 7])
    up = sink.finish()
    assert up.sha256 == hashlib.sha256(body).hexdigest()
    assert up.byte_size == len(body)
    assert up.filename == "evil name.wav"
    assert up.path.parent == tmp_path
    assert "evil" not in up.path.name and up.path.suffix == ".wav"
    assert up.path.read_bytes() == body


def test_upload_sink_enforces_cap_while_streaming(tmp_path):
    sink = intake.UploadSink(tmp_path, "a.wav", max_bytes=100)
    sink.write(WAV_HEAD + b"\x00" * 50)
    with pytest.raises(ThicketError) as e:
        sink.write(b"\x00" * 100)
    assert e.value.code == ErrorCode.file_too_large and e.value.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_upload_sink_rejects_signature_mismatch_early(tmp_path):
    sink = intake.UploadSink(tmp_path, "a.mp3", max_bytes=10_000)
    with pytest.raises(ThicketError) as e:
        sink.write(WAV_HEAD)
    assert e.value.code == ErrorCode.unsupported_file_type
    assert list(tmp_path.iterdir()) == []


def test_upload_sink_empty_file(tmp_path):
    sink = intake.UploadSink(tmp_path, "a.wav", max_bytes=100)
    with pytest.raises(ThicketError):
        sink.finish()
    assert list(tmp_path.iterdir()) == []


def _multipart(parts: list[tuple[str, str | None, bytes]], boundary: str = "BOUNDARY") -> bytes:
    out = b""
    for name, filename, data in parts:
        disp = f'form-data; name="{name}"'
        if filename is not None:
            disp += f'; filename="{filename}"'
        out += f"--{boundary}\r\nContent-Disposition: {disp}\r\n\r\n".encode() + data + b"\r\n"
    return out + f"--{boundary}--\r\n".encode()


async def _stream(body: bytes, size: int = 13):
    for i in range(0, len(body), size):
        yield body[i : i + size]


def parse(body: bytes, tmp_path, max_bytes=10_000, allowed=("file", "threshold", "models")):
    return asyncio.run(
        intake.parse_multipart_upload(
            "multipart/form-data; boundary=BOUNDARY",
            _stream(body),
            tmp_path,
            max_bytes=max_bytes,
            allowed_fields=allowed,
        )
    )


def test_parse_multipart_fields_and_file(tmp_path):
    audio = WAV_HEAD + b"\x02" * 300
    body = _multipart(
        [("threshold", None, b"0.5"), ("file", "x.wav", audio), ("models", None, b"birdnet")]
    )
    fields, up = parse(body, tmp_path)
    assert fields == {"threshold": "0.5", "models": "birdnet"}
    assert up is not None and up.path.read_bytes() == audio


def test_parse_multipart_rejects_unknown_field(tmp_path):
    with pytest.raises(ThicketError) as e:
        parse(_multipart([("modle", None, b"x")]), tmp_path)
    assert e.value.code == ErrorCode.invalid_parameter


def test_parse_multipart_rejects_two_files(tmp_path):
    audio = WAV_HEAD + b"\x00" * 10
    with pytest.raises(ThicketError):
        parse(_multipart([("file", "a.wav", audio), ("file", "b.wav", audio)]), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_parse_multipart_oversize_aborts(tmp_path):
    body = _multipart([("file", "a.wav", WAV_HEAD + b"\x00" * 5000)])
    with pytest.raises(ThicketError) as e:
        parse(body, tmp_path, max_bytes=1000)
    assert e.value.code == ErrorCode.file_too_large
    assert list(tmp_path.iterdir()) == []


def test_parse_multipart_bad_extension_before_data(tmp_path):
    with pytest.raises(ThicketError) as e:
        parse(_multipart([("file", "a.exe", b"MZ" + b"\x00" * 100)]), tmp_path)
    assert e.value.code == ErrorCode.unsupported_file_type


def test_parse_requires_multipart(tmp_path):
    with pytest.raises(ThicketError):
        asyncio.run(
            intake.parse_multipart_upload(
                "application/json", _stream(b"{}"), tmp_path, max_bytes=10, allowed_fields=()
            )
        )


def test_clean_text():
    assert intake.clean_text("  hi\x07 there  ", 20, "x") == "hi there"
    assert intake.clean_text("   ", 20, "x") is None
    with pytest.raises(ThicketError):
        intake.clean_text("x" * 21, 20, "x")
