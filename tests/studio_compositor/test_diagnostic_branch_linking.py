"""Focused tests for diagnostic compositor branch link hardening."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.studio_compositor import smooth_delay, snapshots
from agents.studio_compositor.diagnostic_branch import (
    DiagnosticBranchLinkError,
    attach_tee_branch_or_raise,
)


class FakeCaps:
    @staticmethod
    def from_string(value: str) -> str:
        return value


class FakeMapFlags:
    READ = object()


class FakePadLinkReturn:
    OK = "ok"
    REFUSED = "refused"


class FakePadProbeReturn:
    OK = "ok"
    DROP = "drop"


class FakePadProbeType:
    BUFFER = "buffer"


class FakePad:
    def __init__(self, gst: FakeGst, name: str) -> None:
        self._gst = gst
        self._name = name
        self.probes: list[tuple[Any, Any]] = []

    def get_name(self) -> str:
        return self._name

    def link(self, other: FakePad) -> str:
        self._gst.pad_links.append((self._name, other._name))
        return self._gst.pad_link_return

    def add_probe(self, probe_type: Any, callback: Any) -> None:
        self.probes.append((probe_type, callback))


class FakeElement:
    def __init__(self, gst: FakeGst, factory_name: str, name: str) -> None:
        self._gst = gst
        self.factory_name = factory_name
        self.name = name
        self.properties: dict[str, Any] = {}
        self.callbacks: dict[str, Any] = {}
        self.requested_pads: list[FakePad] = []
        self.released_pads: list[FakePad] = []

    def get_name(self) -> str:
        return self.name

    def set_property(self, name: str, value: Any) -> None:
        self.properties[name] = value

    def connect(self, signal: str, callback: Any) -> None:
        self.callbacks[signal] = callback

    def link(self, other: FakeElement) -> bool:
        self._gst.element_links.append((self.name, other.name))
        return (self.name, other.name) not in self._gst.fail_links

    def get_static_pad(self, name: str) -> FakePad | None:
        if (self.name, name) in self._gst.missing_static_pads:
            return None
        return FakePad(self._gst, f"{self.name}.{name}")

    def get_pad_template(self, name: str) -> str | None:
        if (self.name, name) in self._gst.missing_pad_templates:
            return None
        return f"{self.name}.{name}.template"

    def request_pad(self, template: str, name: str | None, caps: Any) -> FakePad | None:
        del name, caps
        if self.name in self._gst.request_pad_failures:
            return None
        pad = FakePad(self._gst, f"{self.name}.{template}.requested")
        self.requested_pads.append(pad)
        return pad

    def release_request_pad(self, pad: FakePad) -> None:
        self.released_pads.append(pad)


class FakeElementFactory:
    def __init__(self, gst: FakeGst) -> None:
        self._gst = gst

    def make(self, factory_name: str, name: str) -> FakeElement | None:
        if name in self._gst.missing_elements:
            return None
        element = FakeElement(self._gst, factory_name, name)
        self._gst.elements[name] = element
        return element


class FakeGst:
    Caps = FakeCaps
    MapFlags = FakeMapFlags
    PadLinkReturn = FakePadLinkReturn
    PadProbeReturn = FakePadProbeReturn
    PadProbeType = FakePadProbeType

    def __init__(
        self,
        *,
        fail_links: set[tuple[str, str]] | None = None,
        pad_link_return: str = FakePadLinkReturn.OK,
        missing_elements: set[str] | None = None,
        missing_static_pads: set[tuple[str, str]] | None = None,
        missing_pad_templates: set[tuple[str, str]] | None = None,
        request_pad_failures: set[str] | None = None,
    ) -> None:
        self.fail_links = fail_links or set()
        self.pad_link_return = pad_link_return
        self.missing_elements = missing_elements or set()
        self.missing_static_pads = missing_static_pads or set()
        self.missing_pad_templates = missing_pad_templates or set()
        self.request_pad_failures = request_pad_failures or set()
        self.element_links: list[tuple[str, str]] = []
        self.pad_links: list[tuple[str, str]] = []
        self.elements: dict[str, FakeElement] = {}
        self.ElementFactory = FakeElementFactory(self)


class FakePipeline:
    def __init__(self) -> None:
        self.elements: list[FakeElement] = []

    def add(self, element: FakeElement) -> None:
        self.elements.append(element)


def fake_compositor(gst: FakeGst) -> SimpleNamespace:
    return SimpleNamespace(_Gst=gst, config=SimpleNamespace(framerate=30), _fx_smooth_delay=None)


def fake_tee(gst: FakeGst, name: str = "diagnostic-tee") -> FakeElement:
    return FakeElement(gst, "tee", name)


def test_attach_tee_branch_rejects_non_ok_pad_link() -> None:
    gst = FakeGst(pad_link_return=FakePadLinkReturn.REFUSED)
    tee = fake_tee(gst)
    queue = FakeElement(gst, "queue", "queue-test")

    with pytest.raises(DiagnosticBranchLinkError, match="failed to pad-link"):
        attach_tee_branch_or_raise(gst, tee, queue, branch="test branch")

    assert tee.released_pads == tee.requested_pads


def test_pre_fx_snapshot_branch_raises_on_failed_chain_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path)
    gst = FakeGst(fail_links={("snapshot-scale", "snapshot-scale-caps")})

    with pytest.raises(DiagnosticBranchLinkError, match="snapshot-scale -> snapshot-scale-caps"):
        snapshots.add_snapshot_branch(fake_compositor(gst), FakePipeline(), fake_tee(gst))


def test_llm_frame_snapshot_branch_raises_on_failed_pad_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path)
    gst = FakeGst(pad_link_return=FakePadLinkReturn.REFUSED)

    with pytest.raises(DiagnosticBranchLinkError, match="LLM frame snapshot branch"):
        snapshots.add_llm_frame_snapshot_branch(
            fake_compositor(gst),
            FakePipeline(),
            fake_tee(gst),
        )


def test_legacy_fx_snapshot_branch_raises_on_failed_chain_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path)
    gst = FakeGst(fail_links={("fx-snap-rate-caps", "fx-snap-jpeg")})

    with pytest.raises(DiagnosticBranchLinkError, match="fx-snap-rate-caps -> fx-snap-jpeg"):
        snapshots.add_fx_snapshot_branch(fake_compositor(gst), FakePipeline(), fake_tee(gst))


def test_smooth_delay_branch_raises_and_clears_reference_on_failed_link() -> None:
    gst = FakeGst(fail_links={("smooth-glcc-in", "smooth-delay")})
    compositor = fake_compositor(gst)
    compositor._fx_smooth_delay = object()

    with pytest.raises(DiagnosticBranchLinkError, match="smooth-glcc-in -> smooth-delay"):
        smooth_delay.add_smooth_delay_branch(compositor, FakePipeline(), fake_tee(gst))

    assert compositor._fx_smooth_delay is None


def test_smooth_delay_branch_sets_reference_after_successful_links() -> None:
    gst = FakeGst()
    compositor = fake_compositor(gst)

    smooth_delay.add_smooth_delay_branch(compositor, FakePipeline(), fake_tee(gst))

    assert compositor._fx_smooth_delay is gst.elements["smooth-delay"]
