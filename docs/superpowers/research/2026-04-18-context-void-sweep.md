# Context-Void Sweep: 2026-04-18

## Summary
- Transcripts swept: 4 (ef7bbda9, fe5a14ba, 2fa8fa9e, a08e71c4)
- Dropped-commitment candidates found: 19
- Timeframe: 2026-03-25 to 2026-04-18
- Method: `jq` extraction of `role=user` string-content messages, then grep against pattern families (should also, bug reports, from now on, remind, defer, one more thing, explicit append). Filtered out items already covered by task list #27–#136 and HOMAGE/LRR epics.

## Candidate Dropped Items

### 1. Stream Deck control surface for livestream
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "I have something to add that I didn't want to but it's relevant just peg it for later: I have a stream deck that we can use for controls that we will set up"
- **Approximate timestamp:** 2026-04-06T04:33:12Z
- **Why I flag this:** Explicitly "peg for later" — operator self-identified this as deferred. Not in #27–#136 or any HOMAGE/LRR item. Half-speed toggle at 04:42:32Z reinforces this ("it needs to be toggleable (steam deck button?)").
- **Subsystem:** infra (control surface) + studio
- **Suggested action:** add to task list (infra epic)

### 2. KDEConnect phone-push control path (interim before Stream Deck)
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "set it up intially so I can send via kdeconnect, it'll be easiest"
- **Approximate timestamp:** 2026-04-06T04:49:29Z
- **Why I flag this:** Paired with #1 — explicit interim solution chosen. No KDEConnect bridge evidence in current task list. Likely dropped when conversation pivoted to album ID.
- **Subsystem:** infra
- **Suggested action:** add to task list, likely same epic as #1

### 3. Vinyl half-speed correction + toggle (Korg Handytrax range)
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "I have been playing half speed: make corrections appropriately, but it needs to be toggleable" / "It might not be 50%. Check Korg handytrax play for slowdown speedup range"
- **Approximate timestamp:** 2026-04-06T04:42:32Z, 2026-04-06T07:51:52Z
- **Why I flag this:** Track-identification and audio-reactivity systems need to compensate for non-standard playback rate. Related to #127 SPLATTRIBUTION but the *correction/toggle* mechanic isn't in the current list.
- **Subsystem:** audio / perception
- **Suggested action:** add to task list — splattribution dependency

### 4. ARCloud integration + IR feed pull cadence control
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "You also need to be able to have better control over when you get fresh feed from the IR. ARCLOud"
- **Approximate timestamp:** 2026-04-06T07:39:19Z
- **Why I flag this:** Specific external service name-dropped for track ID (ARCloud/ACRCloud), plus IR pull-cadence control. Not obviously in #127 or the #136 camera rename item.
- **Subsystem:** perception (album ID) + audio
- **Suggested action:** investigate further — likely extends #127 SPLATTRIBUTION

### 5. YouTube livestream description auto-update from shared video links
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "Those links should also be used to update the YT livestream description in real time if possible so attributions are made real (think carefully about this last part, because it could be a powerful reuseable strategy.)"
- **Approximate timestamp:** 2026-04-06T05:20:25Z
- **Why I flag this:** Operator flagged as "powerful reuseable strategy" — explicit value signal. Current task list has no YT livestream API description hook.
- **Subsystem:** infra / livestream integration
- **Suggested action:** add to task list

### 6. Audio ducking of 24c mix for YouTube/React content (production quality, normalized)
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "we will need production quality audio ducking for the 24c mix coming in to get out of the way of any youtube/react content, not A LOT but enough to let the YouTube audio come in (should itself be normalized)"
- **Approximate timestamp:** 2026-04-06T04:29:22Z
- **Why I flag this:** Partial coverage — PR #778 landed audio-ducking envelope (2026-04-14), but that was for the reference livestream audio path, not specifically for ducking the 24c mix around YT/React overlay audio with normalization. Cross-reference needed.
- **Subsystem:** audio
- **Suggested action:** investigate further — may be covered by PR #778 or may need explicit follow-up

### 7. Token pole: scaling difficulty + contributive-chat reward + vampire-survivor emoji spew
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "When the token reaches the top, a whole bunch of human-type emojis/glyphs spew out (think vampire survivor style treasure explosions). Tokens get spent in proportion to contributive, interesting, positive chat activity and subs and donations. This scales over time like a video game scales"
- **Approximate timestamp:** 2026-04-06T09:27:00Z
- **Why I flag this:** #125 "token pole/vetruvian man calibrated and behaving properly" is a calibration task, but the *reward mechanic* (emoji spew when goal hit), the *chat-activity→token-spend coupling*, and the *scaling-over-time difficulty curve* are not in that item.
- **Subsystem:** rendering (livestream) + infra (chat monitor)
- **Suggested action:** add to task list — token-pole reward/scaling mechanic

