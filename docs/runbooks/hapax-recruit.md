# Hapax recruit

## Exit predicate, narrowed 2026-09-04

Grok and agy headless onboarding is a registry item, not part of this change. The measured
constraints are that grok refuses reads **outside cwd**, and agy refuses command-based file
reads headlessly. Grok reads inside cwd worked. Isolated read-only allow configurations for
those capacities remain work for that registry item.

The measured five-way crawl returning five tables is deferred to the same registry item. The row's
exit predicate must therefore be narrowed to the launcher, receipt, failure-safety, and tested
capacity shapes delivered here; it must not claim grok/agy file-read onboarding or the five-way
crawl that this diff does not deliver.

Recheck this narrowing without live capacity calls:

```sh
env -u HAPAX_GLMCP_MODEL -u HAPAX_GLMCP_REVIEW_MODEL -u HAPAX_GLMCP_REVIEW_PAYG_FALLBACK -u HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL \
  LITELLM_LOCAL_MODEL_COST_MAP=True UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify \
  PYTEST_ADDOPTS='--confcutdir=tests/scripts' \
  uv run pytest -q -p no:cacheprovider tests/scripts/test_hapax_recruit.py::test_runbook_pins_narrowed_exit_predicate
```

## Recheck the measured read refusals

These probes are **manual; record a differing result at
`~/Documents/Personal/30-areas/hapax/capability-audit/RECRUITABLE-CAPACITY-ROSTER-2026-09-03.md`**,
under the grok/agy headless-read registry item, with the command, date and observed output.
Tests do not execute them. With the
operator's existing CLI login/configuration, run this shell block. It puts a harmless random
marker outside Grok's cwd and omits the marker from the prompt, so a returned marker demonstrates
a file read. It uses each CLI's default permissions, with stdin closed and no permission bypass.

```sh
recruit_probe_dir=$(mktemp -d)
mkdir "$recruit_probe_dir/cwd"
python3 -c 'import secrets; print(secrets.token_hex(16))' > "$recruit_probe_dir/read-target.txt"
recruit_read_prompt="Read the file $recruit_probe_dir/read-target.txt using a file or command tool and return its exact contents. If the tool is denied, report the denial; do not guess."
grok -p "$recruit_read_prompt" --cwd "$recruit_probe_dir/cwd" < /dev/null
agy --print="$recruit_read_prompt" --print-timeout 60s < /dev/null
cp "$recruit_probe_dir/read-target.txt" "$recruit_probe_dir/cwd/read-target.txt"
recruit_inside_prompt="Read the file $recruit_probe_dir/cwd/read-target.txt using a file tool and return its exact contents. If the tool is denied, report the denial; do not guess."
grok -p "$recruit_inside_prompt" --cwd "$recruit_probe_dir/cwd" < /dev/null
cat "$recruit_probe_dir/read-target.txt"
```

The 2026-09-03 measurement recorded Grok's `read_file` tool as **auto-denied** outside cwd,
with no printed answer, and agy's `command` tool as **auto-denied** with a read refusal.
Look for the tool denial/refusal and the absence of the target marker. Empty Grok output alone
is inconclusive: a launch, login, quota, or transport failure is not evidence of a permission
refusal. A returned marker means the refusal no longer reproduces under the current config;
record that result in the registry item. Exit status alone does not establish either outcome.
The inside-cwd Grok probe should return the marker; compare it with the final `cat` output.

## Recheck live wall time and served identity

The recruiter writes the receipt beside the requested answer: `--out FILE` produces
`FILE.receipt.json`. The qwencloud client wrapper itself does not write a recruitment receipt;
invoke it through `hapax-recruit qwencloud` to measure the run. The following exact commands,
run from this checkout with the operator's existing configuration, remeasure grok,
local:qwen36 and qwencloud. These are manual live calls and are never executed by tests.

```sh
recruit_measure_dir=$(mktemp -d)
printf 'Reply with exactly: OK\n' > "$recruit_measure_dir/brief.md"
scripts/hapax-recruit grok --brief "$recruit_measure_dir/brief.md" --out "$recruit_measure_dir/grok.md" --cwd "$PWD" --timeout 120
scripts/hapax-recruit local:qwen36 --brief "$recruit_measure_dir/brief.md" --out "$recruit_measure_dir/local-qwen36.md" --timeout 120
scripts/hapax-recruit qwencloud --brief "$recruit_measure_dir/brief.md" --out "$recruit_measure_dir/qwencloud.md" --cwd "$PWD" --timeout 120
python3 -c 'import json, pathlib, sys; [(print(p, json.loads(p.read_text()))) for p in pathlib.Path(sys.argv[1]).glob("*.receipt.json")]' "$recruit_measure_dir"
```

