"""Tests for the parametric heartbeat's Cairo-ward extension (gap #26).

Validates:
- ward envelopes are loaded into the walker when ``include_ward_envelopes=True``
- the dispatcher splits ``ward.*`` keys from uniform keys correctly
- ``write_ward_property_overrides`` calls ``set_many_ward_properties`` with
  the right shape (alpha set, defaults preserved, TTL applied)
- ward keys never leak into ``uniforms.json``
- the walker still produces uniform-only values when the extension is opt-out
"""

from __future__ import annotations

import json
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import agents.parametric_modulation_heartbeat.heartbeat as hb
from agents.parametric_modulation_heartbeat.heartbeat import (
    ParameterWalker,
    tick_once,
    write_ward_property_overrides,
)
from shared.parameter_envelopes import (
    envelopes,
    ward_envelopes,
    ward_modulation_targets,
)


class TestWardEnvelopesShape(unittest.TestCase):
    """Static-shape pins on the ward envelope set."""

    def test_targets_are_curated_set_not_global_all(self) -> None:
        targets = ward_modulation_targets()
        self.assertNotIn(
            "all",
            targets,
            "global 'all' modulation is doctrine-banned (would be global pumping)",
        )
        self.assertGreater(len(targets), 0)
        # Bounded: not the entire ward registry
        self.assertLess(len(targets), 10, "curated set must stay small")

    def test_envelopes_only_modulate_alpha_not_z_index(self) -> None:
        # Per scope decision in shared/parameter_envelopes.py, the heartbeat
        # only modulates alpha. z_index_float is modulator-owned;
        # z_order_override is operator-set. Both deferred.
        for env in ward_envelopes():
            self.assertEqual(env.param_name, "alpha")

    def test_alpha_bounds_conservative(self) -> None:
        # Drift in [0.85, 1.0] is barely perceptible — the design goal.
        # Anything wider would risk visible global fade-in/out.
        for env in ward_envelopes():
            self.assertGreaterEqual(env.min_value, 0.7, "alpha floor too low")
            self.assertLessEqual(env.max_value, 1.0, "alpha ceiling above 1.0")
            self.assertLess(env.max_value - env.min_value, 0.2, "alpha range too wide")

    def test_each_target_has_exactly_one_envelope(self) -> None:
        # One envelope per target ward, only alpha (per scope decision).
        # This pin guards against accidental param duplication.
        targets = ward_modulation_targets()
        envs = ward_envelopes()
        self.assertEqual(len(envs), len(targets))
        env_keys = {e.key for e in envs}
        for ward_id in targets:
            self.assertIn(f"ward.{ward_id}.alpha", env_keys)


class TestWalkerIncludesWardEnvelopes(unittest.TestCase):
    """Walker integrates ward envelopes correctly."""

    def test_default_include_ward_envelopes_true(self) -> None:
        walker = ParameterWalker(rng=random.Random(42))
        ward_keys = [k for k in walker.values if k.startswith("ward.")]
        uniform_keys = [k for k in walker.values if not k.startswith("ward.")]
        self.assertEqual(len(ward_keys), len(ward_envelopes()))
        self.assertEqual(len(uniform_keys), len(envelopes()))

    def test_opt_out_excludes_ward_envelopes(self) -> None:
        walker = ParameterWalker(rng=random.Random(42), include_ward_envelopes=False)
        ward_keys = [k for k in walker.values if k.startswith("ward.")]
        self.assertEqual(len(ward_keys), 0)

    def test_explicit_envs_overrides_include_flag(self) -> None:
        # If caller supplies envs, include_ward_envelopes is ignored —
        # caller has full control.
        custom = envelopes()[:2]
        walker = ParameterWalker(envs=custom, include_ward_envelopes=True)
        self.assertEqual(len(walker.values), 2)


