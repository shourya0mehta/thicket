"""Shared fixtures.

Synthetic audio is generated once per session into a temp folder; nothing
but ``fixtures/soundscape_30s.flac`` is committed.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from tests.helpers import SOUNDSCAPE, SR, make_settings, tone, white_noise
from thicket.config import Settings
from thicket.main import create_app


def _birdnet_available() -> bool:
    try:
        from thicket.models.birdnet_runtime import _interpreter_cls, resolve_model_dir

        resolve_model_dir()
        _interpreter_cls()
        return True
    except Exception:  # noqa: BLE001
        return False


BIRDNET_AVAILABLE = _birdnet_available()


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    if BIRDNET_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="BirdNET weights not installed (pip install -e '.[birdnet]')")
    for item in items:
        if "birdnet" in item.keywords:
            item.add_marker(skip)


def _ffmpeg(src: Path, dst: Path, *args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(src), *args, str(dst)],
        check=True,
        timeout=120,
    )


@pytest.fixture(scope="session")
def audio(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("audio")
    files: dict[str, Path] = {}

    def wav(name: str, x: np.ndarray, sr: int = SR, subtype: str = "PCM_16") -> None:
        p = d / f"{name}.wav"
        sf.write(str(p), x, sr, subtype=subtype)
        files[name] = p

    wav("tone_4k", tone(4000, 5.0))
    wav("tone_1500", tone(1500, 5.0))
    wav("noise", white_noise(5.0))
    wav("silence", np.zeros(5 * SR, dtype=np.float32))
    wav("clipped", np.clip(tone(1000, 5.0, amp=3.0), -1.0, 1.0))
    wav("lowrate_8k", tone(1000, 5.0, sr=8000), sr=8000)
    wav("rate_22k", tone(3000, 5.0, sr=22050), sr=22050)
    wav("short", tone(2000, 0.5))
    stereo = np.stack([tone(1000, 4.0, amp=0.3), np.clip(tone(1000, 4.0, amp=2.0), -1, 1)], axis=1)
    wav("stereo_one_clipped", stereo, sr=44100)

    rnd = d / "corrupt_random.wav"
    rnd.write_bytes(np.random.default_rng(1).integers(0, 256, 4096, dtype=np.uint8).tobytes())
    files["corrupt_random"] = rnd
    riff = d / "corrupt_riff.wav"
    riff.write_bytes(b"RIFF\x24\x10\x00\x00WAVEjunk" + bytes(range(256)) * 16)
    files["corrupt_riff"] = riff
    fake_mp3 = d / "really_wav.mp3"
    shutil.copyfile(files["tone_4k"], fake_mp3)
    files["wav_named_mp3"] = fake_mp3
    txt = d / "notes.txt"
    txt.write_text("not audio")
    files["txt"] = txt

    files["soundscape_flac"] = SOUNDSCAPE
    if shutil.which("ffmpeg"):
        mp3 = d / "soundscape.mp3"
        _ffmpeg(SOUNDSCAPE, mp3, "-codec:a", "libmp3lame", "-b:a", "192k")
        files["soundscape_mp3"] = mp3
        m4a = d / "soundscape.m4a"
        _ffmpeg(SOUNDSCAPE, m4a, "-codec:a", "aac", "-b:a", "192k")
        files["soundscape_m4a"] = m4a
        flac = d / "soundscape_copy.flac"
        _ffmpeg(SOUNDSCAPE, flac, "-codec:a", "flac")
        files["soundscape_flac_transcode"] = flac
        ogg = d / "soundscape.ogg"
        _ffmpeg(SOUNDSCAPE, ogg, "-codec:a", "libvorbis", "-q:a", "6")
        files["soundscape_ogg"] = ogg
        wav48 = d / "soundscape.wav"
        _ffmpeg(SOUNDSCAPE, wav48, "-codec:a", "pcm_s16le")
        files["soundscape_wav"] = wav48
    return files


@pytest.fixture(scope="session")
def frog_head(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A tiny synthetic frog/insect head: Spring Peeper fires in every window, the cricket never."""
    d = tmp_path_factory.mktemp("heads")
    path = d / "frog_insect_test.npz"
    hidden = 8
    np.savez(
        path,
        W1=np.zeros((1024, hidden), dtype=np.float32),
        b1=np.ones(hidden, dtype=np.float32),
        W2=np.zeros((hidden, 2), dtype=np.float32),
        b2=np.array([3.0, -3.0], dtype=np.float32),
        labels=np.array(["Pseudacris crucifer", "Gryllus pennsylvanicus"]),
        common_names=np.array(["Spring Peeper", "Fall Field Cricket"]),
        taxa=np.array(["amphibian", "insect"]),
        thresholds=np.array([0.2, 0.5]),
        temperature=np.array(1.0),
        embedding_mean=np.zeros(1024, dtype=np.float32),
        embedding_std=np.ones(1024, dtype=np.float32),
    )
    (d / "frog_insect_test.json").write_text(
        '{"name": "Synthetic test head", "version": "0.0.1-test", "license": "MIT"}'
    )
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def make_client(tmp_path: Path) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(**overrides: object) -> TestClient:
        app = create_app(make_settings(tmp_path, **overrides))
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


# ------------------------------------------------------------- platform


@pytest.fixture
def make_platform_client(tmp_path: Path) -> Iterator[Callable[..., TestClient]]:
    """Clients backed by the tone adapter (no BirdNET weights needed)."""
    from tests.platform_helpers import tone_registry

    clients: list[TestClient] = []

    def _make(**overrides: object) -> TestClient:
        data = tmp_path / f"data{len(clients)}"
        overrides.setdefault("thicket_data_dir", data)
        app = create_app(make_settings(tmp_path, **overrides), registry=tone_registry())
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def container(tmp_path: Path) -> Iterator:
    """A started container on a temp data dir with the tone adapter."""
    from tests.platform_helpers import tone_registry
    from thicket.container import Container

    c = Container(make_settings(tmp_path), registry=tone_registry())
    c.startup(background=False)
    yield c
    c.shutdown()
