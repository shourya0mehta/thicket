import numpy as np

from thicket.models.birdnet_runtime import frame_windows, load_non_bird_map, parse_label, week_48


def test_frame_windows_exact_multiple():
    x = np.ones(48000 * 9, dtype=np.float32)
    w, starts = frame_windows(x)
    assert w.shape == (3, 144000)
    assert list(starts) == [0.0, 3.0, 6.0]


def test_frame_windows_pads_tail_and_drops_tiny_tail():
    x = np.ones(int(48000 * 7.5), dtype=np.float32)
    w, starts = frame_windows(x, min_tail_seconds=1.0)
    assert list(starts) == [0.0, 3.0, 6.0]
    assert w[2, : 48000 * 1].min() == 1.0 and w[2, int(48000 * 1.5) :].max() == 0.0
    w2, s2 = frame_windows(np.ones(int(48000 * 6.5), dtype=np.float32), min_tail_seconds=1.0)
    assert list(s2) == [0.0, 3.0]


def test_frame_windows_short_clip_kept():
    w, starts = frame_windows(np.ones(48000, dtype=np.float32))
    assert w.shape == (1, 144000) and list(starts) == [0.0]


def test_label_parsing_and_taxa():
    nb = load_non_bird_map()
    lab = parse_label("Pseudacris crucifer_Spring Peeper", nb)
    assert (lab.scientific_name, lab.common_name, lab.taxon) == (
        "Pseudacris crucifer",
        "Spring Peeper",
        "amphibian",
    )
    assert parse_label("Cardinalis cardinalis_Northern Cardinal", nb).taxon == "bird"
    assert parse_label("Human vocal_Human vocal", nb).taxon == "human"
    assert parse_label("Gryllus pennsylvanicus_Fall Field Cricket", nb).taxon == "insect"


def test_week_48():
    from datetime import date

    assert week_48(date(2026, 1, 1)) == 1
    assert week_48(date(2026, 5, 15)) == 19
    assert week_48(date(2026, 12, 31)) == 48
