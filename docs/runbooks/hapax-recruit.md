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

## Recheck the measured read refusals

These are manual provider probes for the registry item; tests do not execute them. With the
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

## Failure artifacts and deadlines

Failed CLI output, including partial timeout answers, is redacted before the recruiter writes
the answer and receipt or emits terminal/journal diagnostics. The receipt marks this as
`answer_policy: redacted_failure_output`. Successful answers retain their original content.
Structured credentials include escaped JSON strings, quoted/multiline YAML values and YAML
block scalars. Unterminated sensitive quoted values suppress the remaining diagnostic block.
Codex output is accepted only if its file identity or timestamps changed during this invocation.
An absent, unchanged, or empty output records `OutputNotProduced` and zero output bytes; stdout
chatter is not an answer. A retry with no output clears the previous answer file.
All CLI capacities reject empty or whitespace-only extracted answers as `OutputNotProduced`
with exit 3 and zero answer bytes. Failure receipts and terminal messages include recovery
actions: check the executable mode/PATH, inspect the receipt, or retry with `--out`/`--timeout`.

Expected launch, decoding, and HTTP transport failures return exit 3 with a `failure_class`.
Local endpoint connection, headers, and body consumption share one monotonic deadline; exceeding
it records `EndpointDeadlineExceeded` and exit 3. The POSIX CLI uses an interval timer to interrupt
blocking I/O as well as bounded body reads, so a trickling response cannot extend the deadline.
CLI subprocess timeouts retain exit 4 and process-group cleanup receipts.

Recheck each claim with these exact selections. Provider subprocesses and responses are synthetic;
these tests make no provider requests. The cleanup selection launches only the test wrapper.

```sh
env -u HAPAX_GLMCP_MODEL -u HAPAX_GLMCP_REVIEW_MODEL -u HAPAX_GLMCP_REVIEW_PAYG_FALLBACK -u HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL \
  UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify PYTEST_ADDOPTS='--confcutdir=tests/scripts' \
  uv run pytest -q -p no:cacheprovider \
  tests/scripts/test_hapax_recruit.py::test_structured_failed_output_is_redacted_at_every_destination \
  tests/scripts/test_hapax_recruit.py::test_codex_run_without_new_output_never_attributes_an_old_answer \
  tests/scripts/test_hapax_recruit.py::test_empty_cli_answer_is_receipted_failure \
  tests/scripts/test_hapax_recruit.py::test_expected_launch_decode_and_transport_failures_are_receipted \
  tests/scripts/test_hapax_recruit.py::test_local_deadline_covers_connection_and_body \
  tests/scripts/test_hapax_recruit.py::test_local_deadline_interrupts_blocking_io_and_restores_alarm \
  tests/scripts/test_hapax_recruit.py::test_timeout_kills_wrapper_process_group_and_records_no_survivor \
  tests/scripts/test_hapax_recruit.py::test_failure_recovery_actions_reach_diagnostic_destinations \
  tests/scripts/test_hapax_recruit.py::test_runbook_has_headless_read_refusal_rechecks
```

The selections check redaction, stale/empty output, receipted transport failures, the complete
deadline (including blocking I/O), process cleanup, recovery actions, and collected runbook node ids.
