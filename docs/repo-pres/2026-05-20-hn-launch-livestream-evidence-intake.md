# HN Launch Livestream Evidence Intake

Date: 2026-05-20
Task: `hn-launch-livestream-evidence-intake`
Decision: **NO-GO** for livestream-dependent HN systems readiness.

This receipt consumes the current YouTube, OBS, RTMP, MediaMTX, and broadcast
audio evidence exposed by the owning livestream/runtime surfaces. It does not
authorize public launch, start livestream services, alter audio routing, or
expose credentials.

## Readiness Sample

Command:

```bash
scripts/hn-launch-systems-readiness --json
```

Receipt:
`/tmp/hapax-hn-livestream-evidence-intake-20260520T145236Z.json`

Result:

```text
status=fail
ready=false
failures=compositor_visual_surface,reverie_visual_surface,youtube_livestream,obs_clean_feed,systemd_timer_failed_unit_budget
warnings=logos_api
```

Relevant HN launch checks:

```text
youtube_livestream=fail :: YouTube livestream video id is missing, empty, or stale
obs_clean_feed=fail :: hapax-obs-livestream is not active; egress state does not allow a public live claim; egress evidence failing: rtmp_output, mediamtx_hls, hls_playlist, audio_floor
```

## YouTube Evidence

`hapax-youtube-video-id.service` and `hapax-youtube-viewer-count.service` are
active, but they do not currently prove an active public livestream.

- `/dev/shm/hapax-compositor/youtube-video-id.txt` exists but is empty,
  stale, and therefore not public-copy-match evidence.
- `/dev/shm/hapax-compositor/youtube-viewer-count.txt` is fresh and contains
  `0`; service logs report no active broadcast.
- `/dev/shm/hapax-compositor/youtube-quota.json` is absent, which is a warning
  for quota/description state, not a substitute for the missing video id.

The `youtube_livestream` readiness check is correctly red.

## OBS And Public Egress Evidence

`hapax-obs-livestream.service` is inactive. The loopback device `/dev/video42`
exists, but the public egress state does not allow a launch claim:

- `public_claim_allowed=false`
- `rtmp_output=fail`, with RTMP detached/not reported
- `mediamtx_hls=fail`, with the local Studio HLS URL returning 404
- `hls_playlist=fail`, with the playlist stale
- `audio_floor=fail`
- `privacy_floor=pass`

MediaMTX is active, but its metrics show no publisher or HLS muxer:

```text
paths{name="studio",state="notReady"} 1
paths_bytes_received{name="studio",state="notReady"} 0
hls_muxers 0
rtmp_conns 0
```

The `obs_clean_feed` readiness check is correctly red.

## Broadcast Audio Evidence

The current broadcast audio safety file is fresh, but it is not green. Blocking
reasons include:

- `topology_unclassified_drift`
- `egress_binding_missing`
- `egress_loopback_silent`
- `health_predicate_drift`

The broadcast manifest is fresh and lists only broadcast-safe owned assets, but
its authority ceiling explicitly does not grant public, truth, rights, safety,
or monetization status. It cannot override the failed OBS/public-egress gate.

## Conclusion

The livestream owner has not supplied green YouTube/OBS evidence for HN launch
readiness. The honest intake result is NO-GO:

- no current YouTube livestream video id,
- no active OBS clean-feed service,
- no RTMP publisher,
- no MediaMTX Studio HLS stream,
- no public-claim allowance, and
- no passing audio-floor evidence.

`scripts/hn-launch-systems-readiness` must continue to fail
`youtube_livestream` and `obs_clean_feed` until those owning surfaces publish
fresh green evidence.
