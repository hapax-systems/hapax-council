# Audio Source Activation Rollback Guard AVSDLC Release Dossier

## Impacted Axes

| Axis | Impact | Rationale |
|---|---|---|
| Audio | Yes | The change controls private/director voice routing and source-activation rollback behavior for audio-critical files. |
| Visual | No | `agents/studio_compositor/director_loop.py` is touched only in the `_play_audio` method. No frame, layout, shader, camera, overlay, or raster output semantics change. |
| Audiovisual | No | No timing relationship between rendered visuals and audio events changes. |

## Standards

- AVSDLC audio evidence contract: signal-chain integrity and no unintended broadcast/private crossfeed.
- Hapax audio topology invariant: private/director audio must not fall back to default, multimedia, L-12, MPC broadcast, or livestream paths.
- Source activation invariant: a dirty active-source worktree containing audio-critical runtime hotfixes must not be reset silently.

## Failure Predicates

- Director private playback uses `input.loopback.sink.role.assistant` or another default/legacy fallback when `private_monitor` is unavailable.
- `config/voice-output-routes.yaml` maps assistant, private monitor, or notification roles to a public/broadcast/default sink.
- `hapax-source-activate` resets or deploys over dirty audio-critical active-source drift without a held receipt.
- Runtime private/director leakage appears in `scripts/audio-leak-guard.sh`.

## Evidence

- `uv run pytest tests/scripts/test_hapax_source_activate.py tests/studio_compositor/test_director_voice_role_routing.py tests/shared/test_voice_output_router_role_api.py -q` passed: 30 tests.
- `uv run pytest tests/scripts/test_hapax_audio_routing_check.py tests/scripts/test_audio_leak_guard.py tests/shared/test_voice_output_router.py tests/shared/test_voice_output_router_role_api.py tests/studio_compositor/test_director_voice_role_routing.py -q` passed: 61 tests.
- `uv run ruff check tests/scripts/test_hapax_source_activate.py tests/studio_compositor/test_director_voice_role_routing.py tests/shared/test_voice_output_router_role_api.py agents/studio_compositor/director_loop.py` passed.
- `uv run ruff format --check tests/scripts/test_hapax_source_activate.py tests/studio_compositor/test_director_voice_role_routing.py tests/shared/test_voice_output_router_role_api.py` passed.
- `bash -n scripts/hapax-source-activate` passed.
- `scripts/audio-leak-guard.sh` passed live with no leak risk.
- Live `hapax-source-activate` guard was run with a temporary state directory and no HOLD file; it exited before reset/deploy with `deploy_status=skipped_audio_critical_drift`, naming the dirty audio-critical files.
- Live `hapax-source-activate.service` was run with the HOLD present; it exited 0 with `deploy_status=skipped_hold`.

## Residual Risk

Full live `scripts/hapax-audio-routing-check` remains red for pre-existing runtime drift: WirePlumber deny runtime/source mismatch and L-12 AUX8-11 / evilpet return completeness. This dossier does not certify the full audio graph as green; it certifies that this patch prevents rollback of the private/director route hotfix and preserves fail-closed behavior.
