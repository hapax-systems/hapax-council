"""Persistent ALSA card-id udev rules contract tests.

The rules at config/udev/rules.d/50-hapax-alsa-card-ids.rules pin every
USB-Audio device to a stable symbolic ALSA card id (`hw:CARD=L12` etc.).
These tests assert the rule file's structural invariants:

- All expected vendor:product pairs are covered.
- Every rule that sets ATTR{id} also constrains both vid and pid.
- Multi-instance device classes (BRIO, C920) additionally constrain by
  ATTRS{serial} so rules don't collide.
- Card ids are unique across the rule set.
- audio-topology.yaml's hw: fields use the symbolic CARD= form rather
  than fragile numeric indices.

Today's incident (2026-05-02) burned the operator with hw:11 → hw:12 drift
across reboots; these tests pin the regression-fix surface.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES = REPO_ROOT / "config" / "udev" / "rules.d" / "50-hapax-alsa-card-ids.rules"
AUDIO_TOPOLOGY = REPO_ROOT / "config" / "audio-topology.yaml"
SHOW_CARDS_SCRIPT = REPO_ROOT / "scripts" / "hapax-show-stable-card-ids"

# Devices that MUST appear in the rule file. Each tuple is
# (vendor, product, expected_card_id, requires_serial_match).
EXPECTED_DEVICES: tuple[tuple[str, str, str, bool], ...] = (
    ("1686", "03d5", "L12", False),
    ("1d6b", "0104", "S4", True),  # serial fedcba9876543220*
    ("b58e", "9e84", "Yeti", False),
    ("16c0", "048a", "M8", False),
    ("2886", "001a", "XVF3800", False),  # Seeed firmware
    ("20b1", "4f00", "XVF3800", False),  # XMOS 48 kHz reference firmware
    ("20b1", "4f01", "XVF3800", False),  # XMOS 16 kHz reference firmware
    ("381a", "1003", "Dispatch", False),
)

# Logitech webcam serials we expect pinned in the rule set.
EXPECTED_BRIO_SERIALS = ("43B0576A", "5342C819", "9726C031")
EXPECTED_C920_SERIALS = ("2657DFCF", "7B88C71F", "86B6B75F")


def _rule_lines() -> list[str]:
    text = RULES.read_text(encoding="utf-8")
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _id_assignments() -> list[tuple[str, str]]:
    """Return list of (line, card_id) for every rule that sets ATTR{id}."""
    pattern = re.compile(r'ATTR\{id\}="([^"]+)"')
    matches: list[tuple[str, str]] = []
    for line in _rule_lines():
        m = pattern.search(line)
        if m:
            matches.append((line, m.group(1)))
    return matches


def test_rule_file_exists() -> None:
    assert RULES.exists(), f"missing udev rules at {RULES}"
    text = RULES.read_text(encoding="utf-8")
    assert "Persistent ALSA card IDs" in text, "rule banner missing"


def test_subsystem_gate_is_present() -> None:
    """The rule file must short-circuit on non-sound events."""
    text = RULES.read_text(encoding="utf-8")
    assert 'SUBSYSTEM!="sound"' in text
    assert 'GOTO="hapax_card_ids_end"' in text
    assert 'LABEL="hapax_card_ids_end"' in text


def test_action_filter_is_add_or_change() -> None:
    """udev fires sound events on add and change; we want both."""
    text = RULES.read_text(encoding="utf-8")
    assert 'ACTION!="add|change"' in text


def test_all_expected_devices_have_a_pinned_id() -> None:
    text = RULES.read_text(encoding="utf-8")
    for vendor, product, card_id, _requires_serial in EXPECTED_DEVICES:
        # The vendor and product must both appear on the same rule line that
        # pins the card id. We assert by looking for a line containing all
        # three tokens.
        match = False
        for line, found_id in _id_assignments():
            if (
                f'ATTRS{{idVendor}}=="{vendor}"' in line
                and f'ATTRS{{idProduct}}=="{product}"' in line
                and found_id == card_id
            ):
                match = True
                break
        assert match, f"no rule pins {vendor}:{product} -> {card_id} (text:\n{text})"


def test_each_id_rule_has_both_vendor_and_product() -> None:
    """A rule with ATTR{id}=... but no idProduct would be too broad and
    would collide if the same vendor ships another USB-Audio device."""
    for line, card_id in _id_assignments():
        assert "ATTRS{idVendor}==" in line, f"rule for {card_id} missing idVendor: {line}"
        assert "ATTRS{idProduct}==" in line, f"rule for {card_id} missing idProduct: {line}"


def test_card_ids_are_unique() -> None:
    ids = [cid for _, cid in _id_assignments()]
    seen = set()
    duplicates: list[str] = []
    for cid in ids:
        if cid in seen and cid not in {"C920a", "C920b", "C920c", "XVF3800"}:
            # C920a/b/c each appear twice (once for 082d, once for 08e5)
            # because the C920 plain and C920 PRO share the same serial pool.
            # XVF3800 appears under multiple possible firmware IDs. Both are
            # intentional aliases, not collisions between distinct devices.
            duplicates.append(cid)
        seen.add(cid)
    assert not duplicates, f"duplicate card ids: {duplicates}"


def test_card_ids_are_short_enough_for_alsa() -> None:
    """ALSA truncates card ids beyond 15 chars; rule must respect the cap."""
    for line, card_id in _id_assignments():
        assert len(card_id) <= 15, f"card id {card_id!r} too long ({len(card_id)} > 15): {line}"


def test_brio_rules_match_by_serial() -> None:
    """Three BRIOs share vid:pid 046d:085e; rules must pin by serial."""
    text = RULES.read_text(encoding="utf-8")
    for serial in EXPECTED_BRIO_SERIALS:
        assert f'ATTRS{{serial}}=="{serial}"' in text, f"BRIO serial {serial} not pinned"
    # Each BRIO must have a distinct id (Brio0/1/2).
    brio_lines = [
        line
        for line, _ in _id_assignments()
        if "046d" in line and "085e" in line and "ATTRS{serial}" in line
    ]
    assert len(brio_lines) == 3, f"expected 3 BRIO rules, got {len(brio_lines)}: {brio_lines}"
    brio_ids = sorted(
        cid
        for line, cid in _id_assignments()
        if "046d" in line and "085e" in line and "ATTRS{serial}" in line
    )
    assert brio_ids == ["Brio0", "Brio1", "Brio2"]


def test_c920_rules_match_by_serial_across_both_pids() -> None:
    """C920 plain (082d) and C920 PRO (08e5) are different hardware
    revisions but the operator's three units have stable serials. Rules
    must pin each serial under both pids so a unit replaced with the
    other revision keeps its symbolic id."""
    text = RULES.read_text(encoding="utf-8")
    for serial in EXPECTED_C920_SERIALS:
        assert f'ATTRS{{serial}}=="{serial}"' in text, f"C920 serial {serial} not pinned"
    # Each serial should appear in two rules — one per pid.
    for serial in EXPECTED_C920_SERIALS:
        count = text.count(f'ATTRS{{serial}}=="{serial}"')
        assert count == 2, f"C920 serial {serial} should map under both 082d and 08e5; got {count}"


def test_audio_topology_yaml_uses_symbolic_card_ids() -> None:
    """The hw: fields in audio-topology.yaml must use hw:CARD=<id> form,
    not fragile numeric indices like hw:11 or hw:14."""
    text = AUDIO_TOPOLOGY.read_text(encoding="utf-8")
    # Every hw: assignment that references a USB-Audio card should be
    # symbolic. Allow `hw:M8,0` (already symbolic) and `hw:CARD=...`.
    bad_pattern = re.compile(r"^\s*hw:\s+(?:hw|surround\d+|front):\d+", re.MULTILINE)
    bad_matches = bad_pattern.findall(text)
    assert not bad_matches, f"audio-topology.yaml still has numeric hw indices: {bad_matches}"

    # And the expected symbolic forms must be present.
    assert "hw:CARD=L12" in text
    assert "surround40:CARD=L12" in text
    assert "front:CARD=Yeti" in text
    assert "hw:CARD=S4" in text
    assert "hw:CARD=XVF3800" in text


def test_audio_topology_schema_version_bumped_for_symbolic_migration() -> None:
    text = AUDIO_TOPOLOGY.read_text(encoding="utf-8")
    assert ("schema_version: 2" in text) or ("schema_version: 3" in text), (
        "schema_version must be bumped for symbolic-id migration"
    )


def test_show_cards_script_exists_and_is_executable() -> None:
    assert SHOW_CARDS_SCRIPT.exists(), f"missing helper at {SHOW_CARDS_SCRIPT}"
    mode = SHOW_CARDS_SCRIPT.stat().st_mode
    assert mode & 0o111, f"{SHOW_CARDS_SCRIPT} is not executable (mode={oct(mode)})"
    text = SHOW_CARDS_SCRIPT.read_text(encoding="utf-8")
    assert "/proc/asound/cards" in text
    # Script should warn when the udev rules are not yet installed.
    assert "udev" in text.lower()


def test_governance_doc_exists_and_describes_install_steps() -> None:
    doc = REPO_ROOT / "docs" / "governance" / "persistent-alsa-card-ids.md"
    assert doc.exists(), f"missing governance doc at {doc}"
    text = doc.read_text(encoding="utf-8")
    # Must reference the install steps so operator can act on it.
    assert "udevadm control" in text
    assert "udevadm trigger" in text
    assert "/etc/udev/rules.d/" in text
    # And reference today's incident as motivation.
    assert "2026-05-02" in text
