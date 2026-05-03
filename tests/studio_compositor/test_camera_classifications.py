"""Tests for camera classification metadata (task #135).

``CameraSpec`` carries semantic metadata (``semantic_role``,
``subject_ontology``, ``angle``, ``operator_visible``,
``ambient_priority``) so Hapax (director, reverie, daimonion) can reason
about what each camera points at. The compositor publishes the full
classification dict to ``/dev/shm/hapax-compositor/camera-classifications.json``
so downstream perception (``PerceptualField.camera_classifications``)
can read it.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.studio_compositor.config import _DEFAULT_CAMERAS, _default_config
from agents.studio_compositor.models import CameraSpec
from shared.perceptual_field import PerceptualField


class TestCameraSpecClassificationFields:
    def test_defaults_leave_classification_unspecified(self) -> None:
        cam = CameraSpec(role="test", device="/dev/video0")
        assert cam.semantic_role == "unspecified"
        assert cam.subject_ontology == []
        assert cam.angle == "unspecified"
        assert cam.operator_visible is False
        assert cam.ambient_priority == 5

    def test_explicit_classification(self) -> None:
        cam = CameraSpec(
            role="brio-operator",
            device="/dev/video0",
            semantic_role="operator-face",
            subject_ontology=["person"],
            angle="front",
            operator_visible=True,
            ambient_priority=7,
        )
        assert cam.semantic_role == "operator-face"
        assert cam.subject_ontology == ["person"]
        assert cam.angle == "front"
        assert cam.operator_visible is True
        assert cam.ambient_priority == 7

    def test_subject_ontology_independent_across_instances(self) -> None:
        """Default factory must not share the list across instances."""
        a = CameraSpec(role="a", device="/dev/video0")
        b = CameraSpec(role="b", device="/dev/video1")
        a.subject_ontology.append("person")
        assert b.subject_ontology == []


class TestDefaultLayoutClassifications:
    """The 6 production cameras must all carry non-default metadata."""

    _EXPECTED_SEMANTIC_ROLES = {
        "brio-operator": "operator-face",
        "c920-desk": "operator-hands",
        "c920-room": "room-wide",
        "c920-overhead": "operator-desk-topdown",
        "brio-room": "outboard-gear",
        "brio-synths": "turntables",
    }

    def test_all_six_cameras_carry_classification(self) -> None:
        assert len(_DEFAULT_CAMERAS) == 6
        cfg = _default_config()
        assert len(cfg.cameras) == 6
        for cam in cfg.cameras:
            # Every production camera must have a concrete semantic_role
            # (not the "unspecified" default), and a non-empty ontology.
            assert cam.semantic_role != "unspecified", f"{cam.role} missing semantic_role"
            assert cam.subject_ontology, f"{cam.role} missing subject_ontology"
            assert cam.angle != "unspecified", f"{cam.role} missing angle"

    def test_semantic_roles_match_spec(self) -> None:
        cfg = _default_config()
        by_role = {cam.role: cam for cam in cfg.cameras}
        for role, expected_semantic in self._EXPECTED_SEMANTIC_ROLES.items():
            assert by_role[role].semantic_role == expected_semantic

    def test_operator_visible_cameras(self) -> None:
        """Only operator-face and room-wide see the operator."""
        cfg = _default_config()
        by_role = {cam.role: cam for cam in cfg.cameras}
        assert by_role["brio-operator"].operator_visible is True
        assert by_role["c920-room"].operator_visible is True
        # All others must not expose the operator's face.
        for role in ("c920-desk", "c920-overhead", "brio-room", "brio-synths"):
            assert by_role[role].operator_visible is False, f"{role} wrongly operator-visible"

    def test_ambient_priority_in_range(self) -> None:
        cfg = _default_config()
        for cam in cfg.cameras:
            assert 0 <= cam.ambient_priority <= 10, f"{cam.role} priority out of range"

    def test_room_wide_has_highest_ambient_priority(self) -> None:
        """The wide room shot is the most natural ambient cut (spec: 8)."""
        cfg = _default_config()
        by_role = {cam.role: cam for cam in cfg.cameras}
        assert by_role["c920-room"].ambient_priority == 8
        # All others have a lower ambient_priority.
        max_other = max(cam.ambient_priority for cam in cfg.cameras if cam.role != "c920-room")
        assert max_other < 8


class TestClassificationPublish:
    """``StudioCompositor.publish_camera_classifications`` writes a
    valid, roundtrip-readable JSON dict to /dev/shm under tmp+rename."""

    def _make_compositor(self, tmp_path: Path) -> object:
        # Import locally so the module import doesn't happen at collection.
        from agents.studio_compositor.compositor import StudioCompositor
        from agents.studio_compositor.models import CompositorConfig

        # Two cameras, one with a full classification and one left at
        # defaults — publication must include both.
        cfg = CompositorConfig(
            cameras=[
                CameraSpec(
                    role="brio-operator",
                    device="/dev/video0",
                    semantic_role="operator-face",
                    subject_ontology=["person"],
                    angle="front",
                    operator_visible=True,
                    ambient_priority=7,
                ),
                CameraSpec(role="unnamed", device="/dev/video1"),
            ]
        )

        # Patch SNAPSHOT_DIR on both the module and inside the bound name
        # used by publish_camera_classifications. Avoid touching /dev/shm
        # on the host by writing into tmp_path.
        with patch("agents.studio_compositor.compositor.SNAPSHOT_DIR", tmp_path):
            comp = StudioCompositor.__new__(StudioCompositor)
            # Minimal state for publish_camera_classifications — avoids
            # the full __init__ which wires GStreamer / budget trackers.
            comp.config = cfg
            classifications = comp.publish_camera_classifications()
        return classifications, tmp_path / "camera-classifications.json"

    def test_publish_writes_valid_json(self, tmp_path: Path) -> None:
        classifications, target = self._make_compositor(tmp_path)

        assert target.exists()
        on_disk = json.loads(target.read_text())

        # Both cameras appear.
        assert set(on_disk.keys()) == {"brio-operator", "unnamed"}
        assert on_disk == classifications

    def test_publish_payload_shape(self, tmp_path: Path) -> None:
        classifications, _ = self._make_compositor(tmp_path)

        brio = classifications["brio-operator"]
        assert brio["semantic_role"] == "operator-face"
        assert brio["subject_ontology"] == ["person"]
        assert brio["angle"] == "front"
        assert brio["operator_visible"] is True
        assert brio["ambient_priority"] == 7

        unnamed = classifications["unnamed"]
        assert unnamed["semantic_role"] == "unspecified"
        assert unnamed["subject_ontology"] == []
        assert unnamed["angle"] == "unspecified"
        assert unnamed["operator_visible"] is False
        assert unnamed["ambient_priority"] == 5

    def test_publish_atomic_no_partial_file(self, tmp_path: Path) -> None:
        """The ``.tmp`` shadow must not survive a successful rename."""
        _, target = self._make_compositor(tmp_path)
        assert target.exists()
        assert not target.with_suffix(".tmp").exists()


class TestPerceptualFieldRoundtrip:
    def test_default_empty_dict(self) -> None:
        field = PerceptualField()
        assert field.camera_classifications == {}

    def test_accepts_dict(self) -> None:
        payload = {
            "brio-operator": {
                "semantic_role": "operator-face",
                "subject_ontology": ["person"],
                "angle": "front",
                "operator_visible": True,
                "ambient_priority": 7,
            }
        }
        field = PerceptualField(camera_classifications=payload)
        assert field.camera_classifications == payload

    def test_model_dump_roundtrip(self) -> None:
        payload = {
            "c920-overhead": {
                "semantic_role": "operator-desk-topdown",
                "subject_ontology": ["hands", "mpc", "desk"],
                "angle": "top-down",
                "operator_visible": False,
                "ambient_priority": 6,
            }
        }
        field = PerceptualField(camera_classifications=payload)
        dumped = field.model_dump()
        reconstructed = PerceptualField.model_validate(dumped)
        assert reconstructed.camera_classifications == payload

    def test_build_perceptual_field_reads_shm(self, tmp_path: Path) -> None:
        """``build_perceptual_field`` picks up the published dict."""
        import shared.perceptual_field as pf

        shm_path = tmp_path / "camera-classifications.json"
        payload = {
            "brio-operator": {
                "semantic_role": "operator-face",
                "subject_ontology": ["person"],
                "angle": "front",
                "operator_visible": True,
                "ambient_priority": 7,
            }
        }
        shm_path.write_text(json.dumps(payload))

        with patch.object(pf, "_CAMERA_CLASSIFICATIONS", shm_path):
            field = pf.build_perceptual_field()
        assert field.camera_classifications == payload

    def test_build_perceptual_field_missing_file(self, tmp_path: Path) -> None:
        """A missing SHM file yields an empty dict, not a crash."""
        import shared.perceptual_field as pf

        missing = tmp_path / "does-not-exist.json"
        with patch.object(pf, "_CAMERA_CLASSIFICATIONS", missing):
            field = pf.build_perceptual_field()
        assert field.camera_classifications == {}


# ──────────────────────────────────────────────────────────────────────────
# Round-robin degeneracy regression — semantic-recruitment audit 2026-05-02
#
# The audit observed 322 ``hero-camera-override`` events in 15 min, every
# single one tagged ``priority=5, repetition-3.0``: pure round-robin via
# the recency penalty because every camera scored identically (all
# ``subject_ontology=[]`` and ``operator_visible=false``). Root cause: a
# user-side YAML (``~/.config/hapax-compositor/config.yaml``) listed the
# six cameras without classification fields, so pydantic filled them with
# ``CameraSpec`` model defaults (``"unspecified"``/``[]``/``False``). The
# ``_merge_camera_classifications`` overlay in ``load_config`` carries the
# ``_DEFAULT_CAMERAS`` classifications through to such deployments. These
# tests pin the data invariants this fix relies on so the round-robin
# degeneracy can't drift back in via any future config-loading path.
# ──────────────────────────────────────────────────────────────────────────


# Open-vocab tags used in ``subject_ontology`` across the production
# fleet. New terms must be added here and to at least one camera spec —
# the controlled vocabulary keeps the FollowModeController's
# ``_LOCATION_ONTOLOGY_HINTS`` matching predictable.
KNOWN_ONTOLOGY_TERMS: frozenset[str] = frozenset(
    {
        "person",
        "hands",
        "mpc",
        "room",
        "desk",
        "eurorack",
        "outboard",
        "turntable",
        "vinyl",
    }
)

# Per the studio inventory (memory project_studio_cameras / audit §1):
# 6 USB cameras, two physical-position groups per camera class.
EXPECTED_ROLES: frozenset[str] = frozenset(
    {
        "brio-operator",
        "brio-room",
        "brio-synths",
        "c920-desk",
        "c920-room",
        "c920-overhead",
    }
)


class TestSemanticClassificationRegression:
    """Regression: every production camera carries non-empty semantic
    metadata so ``FollowModeController._score_camera`` does not collapse
    to round-robin via the recency penalty.
    """

    def test_no_camera_has_empty_subject_ontology(self) -> None:
        """The audit's hard data: every camera scoring at ``priority=5``
        with ``subject_ontology=[]`` defeats the location-match bonus.
        At least one ontology tag per camera is the load-bearing
        invariant — without it, ``_LOCATION_MATCH_BONUS`` (3.0) cannot
        ever fire and the controller falls through to round-robin."""
        cfg = _default_config()
        for cam in cfg.cameras:
            assert cam.subject_ontology, (
                f"{cam.role} has empty subject_ontology — round-robin "
                f"degeneracy regression. Audit 2026-05-02 §F2."
            )

    def test_every_role_has_a_classification(self) -> None:
        """All 6 production cameras present and accounted for."""
        cfg = _default_config()
        roles = {cam.role for cam in cfg.cameras}
        assert roles == EXPECTED_ROLES, (
            f"Production camera fleet mismatch: missing {EXPECTED_ROLES - roles}, "
            f"unexpected {roles - EXPECTED_ROLES}"
        )

    def test_subject_ontology_terms_are_known(self) -> None:
        """Vocabulary discipline: every ontology tag must be in
        ``KNOWN_ONTOLOGY_TERMS``. Adding a term requires touching this
        list, which makes the audit trail visible at PR time."""
        cfg = _default_config()
        for cam in cfg.cameras:
            for term in cam.subject_ontology:
                assert term in KNOWN_ONTOLOGY_TERMS, (
                    f"{cam.role} uses unknown ontology term {term!r}; "
                    f"add it to KNOWN_ONTOLOGY_TERMS or correct the spec"
                )

    def test_at_least_one_operator_visible_camera(self) -> None:
        """Privacy + scoring invariant: at least one camera flags
        ``operator_visible=True`` so the operator-visible bonus (0.3)
        ever has the opportunity to fire and so the privacy-aware code
        paths (face-obscure pipeline) have at least one consumer."""
        cfg = _default_config()
        n_visible = sum(1 for cam in cfg.cameras if cam.operator_visible)
        assert n_visible >= 1, "no operator-visible camera; privacy + scoring degenerate"

    def test_each_physical_position_present(self) -> None:
        """The studio inventory has cameras at desk, room, and overhead
        positions (memory project_studio_cameras). Each position must
        be reachable so the FollowModeController has somewhere to cut
        for each inferred operator location."""
        cfg = _default_config()
        roles = {cam.role for cam in cfg.cameras}
        # ``c920-desk`` is the operator-hands close shot.
        assert "c920-desk" in roles, "missing desk camera"
        # ``c920-room`` and ``brio-room`` between them cover the room.
        assert {"c920-room", "brio-room"} <= roles, "missing room camera"
        # ``c920-overhead`` is the canonical top-down shot.
        assert "c920-overhead" in roles, "missing overhead camera"

    def test_ambient_priority_spans_a_meaningful_range(self) -> None:
        """Audit §F2: when all cameras score at ``priority=5`` the
        repetition penalty is the only differentiator. Real spread
        in ``ambient_priority`` is what gives ``FollowModeController``
        something to score against once the location-match bonus
        and operator-visible bonus apply."""
        cfg = _default_config()
        priorities = [cam.ambient_priority for cam in cfg.cameras]
        assert max(priorities) - min(priorities) >= 3, (
            f"ambient_priority range too narrow ({min(priorities)}..{max(priorities)}): "
            f"score variance reduces to recency-penalty round-robin"
        )


class TestUserYamlClassificationOverlay:
    """``load_config`` must carry ``_DEFAULT_CAMERAS`` classification
    fields through onto YAML cameras whose YAML omits them. This is
    what fixed the live-system bug (audit §F2): user YAML at
    ``~/.config/hapax-compositor/config.yaml`` listed the cameras
    without classification fields, so pydantic filled them with
    bare-``CameraSpec`` defaults of ``unspecified``/``[]``/false.
    """

    def _write_classifications_free_yaml(self, path: Path) -> None:
        """Replicate the production user YAML failure mode: real
        cameras keyed by role, but no classification fields."""
        path.write_text(
            "cameras:\n"
            "- device: /dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0\n"
            "  height: 720\n"
            "  hero: true\n"
            "  input_format: mjpeg\n"
            "  role: brio-operator\n"
            "  width: 1280\n"
            "- device: /dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0\n"
            "  height: 720\n"
            "  input_format: mjpeg\n"
            "  role: c920-desk\n"
            "  width: 1280\n"
            "- device: /dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_86B6B75F-video-index0\n"
            "  height: 720\n"
            "  input_format: mjpeg\n"
            "  role: c920-room\n"
            "  width: 1280\n"
            "- device: /dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_7B88C71F-video-index0\n"
            "  height: 720\n"
            "  input_format: mjpeg\n"
            "  role: c920-overhead\n"
            "  width: 1280\n"
            "- device: /dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A-video-index0\n"
            "  height: 720\n"
            "  input_format: mjpeg\n"
            "  role: brio-room\n"
            "  width: 1280\n"
            "- device: /dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index0\n"
            "  height: 720\n"
            "  input_format: mjpeg\n"
            "  role: brio-synths\n"
            "  width: 1280\n",
            encoding="utf-8",
        )

    def test_load_config_overlays_classifications_for_known_roles(self, tmp_path: Path) -> None:
        """The whole point of the fix: a user YAML that lists known
        role names without classification fields must end up with the
        ``_DEFAULT_CAMERAS`` classifications for each role."""
        from agents.studio_compositor.config import load_config

        yaml_path = tmp_path / "config.yaml"
        self._write_classifications_free_yaml(yaml_path)
        cfg = load_config(path=yaml_path)

        by_role = {cam.role: cam for cam in cfg.cameras}
        # The audit's failure case: every camera was unspecified/[]/false.
        # The overlay must lift them to real values.
        for cam in cfg.cameras:
            assert cam.semantic_role != "unspecified", (
                f"{cam.role} still 'unspecified' after overlay"
            )
            assert cam.subject_ontology, (
                f"{cam.role} still has empty subject_ontology after overlay"
            )

        # Spot-check specific values match _DEFAULT_CAMERAS so we know
        # the merge actually picked them up by role.
        assert by_role["brio-operator"].semantic_role == "operator-face"
        assert by_role["brio-operator"].subject_ontology == ["person"]
        assert by_role["brio-operator"].operator_visible is True
        assert by_role["c920-overhead"].subject_ontology == ["hands", "mpc", "desk"]
        assert by_role["c920-overhead"].angle == "top-down"
        assert by_role["brio-synths"].subject_ontology == ["turntable", "vinyl"]

    def test_yaml_classification_wins_over_default(self, tmp_path: Path) -> None:
        """The overlay is fill-the-blanks, not clobber: when the YAML
        DOES specify a classification field, its value wins."""
        from agents.studio_compositor.config import load_config

        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "cameras:\n"
            "- role: brio-operator\n"
            "  device: /dev/video0\n"
            "  semantic_role: custom-override\n"
            "  subject_ontology: [custom-tag]\n"
            "  operator_visible: false\n"
            "  ambient_priority: 9\n",
            encoding="utf-8",
        )
        cfg = load_config(path=yaml_path)

        cam = cfg.cameras[0]
        assert cam.semantic_role == "custom-override"
        assert cam.subject_ontology == ["custom-tag"]
        assert cam.operator_visible is False
        assert cam.ambient_priority == 9

    def test_unknown_role_leaves_classifications_unspecified(self, tmp_path: Path) -> None:
        """Cameras whose role isn't in ``_DEFAULT_CAMERAS`` get the
        bare ``CameraSpec`` defaults — the overlay only matches by
        role and never fabricates classifications for unknown cameras."""
        from agents.studio_compositor.config import load_config

        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "cameras:\n- role: experimental-pi-cam\n  device: /dev/video99\n",
            encoding="utf-8",
        )
        cfg = load_config(path=yaml_path)

        cam = cfg.cameras[0]
        assert cam.semantic_role == "unspecified"
        assert cam.subject_ontology == []
        assert cam.operator_visible is False
