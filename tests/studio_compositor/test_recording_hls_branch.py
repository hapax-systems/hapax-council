from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.studio_compositor.models import HlsConfig
from agents.studio_compositor.recording import add_hls_branch


class _FakeCaps:
    @staticmethod
    def from_string(value: str) -> str:
        return value


class _FakePadLinkReturn:
    OK = 0


class _FakePad:
    def __init__(self, name: str, *, link_return: int = _FakePadLinkReturn.OK) -> None:
        self.name = name
        self.link_return = link_return
        self.links: list[_FakePad] = []
        self.probes: list[tuple[object, object]] = []

    def link(self, other: _FakePad) -> int:
        self.links.append(other)
        return self.link_return

    def get_name(self) -> str:
        return self.name

    def add_probe(self, probe_type: object, callback: object) -> None:
        self.probes.append((probe_type, callback))


class _FakeElement:
    def __init__(self, factory: str, name: str, gst: _FakeGst) -> None:
        self.factory = factory
        self.name = name
        self._gst = gst
        self.props: dict[str, object] = {}
        self.links: list[str] = []
        self.static_pads: dict[str, _FakePad] = {}
        self.requested_pads: list[_FakePad] = []
        self.released_pads: list[_FakePad] = []

    def set_property(self, name: str, value: object) -> None:
        self.props[name] = value

    def link(self, other: _FakeElement) -> bool:
        self.links.append(other.name)
        return (self.name, other.name) not in self._gst.fail_links

    def get_name(self) -> str:
        return self.name

    def get_pad_template(self, name: str) -> str | None:
        if self._gst.missing_pad_template or (self.name, name) in self._gst.missing_pad_templates:
            return None
        return name

    def request_pad(self, template: str, name: str | None, caps: object) -> _FakePad | None:
        del template, name, caps
        if self._gst.request_pad_none or self.name in self._gst.request_pad_none_for:
            return None
        link_return = (
            self._gst.tee_pad_link_return if self.name == "output-tee" else _FakePadLinkReturn.OK
        )
        pad_name = f"{self.name}:src_0" if self.name == "output-tee" else f"{self.name}:video_0"
        pad = _FakePad(pad_name, link_return=link_return)
        self.requested_pads.append(pad)
        return pad

    def release_request_pad(self, pad: _FakePad) -> None:
        self.released_pads.append(pad)

    def get_static_pad(self, name: str) -> _FakePad | None:
        if self._gst.missing_static_pad_for == self.name:
            return None
        if name not in self.static_pads:
            link_return = (
                self._gst.hls_pad_link_return
                if self.name == "hls-parse" and name == "src"
                else _FakePadLinkReturn.OK
            )
            self.static_pads[name] = _FakePad(f"{self.name}:{name}", link_return=link_return)
        return self.static_pads[name]


class _FakeFactory:
    def __init__(self, gst: _FakeGst) -> None:
        self._gst = gst

    def make(self, factory: str, name: str) -> _FakeElement | None:
        if factory in self._gst.fail_factories or name in self._gst.fail_names:
            return None
        element = _FakeElement(factory, name, self._gst)
        self._gst.elements[name] = element
        self._gst.factories.append(factory)
        return element


class _FakeGst:
    Caps = _FakeCaps
    PadLinkReturn = _FakePadLinkReturn
    PadProbeReturn = type("_FakePadProbeReturn", (), {"OK": "ok"})
    PadProbeType = type("_FakePadProbeType", (), {"BUFFER": "buffer"})

    def __init__(
        self,
        *,
        fail_factories: set[str] | None = None,
        fail_names: set[str] | None = None,
        fail_links: set[tuple[str, str]] | None = None,
        tee_pad_link_return: int = _FakePadLinkReturn.OK,
        hls_pad_link_return: int = _FakePadLinkReturn.OK,
        missing_pad_template: bool = False,
        missing_pad_templates: set[tuple[str, str]] | None = None,
        request_pad_none: bool = False,
        request_pad_none_for: set[str] | None = None,
        missing_static_pad_for: str | None = None,
    ) -> None:
        self.fail_factories = fail_factories or set()
        self.fail_names = fail_names or set()
        self.fail_links = fail_links or set()
        self.tee_pad_link_return = tee_pad_link_return
        self.hls_pad_link_return = hls_pad_link_return
        self.missing_pad_template = missing_pad_template
        self.missing_pad_templates = missing_pad_templates or set()
        self.request_pad_none = request_pad_none
        self.request_pad_none_for = request_pad_none_for or set()
        self.missing_static_pad_for = missing_static_pad_for
        self.elements: dict[str, _FakeElement] = {}
        self.factories: list[str] = []
        self.ElementFactory = _FakeFactory(self)


class _FakePipeline:
    def __init__(self) -> None:
        self.added: list[_FakeElement] = []

    def add(self, element: _FakeElement) -> None:
        self.added.append(element)


def _build_subject(
    tmp_path: Path,
    gst: _FakeGst | None = None,
) -> tuple[SimpleNamespace, _FakePipeline, _FakeElement]:
    fake_gst = gst or _FakeGst()
    compositor = SimpleNamespace(
        _Gst=fake_gst,
        config=SimpleNamespace(hls=HlsConfig(output_dir=str(tmp_path))),
        _consent_recording_allowed=True,
        _hls_valve=None,
    )
    pipeline = _FakePipeline()
    tee = _FakeElement("tee", "output-tee", fake_gst)
    return compositor, pipeline, tee


