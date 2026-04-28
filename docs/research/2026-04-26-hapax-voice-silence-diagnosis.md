# Hapax Voice Silence Diagnosis — 2026-04-26

**Investigated at:** 2026-04-26T08:08Z (Apr 26 03:08 CDT)
**Operator report:** "haven't heard hapax on the stream for a loooong time (an hour or more)"
**Status at investigation:** READ-ONLY. No services restarted, no config mutated.

## Root cause

**`hapax-daimonion.service` is in a continuous restart loop, ~every 15 minutes for 8+ hours.** Each restart consumes 80–150 s of cold-start time before the daimonion can produce a single TTS frame. The cold-start window plus inter-restart steady-state is shorter than the typical idle gap between spontaneous-speech triggers, so the operator never hears the voice come up before health-monitor kills it again.

**The trigger** is a stale exploration-writer probe in `agents/health_monitor/checks/exploration.py`:

- The check expects 13 components to publish `/dev/shm/hapax-exploration/{component}.json`.
- 12 are present and fresh (mtime within seconds of now).
- **`voice_state.json` is absent** — and *no module in `agents/hapax_daimonion/` ever calls `publish_exploration_signal("voice_state", ...)`.* The expected-writer entry was added in PR #1070 (commit `ef539334f`, 2026-04-18) but the producing call was never wired in daimonion.
- The check returns `Status.DEGRADED` with remediation `systemctl --user restart hapax-daimonion` on every tick.
- `health-monitor.timer` fires every ~15 min. The fix-pipeline (`shared/fix_capabilities/pipeline.py`) recognises `systemctl --user restart [\w@.\-]+` as a `_SAFE_REMEDIATION_PATTERN` and either (a) the LLM evaluator approves the restart, or (b) a transient LiteLLM blip drops it into the deterministic fallback path — *both branches execute the same command*. The 02:33 LiteLLM "Connection error" we see in the logs flipped it to (b) once, but the loop runs identically when LiteLLM is healthy.

The `voice-state.json` confusion is real: there are **two** files with similar names. The one DuckController polls (`/dev/shm/hapax-compositor/voice-state.json`, written by `tts_state_publisher.py` since PR f1f9ccef2) is fresh and intact. The one health-monitor checks (`/dev/shm/hapax-exploration/voice_state.json`, expected per `COMPONENT_OWNERS["voice_state"] = "hapax-daimonion"`) is the missing-writer.

## Top remediation candidates (ranked)

### 1. STOP the restart loop immediately (one-line, READ-ONLY for diagnosis owner — operator runs)

```fish
systemctl --user disable health-monitor.timer ; systemctl --user stop health-monitor.timer
```

This pauses the 15-min health-monitor sweep. Daimonion's last restart at 03:04:25 CDT then completes its full warm-up (~2 min) and stays up. Voice should resume within ~3 minutes. Re-enable later with `systemctl --user enable --now health-monitor.timer` *after* a fix lands.

### 2. Permanent fix — wire the missing writer (operator decision)

Add a `publish_exploration_signal("voice_state", ...)` call in daimonion (matching the pattern in `agents/visual_layer_aggregator/aggregator.py` for `stimmung`). One file change, ≤ 10 lines, plus a regression-pin test mirroring the PR #1070 stimmung fix. This is the SPLATTRIBUTION/voice-state wiring that PR #1070 implicitly assumed but didn't ship.

### 3. Defensive fix — let voice_state legitimately be absent

The check comment at `exploration.py:87` already says `# Missing file: some components (voice_state) may legitimately be absent when their subsystem is disabled, so use DEGRADED not FAILED`. The intent was for `voice_state` to be optional. But `Status.DEGRADED` is still treated as "needs fix" by the auto-remediation pipeline. Either drop `voice_state` from `COMPONENT_OWNERS`, or change the check to return `Status.OK` when `voice_state.json` is absent.

## Evidence trail

### Restart loop (last 90 minutes, all systemd-driven, deliberate stops not crashes)

