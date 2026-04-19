"""HOMAGE Phase 9 (task #115) — PerceptualField.homage reader tests.

Pins the four SHM read paths that feed ``HomageField`` under the new
research condition ``cond-phase-a-homage-active-001``:

- ``/dev/shm/hapax-compositor/homage-substrate-package.json`` → ``package_name``
- ``/dev/shm/hapax-compositor/homage-active-artefact.json`` → ``active_artefact_form``
- ``/dev/shm/hapax-compositor/homage-voice-register.json`` → ``voice_register``
- ``/dev/shm/hapax-compositor/consent-safe-active.json`` (existence) → ``consent_safe_active``

Every sub-read is fail-open: missing or malformed input yields the
default field value, never a crash — the director's hot path must
survive HOMAGE being dormant.
"""

from __future__ import annotations

import json

import shared.perceptual_field as pf
from shared.perceptual_field import HomageField, build_perceptual_field

# ── HomageField schema ────────────────────────────────────────────────────


class TestHomageFieldDefaults:
    def test_all_fields_default_to_none_or_false(self):
        field = HomageField()
        assert field.package_name is None
        assert field.active_artefact_form is None
        assert field.voice_register is None
        assert field.consent_safe_active is False

    def test_roundtrip_serialization(self):
        field = HomageField(
            package_name="bitchx",
            active_artefact_form="quit-quip",
            voice_register="textmode",
            consent_safe_active=True,
        )
        restored = HomageField.model_validate_json(field.model_dump_json())
        assert restored == field


# ── SHM reads ─────────────────────────────────────────────────────────────