class TestDispatcherSeparatesSurfaces(unittest.TestCase):
    """ward.* keys go to ward-properties; uniform keys go to uniforms.json."""

    def test_ward_keys_never_leak_into_uniforms_json(self) -> None:
        walker = ParameterWalker(rng=random.Random(42), include_ward_envelopes=True)
        with tempfile.TemporaryDirectory() as td:
            upath = Path(td) / "uniforms.json"
            rpath = Path(td) / "rec.json"
            with mock.patch.object(hb, "write_ward_property_overrides"):
                tick_once(
                    walker,
                    now=time.time(),
                    uniforms_path=upath,
                    recruitment_path=rpath,
                    rng=random.Random(7),
                )
            payload = json.loads(upath.read_text())
            leaked = [k for k in payload if k.startswith("ward.")]
            self.assertEqual(leaked, [], "ward.* keys must not appear in uniforms.json")

    def test_ward_dispatcher_called_with_only_ward_keys(self) -> None:
        walker = ParameterWalker(rng=random.Random(42), include_ward_envelopes=True)
        captured: dict[str, float] = {}

        def fake_ward_write(values, **_kw):
            captured.update(values)

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(
                hb, "write_ward_property_overrides", side_effect=fake_ward_write
            ):
                tick_once(
                    walker,
                    now=time.time(),
                    uniforms_path=Path(td) / "uniforms.json",
                    recruitment_path=Path(td) / "rec.json",
                    rng=random.Random(7),
                )
        self.assertGreater(len(captured), 0, "ward dispatcher should be called")
        for key in captured:
            self.assertTrue(key.startswith("ward."), f"non-ward key passed: {key}")

    def test_no_ward_dispatch_when_walker_excludes_wards(self) -> None:
        # Walker without ward envelopes → ward dispatcher never called.
        walker = ParameterWalker(rng=random.Random(42), include_ward_envelopes=False)
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(hb, "write_ward_property_overrides") as m:
                tick_once(
                    walker,
                    now=time.time(),
                    uniforms_path=Path(td) / "uniforms.json",
                    recruitment_path=Path(td) / "rec.json",
                    rng=random.Random(7),
                )
                m.assert_not_called()


class TestWriteWardPropertyOverrides(unittest.TestCase):
    """The ward-property write helper builds correct WardProperties."""

    def test_empty_input_is_noop(self) -> None:
        with mock.patch("agents.studio_compositor.ward_properties.set_many_ward_properties") as m:
            write_ward_property_overrides({})
            m.assert_not_called()

    def test_only_ward_prefix_keys_are_dispatched(self) -> None:
        with mock.patch("agents.studio_compositor.ward_properties.set_many_ward_properties") as m:
            write_ward_property_overrides(
                {
                    "noise.frequency_x": 1.5,  # uniform key — must skip
                    "ward.chronicle_ticker.alpha": 0.9,
                }
            )
        m.assert_called_once()
        # set_many_ward_properties signature: (properties_by_ward, ttl_s)
        passed_props = (
            m.call_args.args[0]
            if m.call_args.args
            else m.call_args.kwargs.get("properties_by_ward")
        )
        self.assertIn("chronicle_ticker", passed_props)
        self.assertNotIn("noise", str(passed_props))

    def test_alpha_clamped_to_unit_interval(self) -> None:
        with mock.patch("agents.studio_compositor.ward_properties.set_many_ward_properties") as m:
            write_ward_property_overrides(
                {
                    "ward.chronicle_ticker.alpha": 1.5,  # above 1.0
                    "ward.programme-history.alpha": -0.2,  # below 0.0
                }
            )
        passed_props = (
            m.call_args.args[0]
            if m.call_args.args
            else m.call_args.kwargs.get("properties_by_ward")
        )
        self.assertEqual(passed_props["chronicle_ticker"].alpha, 1.0)
        self.assertEqual(passed_props["programme-history"].alpha, 0.0)

    def test_hyphenated_ward_id_parsed_correctly(self) -> None:
        # programme-history has a hyphen — verify the rsplit doesn't
        # accidentally split on the hyphen.
        with mock.patch("agents.studio_compositor.ward_properties.set_many_ward_properties") as m:
            write_ward_property_overrides({"ward.programme-history.alpha": 0.93})
        passed_props = (
            m.call_args.args[0]
            if m.call_args.args
            else m.call_args.kwargs.get("properties_by_ward")
        )
        self.assertIn("programme-history", passed_props)
        self.assertAlmostEqual(passed_props["programme-history"].alpha, 0.93)

    def test_ttl_passed_through(self) -> None:
        with mock.patch("agents.studio_compositor.ward_properties.set_many_ward_properties") as m:
            write_ward_property_overrides({"ward.chronicle_ticker.alpha": 0.9}, ttl_s=42.0)
        passed_ttl = m.call_args.kwargs.get("ttl_s") or (
            m.call_args.args[1] if len(m.call_args.args) > 1 else None
        )
        self.assertEqual(passed_ttl, 42.0)

    def test_malformed_keys_skipped(self) -> None:
        with mock.patch("agents.studio_compositor.ward_properties.set_many_ward_properties") as m:
            # ``ward.no_param`` has no param suffix — must skip without raising
            write_ward_property_overrides(
                {
                    "ward.no_param": 0.5,
                    "ward.chronicle_ticker.alpha": 0.9,
                }
            )
        passed_props = (
            m.call_args.args[0]
            if m.call_args.args
            else m.call_args.kwargs.get("properties_by_ward")
        )
        self.assertEqual(set(passed_props.keys()), {"chronicle_ticker"})


if __name__ == "__main__":
    unittest.main()