```
Apr 26 02:32:41  daimonion[1019084] starts
Apr 26 02:48:05  health-monitor[1459911]: [WARN] exploration_voice_state ... Writer absent
Apr 26 02:48:39  health-monitor:        [OK] exploration_voice_state: Executed: systemctl --user restart hapax-daimonion
Apr 26 02:48:29  daimonion[1472267] starts (PID change)
Apr 26 02:57:06  systemd: Stopping Hapax Daimonion ...
Apr 26 02:57:21  systemd: Started Hapax Daimonion (PID 2956146)
Apr 26 02:59:34  systemd: Stopping (again, 2 min later)
Apr 26 02:59:47  systemd: Stopped, restarting (PID 3043011)
Apr 26 03:04:10  health-monitor[3132105]: [WARN] exploration_voice_state ... Writer absent
Apr 26 03:04:10  systemd: Stopping Hapax Daimonion
Apr 26 03:04:25  systemd: Started (PID 3150700, current)
Apr 26 03:04:44  Kokoro TTS ready (voice=af_heart)
Apr 26 03:05:04  Signal cache: 12/12 presynthesized in 19.9s
Apr 26 03:05:14  workspace_monitor running
[next health-monitor tick scheduled for 03:19:09 CDT]
```

Same restart-then-restart pattern back to **at least 19:17 CDT (Apr 25)** — verified via `journalctl --since '8 hours ago'`. Cold-start cost per restart:

- ExecStartPre `sleep 10` (intentional, lets logos-api init)
- Backend init ~10 s (PipeWire, IR, contact mic, watch, BT, …)
- Kokoro TTS preload ~5 s + warning `Defaulting repo_id to hexgrad/Kokoro-82M`
- CPAL signal cache pre-synthesize 12–21 s
- Bridge phrases pre-synthesize **52–103 s** (slowest path)
- *Total before steady-state: ~80–150 s.* On a 15-min restart cadence the daemon spends 9–17% of every cycle in cold start.

### Health-monitor probe (the trigger)

```
File: ~/projects/hapax-council/agents/health_monitor/checks/exploration.py
Line 50:  "voice_state": "hapax-daimonion",  (in COMPONENT_OWNERS)
Line 86–98: when path missing → Status.DEGRADED + remediation "systemctl --user restart hapax-daimonion"
```

Live state of `/dev/shm/hapax-exploration/`:

```
affordance_pipeline.json    fresh (mtime 03:07)
apperception.json           fresh
contact_mic.json            fresh
content_resolver.json       fresh
dmn_imagination.json        03:05 (slightly stale but not dead)
dmn_pulse.json              fresh
input_activity.json         fresh
ir_presence.json            fresh
salience_router.json        fresh
stimmung.json               fresh
temporal_bands.json         fresh
visual_chain.json           fresh
voice_state.json            *** ABSENT ***
```

`grep -rE 'publish_exploration_signal' ~/projects/hapax-council/agents/hapax_daimonion/ --include="*.py"` returns **zero results**. The producer side was never wired.

### Auto-remediation pipeline confirms the SAFE pattern fires unconditionally

```
File: ~/projects/hapax-council/shared/fix_capabilities/pipeline.py
Line 30–43: _SAFE_REMEDIATION_PATTERNS includes:
  re.compile(r"^systemctl --user (start|restart|reset-failed|enable --now) [\w@.\-]+$")

→ "systemctl --user restart hapax-daimonion" matches.
→ When LLM evaluator is up:    LLM approves the safe remediation.
→ When LLM evaluator is down:  _run_deterministic_fix() executes it directly with
                                rationale "LLM evaluator unavailable; executing safe remediation"
```

Both the LLM-up path and the LLM-down path execute the same command. The 02:33 LiteLLM transient (`litellm.InternalServerError - Connection error`) was a red herring — the restart loop runs identically when LiteLLM is healthy.

### Full TTS path is wired correctly (verified — not the cause)

PipeWire link graph end-to-end traversal confirms TTS-to-L-12 routing is intact:

```
hapax-voice-fx-capture (Audio/Sink)
  → hapax-voice-fx-playback:output_FL/FR
  → hapax-loudnorm-capture:playback_FL/FR
  → hapax-loudnorm-playback:output_FL/FR
  → hapax-tts-duck:playback_FL/FR
  → hapax-tts-duck-playback:output_RL/RR
  → alsa_output.usb-ZOOM_Corporation_L-12...analog-surround-40:playback_RL/RR
```