class TestHomageReadFromShm:
    def test_missing_files_yield_defaults(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        field = build_perceptual_field()
        assert field.homage.package_name is None
        assert field.homage.active_artefact_form is None
        assert field.homage.voice_register is None
        assert field.homage.consent_safe_active is False

    def test_substrate_package_populates_package_name(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        substrate = tmp_path / "homage-substrate-package.json"
        substrate.write_text(
            json.dumps(
                {
                    "package": "bitchx",
                    "palette_accent_hue_deg": 180.0,
                    "custom_slot_index": 4,
                    "substrate_source_ids": ["reverie"],
                }
            )
        )
        field = build_perceptual_field()
        assert field.homage.package_name == "bitchx"

    def test_artefact_form_read_from_artefact_file(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        artefact = tmp_path / "homage-active-artefact.json"
        artefact.write_text(
            json.dumps(
                {
                    "package": "bitchx",
                    "content": "Hapax: cognition at 20Hz",
                    "form": "quit-quip",
                    "author_tag": "by Hapax",
                    "weight": 1.0,
                }
            )
        )
        field = build_perceptual_field()
        assert field.homage.active_artefact_form == "quit-quip"

    def test_voice_register_read(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        register = tmp_path / "homage-voice-register.json"
        register.write_text(
            json.dumps({"register": "textmode", "package": "bitchx", "updated_at": 2.0})
        )
        field = build_perceptual_field()
        assert field.homage.voice_register == "textmode"

    def test_consent_safe_flag_file_presence(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        flag = tmp_path / "consent-safe-active.json"
        flag.write_text(json.dumps({"active": True}))
        field = build_perceptual_field()
        assert field.homage.consent_safe_active is True

    def test_consent_safe_swap_preserves_package_name(self, monkeypatch, tmp_path):
        """When consent-safe engages, the choreographer rewrites the
        substrate-package file with ``bitchx_consent_safe``; the
        reader surfaces that exact string so the director can
        distinguish the swap without reading the flag file."""
        _redirect_paths(monkeypatch, tmp_path)
        substrate = tmp_path / "homage-substrate-package.json"
        substrate.write_text(json.dumps({"package": "bitchx_consent_safe"}))
        flag = tmp_path / "consent-safe-active.json"
        flag.write_text(json.dumps({"active": True}))
        field = build_perceptual_field()
        assert field.homage.package_name == "bitchx_consent_safe"
        assert field.homage.consent_safe_active is True

    def test_all_four_fields_populated(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        (tmp_path / "homage-substrate-package.json").write_text(json.dumps({"package": "bitchx"}))
        (tmp_path / "homage-active-artefact.json").write_text(
            json.dumps(
                {
                    "package": "bitchx",
                    "content": "Connection reset by Bachelard",
                    "form": "kick-reason",
                    "author_tag": "by Hapax",
                }
            )
        )
        (tmp_path / "homage-voice-register.json").write_text(json.dumps({"register": "announcing"}))
        (tmp_path / "consent-safe-active.json").write_text(json.dumps({}))
        field = build_perceptual_field()
        assert field.homage.package_name == "bitchx"
        assert field.homage.active_artefact_form == "kick-reason"
        assert field.homage.voice_register == "announcing"
        assert field.homage.consent_safe_active is True


# ── Graceful degradation on bad input ─────────────────────────────────────


class TestHomageGracefulDegradation:
    def test_malformed_substrate_file_yields_none(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        substrate = tmp_path / "homage-substrate-package.json"
        substrate.write_text("not-json-at-all {")
        field = build_perceptual_field()
        assert field.homage.package_name is None

    def test_substrate_file_missing_package_key(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        substrate = tmp_path / "homage-substrate-package.json"
        substrate.write_text(json.dumps({"palette_accent_hue_deg": 180.0}))
        field = build_perceptual_field()
        assert field.homage.package_name is None

    def test_empty_string_package_treated_as_none(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        substrate = tmp_path / "homage-substrate-package.json"
        substrate.write_text(json.dumps({"package": ""}))
        field = build_perceptual_field()
        assert field.homage.package_name is None

    def test_non_string_register_ignored(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        register = tmp_path / "homage-voice-register.json"
        register.write_text(json.dumps({"register": 42}))
        field = build_perceptual_field()
        assert field.homage.voice_register is None

    def test_malformed_artefact_yields_none_form(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        artefact = tmp_path / "homage-active-artefact.json"
        artefact.write_text("]][[not valid json")
        field = build_perceptual_field()
        assert field.homage.active_artefact_form is None

    def test_consent_safe_false_when_flag_absent(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        # Populate everything else, leave consent-safe flag out.
        (tmp_path / "homage-substrate-package.json").write_text(json.dumps({"package": "bitchx"}))
        field = build_perceptual_field()
        assert field.homage.consent_safe_active is False


# ── Roundtrip through PerceptualField ─────────────────────────────────────


class TestPerceptualFieldRoundtrip:
    def test_homage_field_survives_model_dump_roundtrip(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        (tmp_path / "homage-substrate-package.json").write_text(json.dumps({"package": "bitchx"}))
        (tmp_path / "homage-voice-register.json").write_text(json.dumps({"register": "textmode"}))
        field = build_perceptual_field()
        text = field.model_dump_json(exclude_none=True)
        # package_name and voice_register must appear in the grounding
        # provenance payload the director consumes.
        assert "bitchx" in text
        assert "textmode" in text


# ── Fixtures helpers ──────────────────────────────────────────────────────


def _redirect_paths(monkeypatch, tmp_path):
    """Redirect every PerceptualField source path at ``tmp_path``.

    Keeps the homage reader's source paths under ``tmp_path`` so tests
    control exactly which files exist. All other source paths are also
    redirected to avoid polluting the homage reads with ambient state.
    """
    monkeypatch.setattr(pf, "_PERCEPTION_STATE", tmp_path / "perception-state.json")
    monkeypatch.setattr(pf, "_STIMMUNG_STATE", tmp_path / "stimmung-state.json")
    monkeypatch.setattr(pf, "_ALBUM_STATE", tmp_path / "album-state.json")
    monkeypatch.setattr(pf, "_CHAT_STATE", tmp_path / "chat-state.json")
    monkeypatch.setattr(pf, "_CHAT_RECENT", tmp_path / "chat-recent.json")
    monkeypatch.setattr(pf, "_STREAM_LIVE", tmp_path / "stream-live")
    monkeypatch.setattr(pf, "_PRESENCE_STATE", tmp_path / "presence-state.json")
    monkeypatch.setattr(pf, "_WORKING_MODE", tmp_path / "working-mode")
    monkeypatch.setattr(pf, "_CONSENT_CONTRACTS_DIR", tmp_path / "contracts")
    monkeypatch.setattr(pf, "_OBJECTIVES_DIR", tmp_path / "objectives")
    monkeypatch.setattr(pf, "_read_stream_mode", lambda: None)
    # HOMAGE SHM paths (task #115).
    monkeypatch.setattr(pf, "_HOMAGE_ACTIVE_ARTEFACT", tmp_path / "homage-active-artefact.json")
    monkeypatch.setattr(pf, "_HOMAGE_VOICE_REGISTER", tmp_path / "homage-voice-register.json")
    monkeypatch.setattr(pf, "_HOMAGE_SUBSTRATE_PACKAGE", tmp_path / "homage-substrate-package.json")
    monkeypatch.setattr(pf, "_HOMAGE_CONSENT_SAFE_FLAG", tmp_path / "consent-safe-active.json")
