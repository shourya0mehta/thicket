import pytest

from thicket.api.schemas import ErrorCode
from thicket.errors import ThicketError
from thicket.ids import is_valid_event_id, is_valid_id, model_run_id, new_id
from thicket.services.storage import Storage


def test_new_ids_are_valid_and_unique():
    ids = {new_id("ana") for _ in range(100)}
    assert len(ids) == 100
    assert all(is_valid_id(i, "ana") for i in ids)
    assert not is_valid_id(new_id("prv"), "ana")


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "ana_../../../x",
        "ana_0123456789abcdef01234567/..",
        "ana_0123456789ABCDEF01234567",
        "ana_0123456789abcdef0123456",
        "ana_0123456789abcdef01234567\n",
        "",
        None,
        "ana_0123456789abcdef0123456%2F",
    ],
)
def test_invalid_ids_rejected(bad):
    assert not is_valid_id(bad, "ana")


def test_storage_refuses_traversal(tmp_path):
    st = Storage(tmp_path)
    for bad in ("../x", "ana_../../etc", "..", "/etc/passwd"):
        with pytest.raises(ThicketError) as e:
            st.analysis_tmp(bad)
        assert e.value.code == ErrorCode.analysis_not_found
        with pytest.raises(ThicketError):
            st.preview_dir(bad.replace("ana", "prv"))
        with pytest.raises(ThicketError):
            st.spectrogram_path(bad)
    good = new_id("ana")
    assert st.analysis_tmp(good) == (tmp_path / "tmp" / good).resolve()


def test_storage_uri_roundtrip(tmp_path):
    st = Storage(tmp_path)
    st.ensure()
    aid = new_id("ana")
    p = st.audio_path(aid)
    uri = st.storage_uri(p)
    assert uri == f"local:recordings/{aid}.wav"
    assert st.resolve_uri(uri) == p
    assert st.resolve_uri(None) is None
    with pytest.raises(ThicketError):
        st.resolve_uri("local:../../etc/passwd")


def test_model_run_and_event_ids():
    a = model_run_id("ana_x", "birdnet")
    assert a == model_run_id("ana_x", "birdnet")
    assert a != model_run_id("ana_x", "frog_insect")
    assert is_valid_event_id("evt_0123456789abcdef")
    assert not is_valid_event_id("evt_../../x")