L-12 is reachable, the voice-fx chain is alive, the TTS-duck is wired. No node is suspended. Compositor `voice-state.json` is fresh (`{"operator_speech_active": false}`). LiteLLM container is healthy NOW (200s flowing on `/chat/completions`). Consent state is `no_guest, persistence_allowed: true` — no consent gate blocking. Chat signals are nominal. CPAL impingement consumer is caught up (cursor 147046 = bus head 147046). CPAL is resolving destinations (`destination=livestream source=...`) at >1 Hz — but each restart loses the CPAL runtime state before TTS actually fires.

### Last actually-spoken event

Chronicle API returned only 1 item; no `cpal`/`tts`/`speech` chronicle entries in the queried window. CPAL "destination resolved" lines are abundant but no `synthesize` / `Kokoro produced` / `played to voice-fx` log lines after the restart loop began (8+ hours ago).

## What to check next if disabling the timer doesn't restore voice

1. **Confirm Kokoro is actually emitting samples** — after daimonion warms up, watch `journalctl --user -u hapax-daimonion -f | grep -iE "synthesize|voice-fx|delivered"`. If CPAL keeps "destination resolved" but never "synthesize", the cold-start window is being interrupted again from a *different* path (e.g. another auto-remediation, a rebuild-services timer, oom-killer, etc.).
2. **Check fix-pipeline runner separately** — the auto-remediation could conceivably run from another entry point. `journalctl --user --since '30 min ago' | grep "Executed: systemctl --user restart hapax-daimonion"` will catch any other invoker.
3. **Verify LiteLLM is healthy continuously** — flapping 200/connection-error would still cause some slow LLM-grounded paths in CPAL to silently abort. Watch `docker logs -f litellm | grep -iE "error|429|timeout"`.
4. **VRAM contention check** — daimonion's Kokoro loads onto GPU 0 (5060 Ti) per `gpu-pin.conf`. If hapax-imagination or compositor on the same card spike during a TTS attempt, NeMo/Kokoro can stall silently. `gpu-audit` skill or `nvidia-smi --query-compute-apps`.
5. **TTS server hang** — `tts_server.py` UDS could be hung from a previous session. Watch for `tts-server` listening at `/run/user/1000/hapax-tts.sock` (or wherever it binds). One ERROR was logged at 02:59:43: `Task was destroyed but it is pending! task: <Task pending name='Task-41' coro=<TtsServer._handle_client()`.
6. **Consider Restart=always backoff window** — `RestartSec=10` + `StartLimitBurst=8 / IntervalSec=600` means ~8 restarts per 10 min puts the unit in a `start-limit-hit` state. We're well within burst limits at 1 restart per 15 min, but worth checking `systemctl --user status hapax-daimonion --no-pager -l` for `start-limit-hit` text.

## File / line references

- `agents/health_monitor/checks/exploration.py:37–51` — `COMPONENT_OWNERS` (the bad entry is line 50)
- `agents/health_monitor/checks/exploration.py:86–98` — DEGRADED-on-missing branch (correct)
- `shared/fix_capabilities/pipeline.py:30–44` — `_SAFE_REMEDIATION_PATTERNS`
- `shared/fix_capabilities/pipeline.py:62–78` — `_run_deterministic_fix` (the LLM-down fallback)
- `shared/exploration_writer.py` — `publish_exploration_signal()` (the function daimonion never calls for `voice_state`)
- `~/.config/systemd/user/hapax-daimonion.service` — main unit, `Restart=always RestartSec=10 StartLimitBurst=8 StartLimitIntervalSec=600`
- `~/.config/systemd/user/hapax-daimonion.service.d/{aec,gpu-pin,opt-in-all,override,zz-capacity}.conf` — drop-ins, none implicated
- `commit ef539334f` (PR #1070, 2026-04-18) — added `voice_state` to `COMPONENT_OWNERS` without wiring the producer
- `commit f1f9ccef2` (FINDING-F, 2026-04-21) — *different* file (`/dev/shm/hapax-compositor/voice-state.json`), not related to this loop

## One-line operator remediation NOW

```fish
systemctl --user stop health-monitor.timer
```

(stops the 15-min sweep; allow ~2 min for daimonion to finish its warm-up; voice resumes; re-enable the timer with `systemctl --user start health-monitor.timer` after the producer is wired or the check is loosened)