### 8. Token-pole qualifier research — healthy, non-patronizing, non-manipulative
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "research ways of determining those qualifiers that are actually healthy, not patronizing, not cheesy, not manipulative and actually likely to lead to positive results. The risks here are considerable."
- **Approximate timestamp:** 2026-04-06T09:29:19Z
- **Why I flag this:** Governance-adjacent research commitment explicit from operator ("risks here are considerable"). Not reflected in any LRR or HOMAGE task.
- **Subsystem:** governance / research
- **Suggested action:** add to task list — dedicated research task tied to #7 above

### 9. Reactivity granularity/symmetry/sync still off (compounded reactivity + bloom interaction)
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "the reactivity still doesn't line up correctly with the audio, enough that it doesn't feel sync'd, just seems to have its own pulse" / "the increased responsivity has compounded the strength of many of the reactivity effects, especially ones that 'bloom'"
- **Approximate timestamp:** 2026-04-05T01:44:17Z, 2026-04-05T01:53:41Z
- **Why I flag this:** #128 "preset variety" is about variety, not sync/granularity. Operator verdict "doesn't feel sync'd" is a quality-ceiling complaint distinct from variety. Unclear if later A+ livestream work (#74–#78) addressed it — should verify before dropping.
- **Subsystem:** rendering / audio
- **Suggested action:** investigate further — cross-reference against A+ livestream closures

### 10. "Effect reactivity to anything pumped into 24c" — global reactivity source contract
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "not sure where to shove it in the project sequence, but we need to enable effect reactivity to anything being pumped into the 24c"
- **Approximate timestamp:** 2026-04-04T23:25:09Z
- **Why I flag this:** Explicit "I don't know where to put this" + durable architectural directive. Contact-mic pipeline (MEMORY: project_contact_mic_wired) covers LEFT channel; RIGHT channel + any future 24c input may not have the generic contract.
- **Subsystem:** audio
- **Suggested action:** investigate further — may overlap with #134 audio pathways audit

### 11. Massive video/image classification + detection pipeline underutilized in livestream
- **Source transcript:** ef7bbda9-4b93-494f-b8e7-7037c7279a85.jsonl
- **Operator quote (verbatim):** "Another wrench that has not been thrown around yet: We have a massive video/image classification and detection system that we are not at all using in the livestream"
- **Approximate timestamp:** 2026-04-17T18:56:37Z
- **Why I flag this:** Explicit call-out of unused capability. Image classification appears only in context of #129 facial obscuring. Broader livestream integration (scene understanding → director decisions, object presence → ward triggers) is not tracked.
- **Subsystem:** perception / rendering (livestream direction)
- **Suggested action:** add to task list — capability-integration epic

### 12. Claude must be prepared to audit EVERYTHING Gemini produces
- **Source transcript:** ef7bbda9-4b93-494f-b8e7-7037c7279a85.jsonl
- **Operator quote (verbatim):** "I also want to make sure that claude is totally prepared to audit EVERYTHING gemini does"
- **Approximate timestamp:** 2026-04-15T22:03:29Z
- **Why I flag this:** Gemini-takeover experiment ran one day and was abandoned (2026-04-16 14:08), but the audit-preparedness directive is durable for any future heterogeneous agent collaboration. Not in task list.
- **Subsystem:** governance
- **Suggested action:** add to task list or to global CLAUDE.md (meta-directive about cross-agent audit posture)

### 13. Session-naming convention: sessions are ALWAYS named alpha/beta/delta/epsilon etc.
- **Source transcript:** ef7bbda9-4b93-494f-b8e7-7037c7279a85.jsonl
- **Operator quote (verbatim):** "I always have sessions named what they are 'alpha' 'beta' 'delta' etc"
- **Approximate timestamp:** 2026-04-15T17:42:44Z
- **Why I flag this:** Context: beta was misidentifying itself as alpha after reboot. This is a "from now on" infrastructure invariant. Not encoded in hooks or session-startup scripts as far as I can see.
- **Subsystem:** infra (session identity)
- **Suggested action:** investigate whether enforced by hooks; if not, add hook via `hookify` or add to task list

### 14. Worktree cap = 6 blocking beta mid-work
- **Source transcript:** ef7bbda9-4b93-494f-b8e7-7037c7279a85.jsonl
- **Operator quote (verbatim):** "beta is hitting worktree limits, figure out how to solve this issue: Worktree limit reached (6). Committing #104 direct-to-main in primary worktree."
- **Approximate timestamp:** 2026-04-15T17:24:49Z
- **Why I flag this:** Bug report embedded in chat. Operator asked to "figure out how to solve" but the fix is unclear from transcript. Workspace CLAUDE.md pins "three worktree slots strictly enforced" — bump to 6 was in effect but still ran out.
- **Subsystem:** infra (git workflow)
- **Suggested action:** investigate further — may be policy tightening already in place, verify