def test_add_hls_branch_uploads_converts_and_caps_nv12_before_nvenc(tmp_path: Path) -> None:
    compositor, pipeline, tee = _build_subject(tmp_path)

    add_hls_branch(compositor, pipeline, tee, fps=30)

    assert [element.factory for element in pipeline.added] == [
        "queue",
        "valve",
        "cudaupload",
        "cudaconvert",
        "capsfilter",
        "nvh264enc",
        "h264parse",
        "hlssink2",
    ]
    assert [element.name for element in pipeline.added] == [
        "queue-hls",
        "hls-valve",
        "hls-upload",
        "hls-cudaconv",
        "hls-nv12caps",
        "hls-enc",
        "hls-parse",
        "hls-sink",
    ]

    by_name = {element.name: element for element in pipeline.added}
    assert by_name["hls-upload"].props["cuda-device-id"] == 0
    assert by_name["hls-cudaconv"].props["cuda-device-id"] == 0
    assert by_name["hls-nv12caps"].props["caps"] == ("video/x-raw(memory:CUDAMemory),format=NV12")
    assert by_name["hls-enc"].props["cuda-device-id"] == 0
    assert by_name["hls-enc"].props["rc-mode"] == 2
    assert by_name["hls-enc"].props["gop-size"] == 60
    assert by_name["hls-enc"].props["zerolatency"] is True
    assert by_name["hls-enc"].props["tune"] == 3
    assert by_name["hls-enc"].props["bframes"] == 0
    assert by_name["hls-enc"].props["repeat-sequence-header"] is True
    assert by_name["hls-parse"].props["config-interval"] == -1
    assert by_name["hls-sink"].props["send-keyframe-requests"] is True
    assert by_name["hls-sink"].props["playlist-location"] == str(tmp_path / "stream.m3u8")

    assert by_name["queue-hls"].links == ["hls-valve"]
    assert by_name["hls-valve"].links == ["hls-upload"]
    assert by_name["hls-upload"].links == ["hls-cudaconv"]
    assert by_name["hls-cudaconv"].links == ["hls-nv12caps"]
    assert by_name["hls-nv12caps"].links == ["hls-enc"]
    assert by_name["hls-enc"].links == ["hls-parse"]
    assert by_name["hls-parse"].links == []
    assert by_name["hls-parse"].static_pads["src"].links[0].name == "hls-sink:video_0"
    assert len(by_name["hls-sink"].requested_pads) == 1
    assert by_name["queue-hls"].static_pads["sink"].probes
    assert by_name["hls-valve"].static_pads["src"].probes
    assert by_name["hls-enc"].static_pads["sink"].probes
    assert by_name["hls-parse"].static_pads["src"].probes
    assert tee.requested_pads[0].links[0].name == "queue-hls:sink"
    assert compositor._hls_valve is by_name["hls-valve"]


def test_add_hls_branch_raises_when_cuda_upload_factory_missing(tmp_path: Path) -> None:
    compositor, pipeline, tee = _build_subject(
        tmp_path,
        _FakeGst(fail_factories={"cudaupload"}),
    )

    with pytest.raises(RuntimeError, match="failed to create cudaupload"):
        add_hls_branch(compositor, pipeline, tee, fps=30)

    assert compositor._hls_valve is None
    assert not tee.requested_pads


def test_add_hls_branch_raises_when_linear_link_fails(tmp_path: Path) -> None:
    compositor, _pipeline, tee = _build_subject(
        tmp_path,
        _FakeGst(fail_links={("hls-cudaconv", "hls-nv12caps")}),
    )

    with pytest.raises(RuntimeError, match="hls-cudaconv -> hls-nv12caps"):
        add_hls_branch(compositor, _pipeline, tee, fps=30)

    assert compositor._hls_valve is None
    assert not tee.requested_pads


def test_add_hls_branch_raises_and_releases_when_tee_pad_link_fails(tmp_path: Path) -> None:
    compositor, _pipeline, tee = _build_subject(
        tmp_path,
        _FakeGst(tee_pad_link_return=1),
    )

    with pytest.raises(RuntimeError, match="failed to link tee pad"):
        add_hls_branch(compositor, _pipeline, tee, fps=30)

    assert compositor._hls_valve is None
    assert tee.released_pads == tee.requested_pads


def test_add_hls_branch_requests_hlssink_video_pad(tmp_path: Path) -> None:
    compositor, _pipeline, tee = _build_subject(
        tmp_path,
        _FakeGst(missing_pad_templates={("hls-sink", "video")}),
    )

    with pytest.raises(RuntimeError, match="hls-sink video pad template"):
        add_hls_branch(compositor, _pipeline, tee, fps=30)

    assert compositor._hls_valve is None
    assert not tee.requested_pads


def test_add_hls_branch_releases_hlssink_pad_when_video_pad_link_fails(
    tmp_path: Path,
) -> None:
    compositor, pipeline, tee = _build_subject(
        tmp_path,
        _FakeGst(hls_pad_link_return=1),
    )

    with pytest.raises(RuntimeError, match="hls-parse src pad to hls-sink video pad"):
        add_hls_branch(compositor, pipeline, tee, fps=30)

    by_name = {element.name: element for element in pipeline.added}
    assert compositor._hls_valve is None
    assert by_name["hls-sink"].released_pads == by_name["hls-sink"].requested_pads
    assert not tee.requested_pads