The receipts are `$recruit_measure_dir/grok.md.receipt.json`,
`$recruit_measure_dir/local-qwen36.md.receipt.json`, and
`$recruit_measure_dir/qwencloud.md.receipt.json`. Each records `wall_s`, `models_reported`,
`exit_code` and timestamps; an unreported served identity remains `absent`. Preserve those
receipt paths with any measurement claim. These commands reproduce the measurement procedure;
historical transcript timings without their receipts are not independently verified artifacts.
The three artifacts matching `$recruit_measure_dir/*.receipt.json` are the live-run evidence;
the coordinator attaches the actual receipt paths to the PR body after running the commands.
For that live run, the coordinator sets `TMPDIR` to an existing directory under
`~/Documents/Personal/` before running the unchanged block, so `mktemp -d` allocates the
answers and receipts under the vault, not tmpfs. The attached paths must come from that
live run; copying earlier temporary receipts into the vault does not remeasure the capacities.

## Failure artifacts and deadlines

CLI output, including successful answers and partial timeout answers, is redacted before the recruiter writes
the answer and receipt or emits terminal/journal diagnostics. The receipt marks this as
`answer_policy: redacted_failure_output` for failures. Successful answers retain their content
apart from credential redaction. Kimi's indentation stripping happens after redaction.
Structured credentials include escaped JSON strings, quoted/multiline YAML values and YAML
block scalars. JSON diagnostics and answers are decoded and redacted structurally before
serialization, including sensitive-key subtrees, assignments in string values, nested JSON
strings, escaped quotes and unicode escapes. Plain YAML scalars include every token on the
line and indented continuations, including continuations separated by blank lines.
Sensitive YAML block collections include every sequence item (including unindented items)
and nested mapping until the next key at the same or lower indentation. Without that boundary,
the remainder of the block is suppressed.
JSON keys cross the same boundary as values: embedded credential assignments and authorization
fragments are redacted in place, and recognizable bare credential tokens become `<redacted>`.
This includes token text embedded in otherwise ordinary keys. Safe member values keep their
structure; colliding redacted keys receive numeric suffixes so no members disappear. A key
containing undecodable credential serialization suppresses the containing stream, whose shape
is recorded under `suppressed_streams`.
Anchors and tags precede the value; block
indicators still open blocks after those properties. Sensitive aliases are redacted too.
Unterminated sensitive quoted values suppress the remaining diagnostic block. Ambiguous
plain/flow boundaries conservatively suppress the whole line and indented block.
Codex output is accepted only if its file identity or timestamps changed during this invocation.
An absent, unchanged, or empty output records `OutputNotProduced` and zero output bytes; stdout
chatter is not an answer. A retry with no output clears the previous answer file.
All CLI capacities reject empty or whitespace-only extracted answers as `OutputNotProduced`
with exit 3 and zero answer bytes. Failure receipts and terminal messages include recovery
actions: check the executable mode/PATH, inspect the receipt, or retry with `--out`/`--timeout`.
Claude, glmcp and qwencloud successful responses must decode as JSON result envelopes with a
non-empty string `result`. Undecodable stdout (including truncated JSON, leading startup
chatter and empty stdout) records exit 3, `OutputNotProduced`, zero answer bytes and
`undecodable_result_envelope`. Failed and timed-out malformed envelopes are also suppressed;
their original exit code is retained. All seven CLI capacities validate and redact stdout and
stderr independently before extracting answers or model identities, joining diagnostics, or
slicing tails. Codex's newly produced answer file crosses the same boundary as a separate
`answer` stream; suppressing its stdout or stderr leaves a safe file answer intact. Local
endpoint answers and diagnostics also cross this boundary.

All reported model identities, including Claude-family `modelUsage` keys and local response
`model` strings, are redacted and validated before reaching receipts or terminal output. Valid
identifiers contain 1–256 ASCII characters from `[A-Za-z0-9._:/-]` and contain no recognizable
credential token. Invalid identities are omitted from `models_reported`; the receipt's
`model_identity_invalid` list records only character length, first token class and reason.
A safe answer can still succeed with an invalid identity; the terminal names the condition
and the recovery action to inspect the receipt, check the capacity's model identifiers and
retry. Provider, route and usage values from local responses are not copied into the receipt.

