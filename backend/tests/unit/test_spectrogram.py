import io

import numpy as np
import pytest
from PIL import Image
from tests.helpers import SR, tone, white_noise

from thicket.services import spectrogram as sp


def image(x):
    return Image.open(io.BytesIO(sp.render_png(x)))


def test_size_and_width_cap():
    im = image(white_noise(30.0))
    assert im.size == (sp.MAX_WIDTH, sp.HEIGHT)
    short = image(white_noise(1.0))
    assert short.size[1] == sp.HEIGHT and short.size[0] < sp.MAX_WIDTH


def test_deterministic_bytes():
    x = white_noise(5.0) + tone(3000, 5.0, amp=0.2)
    assert sp.render_png(x) == sp.render_png(x.copy())


def test_low_frequencies_at_bottom_and_tone_row():
    rgb = np.asarray(image(tone(4000, 3.0, amp=0.5) + white_noise(3.0, std=1e-4)).convert("RGB"))
    brightness = rgb.mean(axis=(1, 2))
    row = int(np.argmax(brightness))
    # 4 kHz of 16 kHz is 25% up from the bottom.
    expected = sp.HEIGHT - 1 - round(4000 / sp.MAX_HZ * (sp.HEIGHT - 1))
    assert abs(row - expected) <= 3


def test_colormap_monotonic_lightness_not_rainbow():
    lut = sp.colormap_lut().astype(float)
    luma = 0.2126 * lut[:, 0] + 0.7152 * lut[:, 1] + 0.0722 * lut[:, 2]
    assert np.all(np.diff(luma) >= -1e-9)
    assert luma[0] < 30 and luma[-1] > 220


def test_silence_renders_floor_colour():
    rgb = np.asarray(image(np.zeros(2 * SR, dtype=np.float32)).convert("RGB"))
    assert (rgb == sp.colormap_lut()[0]).all()


def test_long_audio_columns_average_equal_shares():
    power, freqs = sp.power_columns(white_noise(60.0))
    assert power.shape == (int((freqs <= sp.MAX_HZ).sum()), sp.MAX_WIDTH)
    assert freqs[0] == 0 and freqs[-1] == pytest.approx(16000, abs=50)
    # White noise: every column has about the same mean power.
    col = power.mean(axis=0)
    assert col.std() / col.mean() < 0.1


def test_rejects_wrong_rate():
    with pytest.raises(ValueError):
        sp.render_png(np.zeros(1000, dtype=np.float32), sample_rate=44100)
