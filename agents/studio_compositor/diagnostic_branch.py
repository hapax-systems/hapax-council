"""Helpers for non-viewer diagnostic GStreamer branches."""

from __future__ import annotations

import logging
from itertools import pairwise
from typing import Any

log = logging.getLogger(__name__)


class DiagnosticBranchLinkError(RuntimeError):
    """Raised when a diagnostic branch cannot be linked into the pipeline."""


def add_branch_elements_or_raise(
    pipeline: Any, elements: list[tuple[str, Any | None]], *, branch: str
) -> list[Any]:
    """Validate and add branch elements to ``pipeline``.

    Element factory failures should not degrade into later AttributeErrors or
    a half-built branch with no frame flow signal.
    """

    resolved: list[Any] = []
    for factory_name, element in elements:
        if element is None:
            _fail(branch, f"failed to create element {factory_name}")
        pipeline.add(element)
        resolved.append(element)
    return resolved


def link_chain_or_raise(elements: list[Any], *, branch: str) -> None:
    """Link a linear element chain, raising on the first failed link."""

    for src, dst in pairwise(elements):
        if not src.link(dst):
            _fail(branch, f"failed to link {_element_name(src)} -> {_element_name(dst)}")


def attach_tee_branch_or_raise(
    Gst: Any,
    tee: Any,
    sink_element: Any,
    *,
    branch: str,
    sink_pad_name: str = "sink",
) -> Any:
    """Request a tee src pad and link it to ``sink_element``.

    GStreamer pad links return a ``PadLinkReturn`` enum, not a boolean; compare
    against ``Gst.PadLinkReturn.OK`` when available so non-OK returns do not
    pass silently.
    """

    template = tee.get_pad_template("src_%u")
    if template is None:
        _fail(branch, f"{_element_name(tee)} has no src_%u pad template")

    tee_pad = tee.request_pad(template, None, None)
    if tee_pad is None:
        _fail(branch, f"{_element_name(tee)} failed to allocate request pad")

    sink_pad = sink_element.get_static_pad(sink_pad_name)
    if sink_pad is None:
        _release_request_pad(tee, tee_pad)
        _fail(branch, f"{_element_name(sink_element)} has no {sink_pad_name} sink pad")

    result = tee_pad.link(sink_pad)
    if not _pad_link_ok(Gst, result):
        _release_request_pad(tee, tee_pad)
        _fail(
            branch,
            (f"failed to pad-link {_pad_name(tee_pad)} -> {_pad_name(sink_pad)} ({result!r})"),
        )
    return tee_pad


def record_diagnostic_frame(stage: str) -> None:
    """Best-effort frame counter for diagnostic snapshot/proof branches."""

    try:
        from . import metrics

        metrics.record_render_stage_frame(stage)
    except Exception:
        pass


def _pad_link_ok(Gst: Any, result: Any) -> bool:
    pad_link_return = getattr(Gst, "PadLinkReturn", None)
    ok = getattr(pad_link_return, "OK", None)
    if ok is not None:
        return result == ok
    return bool(result)


def _fail(branch: str, detail: str) -> None:
    message = f"{branch}: {detail}"
    log.error(message)
    raise DiagnosticBranchLinkError(message)


def _element_name(element: Any) -> str:
    get_name = getattr(element, "get_name", None)
    if callable(get_name):
        try:
            return str(get_name())
        except Exception:
            pass
    return repr(element)


def _pad_name(pad: Any) -> str:
    get_name = getattr(pad, "get_name", None)
    if callable(get_name):
        try:
            return str(get_name())
        except Exception:
            pass
    return repr(pad)


def _release_request_pad(tee: Any, pad: Any) -> None:
    release = getattr(tee, "release_request_pad", None)
    if callable(release):
        try:
            release(pad)
        except Exception:
            log.debug("failed to release request pad after branch link failure", exc_info=True)