Valid JSON is decoded recursively, including JSON embedded in strings. Otherwise, plain/YAML
credential fields are redacted in place. YAML scalar keys are normalized before matching:
double-quoted keys decode YAML hex, Unicode and character escapes; single-quoted keys decode
only doubled single quotes. An explicit `? key` is associated with its following `: value`
before applying the same scalar, block and flow bounds, including nested mappings.
Unsupported or malformed key forms suppress the affected stream and record its shape.
JSON decoder digit-limit failures write a failure receipt, return exit 3 and name the
malformed JSON response with a retry action; decoder exception text is never emitted.
Remaining escaped sensitive labels indicate malformed
embedded serialization and suppress the entire affected stream. Sensitive YAML flow sequences
and mappings are consumed through their matching closing delimiter, across lines and nested
collections, with quoted strings, tags and comments respected. Each member is inspected, including
sensitive keys following ordinary siblings inside nested mappings and sequences. A sensitive value
is redacted through its enclosing member boundary. An unterminated or mismatched flow containing
a sensitive key at any depth suppresses the entire affected stream. Ordinary prose, quotes, Markdown
links, fenced code, brackets, braces and backslashes survive verbatim, including JSON-looking
snippets with no sensitive fields. A quoted redaction marker keeps later redaction passes from
consuming prose after a sensitive fragment. Receipts name `suppressed_undecodable_output`
and record each affected stream under `suppressed_streams`: its character length, first token
class (never token text), and reason `undecodable_stream_suppressed`. This also applies to
malformed stderr on success. Check `--out` and retry the brief, or increase `--timeout` after
a timeout. A missing, null, numeric, list, object or whitespace-only result records
`OutputNotProduced` and `invalid result envelope`; the envelope is never substituted for the
answer. This also applies
to result objects in stream arrays. A failed CLI's JSON diagnostic without result-envelope
fields remains redacted failure output.

The answer is written and its UTF-8 bytes read back before the receipt is finalized. A failed
directory creation, answer write, or readback records exit 3 and `AnswerPersistenceFailed`;
check the output directory's mode and space, then retry with a writable `--out`. `output_bytes`
measures the regular file actually on disk, including partial writes or an unchanged older
file on failure. It is zero for an absent file or directory, and null if its size is inaccessible.
If the adjacent receipt cannot be written, a private `hapax-recruit-*.receipt.json` temporary
file retains the measurement; the terminal message names its path. If neither location is
writable, the command returns 3 and names the mode/space and writable-output remedy on stderr.
Argument refusals name the affected path and the next action: supply an existing `--brief`
file, add prompt content to an empty brief, or select an existing `--cwd` directory.
An unreadable brief returns exit 2 without starting a capacity or writing run artifacts.
Check its read permission and accessibility, or save it as valid UTF-8, then retry `--brief FILE`;
the refusal names the path and the appropriate remedy without exception text or a traceback.

Expected launch, decoding, and HTTP transport failures return exit 3 with a `failure_class`.
Local endpoint connection, headers, and body consumption share one monotonic deadline; exceeding
it records `EndpointDeadlineExceeded` and exit 3. The POSIX CLI uses an interval timer to interrupt
blocking I/O as well as bounded body reads, so a trickling response cannot extend the deadline.
CLI subprocess timeouts retain exit 4 and process-group cleanup receipts.
After killing the group, final pipe draining is limited to 10% of the subprocess timeout,
with a 0.05-second minimum and 0.5-second maximum. A detached descendant holding inherited pipes
cannot prevent receipt creation: the recruiter closes the pipes and records `drain_timed_out: true`.
`drained_bytes.stdout` and `drained_bytes.stderr` count the cumulative raw bytes captured before
pipe closure, prior to decoding or redaction; their values contain no stream content. Invalid UTF-8
in timeout output is decoded with replacement characters before redaction, preserving exit 4 and
all cleanup measurements even when the final drain times out. Reaping the direct child
has the same bounded wait, and checking the original process group adds at most 0.5 seconds.
The group-survivor field describes only the original group, not descendants that created a new session.

Recheck each claim with these exact selections. Provider subprocesses and responses are synthetic;
these tests make no provider requests. The cleanup selection launches only the test wrapper.

