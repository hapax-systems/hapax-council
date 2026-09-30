# Token Plan listed-client measurement

`scripts/hapax-qwencloud-claude` retains the earlier entry-point filename, but
launches **OpenCode**, not Claude Code. It provides a bounded synthetic
measurement of the operator's Singapore Token Plan credentials. It does not
admit a worker, select real work, infer a second subscription, or activate a
LiteLLM/backend route.

## Authority and provenance

Task: `qwencloud-entitlement-activation-20260914`. The operator's 2026-09-25
ruling permits per-task use of a listed client. The current activation brief
requires a genuine claim, current declared route/identity, installed stage
transition, scoped source edits, independent review, and installed readback.
The lane's manual claim is not an MQ authority receipt. Stop at an installed
gate refusal and report the exact predicate to the coordinator.

BACKED prior art: closed, unmerged
[PR #4630](https://github.com/hapax-systems/hapax-council/pull/4630), head
`7e01a658541d949fef5852658c8ec47dab0aa233`, contains the earlier isolated
Claude launcher. Its old key measurements do not establish current entitlement
use. This implementation retains runtime FileStore resolution and isolated
client configuration; endpoint/model escape switches now refuse, output is
reduced to typed measurements, and the complete child process group is reaped.

## Current vendor binding

Alibaba's [OpenCode configuration](https://www.alibabacloud.com/help/en/model-studio/opencode)
lists OpenCode for Token Plan Personal Edition and specifies
`@ai-sdk/anthropic` with
`https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic/v1`.
The `/v1` suffix belongs to that SDK's base URL configuration.
The underlying client constructs the provider requests; the launcher does not
call the model API.

The [personal catalogue](https://www.alibabacloud.com/help/en/model-studio/token-plan-personal-overview),
read 2026-09-30, lists these explicit text model IDs: `qwen3.8-max`,
`qwen3.8-flash`, `qwen3.7-max`, `qwen3.7-plus`, `qwen3.6-flash`,
`deepseek-v4.1-flash`, `deepseek-v4-pro`, `deepseek-v4-pro-0813`,
`deepseek-v4-flash-0731`, `glm-5.3`, and `glm-5.2`. The launcher excludes the
automatic selector. `qwen3.8-plus` and `qwen3.8-flash-next` were not in that
table; their absence here is not a provider rejection measurement.

The [tool policy](https://www.alibabacloud.com/help/en/model-studio/more-tools)
distinguishes coding clients from prohibited direct backend, automated-script,
and API-testing consumption. Do not convert this binding to direct HTTP calls,
a periodic probe, or a LiteLLM service. No PAYG fallback is implemented.

## Invocation

After the task's installed admission checks pass:

```bash
uv run --no-sync python scripts/hapax-qwencloud-claude \
  --task qwencloud-entitlement-activation-20260914 --check

uv run --no-sync python scripts/hapax-qwencloud-claude \
  --task qwencloud-entitlement-activation-20260914 --smoke
```

`--check` retrieves no credential and makes no model call. `--smoke` sends one
fixed synthetic prompt through OpenCode, with tools denied and output capped.
The default model is `qwen3.8-flash`. `--task` records caller provenance; it
does not mint authority or replace the installed task/route gates.

The default FileStore name is `alibaba-cloud/plan-api-key`. Only an explicit
`--credential legacy` selects `qwencloud/apikey`, at the same Token Plan
endpoint. A failure never triggers the other key or a different endpoint.
Different keys and successful calls do not establish different accounts or
quota pools. Account/plan evidence must settle that question independently.

## Credential and process boundary

The key is read through `hapax-secret` at execution time, into memory, then
passed only in the child environment. Its config contains an environment
placeholder. The client gets a new home and all XDG paths under a verified
`/dev/shm` tmpfs directory. Caller auth, proxy and configuration variables are
not inherited. Project config, skills, plugins, sharing, automatic updates and
model-catalogue fetching are disabled. Existing system-managed OpenCode config
causes a refusal pending review. Only the fixed provider/model can be selected.

The launcher captures stdout/stderr in memory and persists none of the raw
client output. The printed receipt contains only fixed labels, validated
identifiers and numeric measurements. It never prints the answer except for a
boolean exact-match observation. Child groups are killed on timeout and after
exit, before isolated state is removed. There is no disk-backed scratch
fallback. A local failure or uncompleted answer returns a nonzero result.

The receipt records **requested** model separately from **served** model.
OpenCode's captured events do not prove provider-served identity, account
identity or plan quota delta; those fields remain unobserved. A successful
synthetic response alone is not source acceptance or production admission.

## Verification and release

```bash
uv run --no-sync ruff check scripts/hapax-qwencloud-claude \
  tests/scripts/test_hapax_qwencloud_claude.py
uv run --no-sync pytest tests/scripts/test_hapax_qwencloud_claude.py -q
```

Tests substitute executable client and credential fixtures. Safety mutation
legs run in an isolated network namespace and must fail under the break,
restore exact source bytes, then pass. Live smoke receipts and mutation
observations belong in the task's vault evidence, not as invented test results.
The coordinator owns independent review and acceptance. Installation and real
work must wait for their applicable admission/release boundary and require
readback of the installed bytes and behavior.