### 15. Hookify text-glob firing into context uselessly / write hook errors
- **Source transcript:** ef7bbda9-4b93-494f-b8e7-7037c7279a85.jsonl
- **Operator quote (verbatim):** "Is it necessary for this text glob to fire into context all the time? Rarely have I seen it be useful" / "Also seeing lots of these write hook errors" / "hookify glob just hit alpha context again"
- **Approximate timestamp:** 2026-04-15T18:08:50Z, 18:13:26Z, 19:38:15Z
- **Why I flag this:** Three separate complaints about the same hookify issue within 90 minutes. Not in task list. Ongoing irritation.
- **Subsystem:** infra (Claude Code harness)
- **Suggested action:** add to task list — hookify rule pruning / fix write-hook errors

### 16. Hapax persona/posture/role: persona NOT personification (governance-critical)
- **Source transcript:** ef7bbda9-4b93-494f-b8e7-7037c7279a85.jsonl
- **Operator quote (verbatim):** "persona must NOT be PERSONIFICATION. Hapax should not lie about what it is. It should not attempt to have a 'human' perspective because it is not human... Its posture should be engendered by its persona, its being... roles ARE explicated, scoped and defined..."
- **Approximate timestamp:** 2026-04-16T22:10:58Z
- **Why I flag this:** Dense design-directive block on a "tender and fragile subject" per operator. MEMORY has `project_phase_7_taxonomy` (8 positions, 3 layers), but the *anti-personification constraint* and *posture-from-being emergence* principles here are much stronger than what's encoded. Verify they made it into specs.
- **Subsystem:** governance (persona/posture spec)
- **Suggested action:** investigate further — cross-reference against Phase 7 taxonomy docs; if not captured, formalize

### 17. Role derivation from research (general-case + Hapax-specific), not declared
- **Source transcript:** ef7bbda9-4b93-494f-b8e7-7037c7279a85.jsonl
- **Operator quote (verbatim):** "ROLE specifications should be derived from research surfacing what the ROLE actually is in the general case (minute by minute, cadence by cadence functions) and what the ROLE then actually is for US given the very strange set of tools, constraints, and goals we have."
- **Approximate timestamp:** 2026-04-18T18:47:38Z
- **Why I flag this:** Methodological directive (derive roles from research, don't just declare) tied to livestream "direction" complaint at 18:45:45 ("effects should be active directorial decisions... go over ROLE specifications"). Task list has HOMAGE roles research but likely not this general-case methodology commitment.
- **Subsystem:** governance / research methodology
- **Suggested action:** add to task list — role-derivation research task

### 18. Reactivity-from-composite-overlay layer (non-destructive effects on overlay content)
- **Source transcript:** fe5a14ba-3f82-4ec2-9434-9f96ed124351.jsonl
- **Operator quote (verbatim):** "We need the overlay to be part of it's own contained effects layer that is interesting in and of itself but does not get gobbled up by the effects beneath it. That means this layer should be combinations of non-destructive effects. Not necessarily MILD in combination, but something that won't distort the video so severely that it's not indicative of its underlying content."
- **Approximate timestamp:** 2026-04-06T06:07:12Z
- **Why I flag this:** Specific architectural constraint on YT video overlay effect treatment — "non-destructive effects" as a new category. Not in #128 preset variety or HOMAGE ward research.
- **Subsystem:** rendering
- **Suggested action:** add to task list — non-destructive overlay effect category

### 19. Director loop: "do nothing interesting" unacceptable invariant
- **Source transcript:** ef7bbda9-4b93-494f-b8e7-7037c7279a85.jsonl
- **Operator quote (verbatim):** "The director loop should be having some kind of actual effect on the livestream every time. There is no justifiable context where 'do nothing interesting' is acceptable."
- **Approximate timestamp:** 2026-04-18T05:42:07Z
- **Why I flag this:** Strong invariant ("no justifiable context"). Six director sim iterations followed. Latest task list item #136 "follow-mode" doesn't encode this invariant as a test/gate. Worth a regression pin.
- **Subsystem:** rendering (director)
- **Suggested action:** add to task list — director invariant regression test

---

## Out-of-scope items explicitly dropped from this report (operator revoked or covered)

- Vinyl stream "will it hurt music quality at half speed?" — answered in-session, not a commitment.
- Reactivity-weakness cycle (ghost/trails/feedback_preset) — iterated to resolution in-session 04-05.
- Migration hardware troubleshooting (fstab, m.2, enclosure) — resolved in-session 04-17.
- Gemini takeover preparation — operator revoked ("Gemini is done working. Lasted one day. Too painful." 04-16 14:08).
- Pre-reg filing — filed at https://osf.io/5c2kr/overview on 04-16 19:44.
- "Session retirement" attempts — operator explicitly rejected ("there will be no session retirement ever until LRR is completed" 04-15 17:07). Feedback already captured in MEMORY.
- Homage system roles/research — covered by HOMAGE epic #99–#120.
- All #121–#136 appended tasks — directly enumerated in task list.