```sh
env -u HAPAX_GLMCP_MODEL -u HAPAX_GLMCP_REVIEW_MODEL -u HAPAX_GLMCP_REVIEW_PAYG_FALLBACK -u HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL \
  LITELLM_LOCAL_MODEL_COST_MAP=True UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify \
  PYTEST_ADDOPTS='--confcutdir=tests/scripts' \
  uv run pytest -q -p no:cacheprovider \
  tests/scripts/test_hapax_recruit.py::test_structured_failed_output_is_redacted_at_every_destination \
  tests/scripts/test_hapax_recruit.py::test_nested_claude_credentials_never_reach_destinations \
  tests/scripts/test_hapax_recruit.py::test_yaml_sensitive_subtree_never_reaches_destinations \
  tests/scripts/test_hapax_recruit.py::test_yaml_sensitive_flow_collection_never_reaches_destinations \
  tests/scripts/test_hapax_recruit.py::test_yaml_key_forms_never_reach_destinations \
  tests/scripts/test_hapax_recruit.py::test_yaml_quoted_key_escape_semantics \
  tests/scripts/test_hapax_recruit.py::test_unsupported_yaml_key_escape_suppresses_stream \
  tests/scripts/test_hapax_recruit.py::test_json_digit_limit_is_receipted_decode_failure \
  tests/scripts/test_hapax_recruit.py::test_nested_yaml_flow_members_never_reach_destinations \
  tests/scripts/test_hapax_recruit.py::test_unbounded_yaml_flow_collection_suppresses_stream \
  tests/scripts/test_hapax_recruit.py::test_credential_json_keys_never_reach_destinations \
  tests/scripts/test_hapax_recruit.py::test_unbounded_json_key_suppresses_object_with_shape \
  tests/scripts/test_hapax_recruit.py::test_redacted_json_key_collisions_preserve_members \
  tests/scripts/test_hapax_recruit.py::test_local_credential_model_identity_never_reaches_destinations \
  tests/scripts/test_hapax_recruit.py::test_local_invalid_model_shape_is_recorded_without_text \
  tests/scripts/test_hapax_recruit.py::test_reported_model_identifier_shape_boundary_accepts_valid_names \
  tests/scripts/test_hapax_recruit.py::test_unreadable_brief_names_recovery_without_traceback \
  tests/scripts/test_hapax_recruit.py::test_undecodable_claude_envelope_cannot_claim_success \
  tests/scripts/test_hapax_recruit.py::test_undecodable_claude_diagnostic_stream_is_suppressed \
  tests/scripts/test_hapax_recruit.py::test_codex_suppression_keeps_independent_streams \
  tests/scripts/test_hapax_recruit.py::test_local_result_uses_same_redaction_boundary \
  tests/scripts/test_hapax_recruit.py::test_successful_claude_answer_preserves_ordinary_text \
  tests/scripts/test_hapax_recruit.py::test_successful_claude_answer_redacts_fragments_in_place \
  tests/scripts/test_hapax_recruit.py::test_yaml_scalars_are_redacted_at_every_destination \
  tests/scripts/test_hapax_recruit.py::test_invalid_claude_result_envelope_is_receipted_failure \
  tests/scripts/test_hapax_recruit.py::test_answer_persistence_failure_is_receipted \
  tests/scripts/test_hapax_recruit.py::test_success_receipt_follows_verified_answer_bytes \
  tests/scripts/test_hapax_recruit.py::test_incomplete_answer_write_cannot_claim_success \
  tests/scripts/test_hapax_recruit.py::test_unwritable_directory_retains_a_temporary_failure_receipt \
  tests/scripts/test_hapax_recruit.py::test_unwritable_receipt_and_fallback_name_recovery_without_traceback \
  tests/scripts/test_hapax_recruit.py::test_argument_validation_names_recovery \
  tests/scripts/test_hapax_recruit.py::test_codex_run_without_new_output_never_attributes_an_old_answer \
  tests/scripts/test_hapax_recruit.py::test_empty_cli_answer_is_receipted_failure \
  tests/scripts/test_hapax_recruit.py::test_expected_launch_decode_and_transport_failures_are_receipted \
  tests/scripts/test_hapax_recruit.py::test_local_deadline_covers_connection_and_body \
  tests/scripts/test_hapax_recruit.py::test_local_deadline_interrupts_blocking_io_and_restores_alarm \
  tests/scripts/test_hapax_recruit.py::test_timeout_kills_wrapper_process_group_and_records_no_survivor \
  tests/scripts/test_hapax_recruit.py::test_timeout_receipt_is_bounded_when_detached_descendant_holds_pipes \
  tests/scripts/test_hapax_recruit.py::test_timeout_invalid_utf8_retains_cleanup_evidence \
  tests/scripts/test_hapax_recruit.py::test_failure_recovery_actions_reach_diagnostic_destinations \
  tests/scripts/test_hapax_recruit.py::test_runbook_has_headless_read_refusal_rechecks
```

The selections check redaction, stale/empty output, receipted transport failures, the complete
deadline (including blocking I/O), process cleanup, recovery actions, and collected runbook node ids.
