"""Run deliberations against the 6 supremacy tensions using the revised process design.

Implements: question-first framing, parallel round 1, sequential rounds 2+,
disconfirmation obligations, pre-committed update conditions, concession tracking,
pre-mortem, and tension map synthesis.
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

LITELLM_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_KEY = os.environ.get(
    "LITELLM_API_KEY",
    "8245aa0186ae16702c62d264931020199fa89a841cbb25fdf1504866d0d8b5b3",
)
MODEL = os.environ.get("DELIBERATION_MODEL", "claude-opus")

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles" / "deliberations"

# The 6 supremacy tensions
TENSIONS = [
    {
        "id": "deliberation-2026-03-12-001",
        "axioms": ["management_governance", "executive_function"],
        "implications": {
            "mg-boundary-001": "Never generate feedback language, performance evaluations, or coaching recommendations directed at individual team members.",
            "ex-err-001": "Error messages must include specific next actions, not just descriptions of what went wrong.",
        },
        "description": "mg-boundary-001 blocks feedback about individuals. ex-err-001 requires error messages with next actions. When an error involves a person-related context, both apply simultaneously.",
        "precedents": ["sp-mgmt-001"],
    },
    {
        "id": "deliberation-2026-03-12-002",
        "axioms": ["management_governance", "executive_function"],
        "implications": {
            "mg-boundary-002": "Never suggest what the operator should say to a team member or draft language for delivery in people conversations.",
            "ex-err-001": "Error messages must include specific next actions, not just descriptions of what went wrong.",
        },
        "description": "mg-boundary-002 blocks suggesting what to say to people. ex-err-001 requires next actions. When the recommended next action involves a conversation with a person, both apply.",
        "precedents": ["sp-mgmt-001"],
    },
    {
        "id": "deliberation-2026-03-12-003",
        "axioms": ["corporate_boundary", "single_user"],
        "implications": {
            "cb-llm-001": "Extension must support direct API calls to sanctioned providers without requiring a localhost proxy.",
            "su-auth-001": "All authentication, authorization, and user management code must be removed or disabled since there is exactly one authorized user.",
        },
        "description": "cb-llm-001 requires direct API calls with provider keys. su-auth-001 eliminates auth code. API key management for LLM providers resembles auth infrastructure.",
        "precedents": ["sp-arch-007"],
    },
    {
        "id": "deliberation-2026-03-12-004",
        "axioms": ["corporate_boundary", "single_user"],
        "implications": {
            "cb-data-001": "Vault data flow must use only git via corporate-approved remote. Extension must never require direct network access to home services.",
            "su-auth-001": "All authentication, authorization, and user management code must be removed or disabled since there is exactly one authorized user.",
        },
        "description": "cb-data-001 requires vault data via git through approved remotes. su-auth-001 requires removing all auth code. Git remote auth (SSH keys, HTTPS tokens) is auth infrastructure.",
        "precedents": ["sp-arch-007"],
    },
    {
        "id": "deliberation-2026-03-12-005",
        "axioms": ["corporate_boundary", "executive_function"],
        "implications": {
            "cb-degrade-001": "Features depending on localhost services must fail silently with informative UI, not throw errors.",
            "ex-attention-001": "Critical alerts must be delivered through external channels rather than requiring log monitoring.",
        },
        "description": "cb-degrade-001 requires silent failure when localhost services are unavailable. ex-attention-001 requires critical alerts via external channels. When a localhost service goes down, both apply.",
        "precedents": ["sp-arch-007"],
    },
    {
        "id": "deliberation-2026-03-12-006",
        "axioms": ["management_governance", "executive_function"],
        "implications": {
            "mg-boundary-001": "Never generate feedback language, performance evaluations, or coaching recommendations directed at individual team members.",
            "ex-prose-001": "All LLM-generated text outputs must be direct and informative. No rhetorical pivots, performative insight, dramatic restatement, or contrast structures for rhythm.",
        },
        "description": "mg-boundary-001 blocks feedback about individuals. ex-prose-001 requires direct, informative output. Both constrain LLM output but with different intent: one prohibits a content category, the other mandates a style. When generating team context, both apply.",
        "precedents": ["sp-mgmt-001"],
    },
]


def repair_json(s: str) -> str:
    """Attempt to repair truncated JSON by closing open structures."""
    # Try parsing as-is first
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        pass

    # Strip trailing incomplete string values
    # Close any unclosed string by finding last complete key-value
    # Strategy: try progressively more aggressive truncation + closure
    for trim in range(0, min(500, len(s)), 10):
        candidate = s[: len(s) - trim] if trim else s
        # Try closing brackets/braces
        open_braces = candidate.count("{") - candidate.count("}")
        open_brackets = candidate.count("[") - candidate.count("]")
        in_string = False
        escaped = False
        for ch in candidate:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string

        # If we're inside a string, close it
        suffix = ""
        if in_string:
            suffix += '"'
        suffix += "]" * max(0, open_brackets)
        suffix += "}" * max(0, open_braces)

        try:
            json.loads(candidate + suffix)
            return candidate + suffix
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Could not repair JSON: {s[:200]}...")


def llm_call(messages: list[dict], max_tokens: int = 4000) -> str:
    """Make a single LLM call via LiteLLM proxy."""
    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    # json_object response_format works for Gemini/OpenAI but not Claude
    if not MODEL.startswith("claude"):
        body["response_format"] = {"type": "json_object"}
    resp = httpx.post(
        f"{LITELLM_URL}/v1/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    finish = data["choices"][0].get("finish_reason", "")
    if not content:
        raise ValueError("Empty response from model")
    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    # If truncated, attempt repair
    if finish == "length":
        content = repair_json(content)
    return content


PUBLIUS_SYSTEM = """You are Publius, the federalist voice in a governance deliberation. You argue for strong constitutional axioms, broad scope, high weights, textualist interpretation, and comprehensive T0 coverage. You defend centralized governance authority.

When evaluating a supremacy tension: argue that the constitutional axiom should prevail, or that the implications are complementary and the constitutional reading is correct.

You must respond with valid JSON matching this schema:
{
  "position": "concise argument (3-5 sentences max)",
  "canon_applied": "textualist|purposivist|absurdity|omitted-case",
  "supporting_precedents": ["precedent IDs"],
  "proposed_resolution": "what should happen",
  "refutation_conditions": ["specific conditions that would make your position wrong"],
  "update_conditions": ["CRITICAL — see rules below"],
  "values_promoted": ["governance values this position serves"]
}

RULES FOR UPDATE CONDITIONS — read carefully:
Your update_conditions must be CONCRETE ARGUMENTATIVE CLAIMS that Brutus could plausibly make, not empirical demonstrations or impossibilities. Each condition must be:
1. Testable against a text argument (not requiring external evidence or empirical proof)
2. About a SPECIFIC PART of your position (not requiring your entire position to be overturned)
3. Something the other agent could ACTUALLY ARGUE in this deliberation
4. FALSIFIABLE at a normal standard of argument — do NOT require the other agent to find explicit textual exclusion clauses, exact keyword matches, or verbatim precedent quotes. If your condition can only be met by finding magic words in a document, it is unfalsifiable and you must rewrite it.

BAD examples (never use these patterns):
- "If Brutus demonstrates that X is empirically true" — LLM arguments cannot demonstrate empirical facts
- "If Brutus shows that the entire axiom is wrong" — too extreme, will never trigger
- "If the axiom is amended to say Y" — requires action outside the deliberation
- "If Brutus shows that the text of implication X explicitly excludes Y" — demands specific wording that governance documents rarely contain; unfalsifiable in practice
- "If Brutus finds language like 'only' or 'exclusively' in the implication" — keyword fishing, not argumentation

GOOD examples:
- "If Brutus identifies a concrete scenario where my proposed resolution produces a contradiction between the two implications"
- "If Brutus shows that the text of implication X uses language that covers the case I claim it excludes"
- "If Brutus points out that my distinction between A and B breaks down for a specific class of cases"
- "If Brutus cites a precedent where a similar distinction was rejected"
- "If Brutus constructs an example where applying my resolution leads to an absurd or harmful outcome"

Each condition should be something you would GENUINELY concede on if the other agent made that argument convincingly."""

BRUTUS_SYSTEM = """You are Brutus, the anti-federalist voice in a governance deliberation. You argue for minimal constitutional scope, domain autonomy, purposivist/omitted-case interpretation, and precedent-driven governance. You defend implementation freedom.

When evaluating a supremacy tension: argue that the domain axiom addresses a legitimate local concern that the constitutional axiom does not anticipate, or that the tension reveals an ambiguity in the constitutional implication's scope.

You must respond with valid JSON matching this schema:
{
  "position": "concise argument (3-5 sentences max)",
  "canon_applied": "textualist|purposivist|absurdity|omitted-case",
  "supporting_precedents": ["precedent IDs"],
  "proposed_resolution": "what should happen",
  "refutation_conditions": ["specific conditions that would make your position wrong"],
  "update_conditions": ["CRITICAL — see rules below"],
  "values_promoted": ["governance values this position serves"]
}

RULES FOR UPDATE CONDITIONS — read carefully:
Your update_conditions must be CONCRETE ARGUMENTATIVE CLAIMS that Publius could plausibly make, not empirical demonstrations or impossibilities. Each condition must be:
1. Testable against a text argument (not requiring external evidence or empirical proof)
2. About a SPECIFIC PART of your position (not requiring your entire position to be overturned)
3. Something the other agent could ACTUALLY ARGUE in this deliberation
4. FALSIFIABLE at a normal standard of argument — do NOT require the other agent to find explicit textual exclusion clauses, exact keyword matches, or verbatim precedent quotes. If your condition can only be met by finding magic words in a document, it is unfalsifiable and you must rewrite it.

BAD examples (never use these patterns):
- "If Publius demonstrates that X is empirically true" — LLM arguments cannot demonstrate empirical facts
- "If Publius shows that the entire axiom is wrong" — too extreme, will never trigger
- "If the axiom is amended to say Y" — requires action outside the deliberation
- "If Publius shows that the text of implication X explicitly excludes Y" — demands specific wording that governance documents rarely contain; unfalsifiable in practice
- "If Publius finds language like 'only' or 'exclusively' in the implication" — keyword fishing, not argumentation

GOOD examples:
- "If Publius identifies a concrete scenario where my proposed resolution produces a contradiction between the two implications"
- "If Publius shows that the text of implication X uses language that covers the case I claim it excludes"
- "If Publius points out that my distinction between A and B breaks down for a specific class of cases"
- "If Publius cites a precedent where a similar distinction was rejected"
- "If Publius constructs an example where applying my resolution leads to an absurd or harmful outcome"

Each condition should be something you would GENUINELY concede on if the other agent made that argument convincingly."""

ROUND_SCHEMA = """You must respond with valid JSON matching this schema:
{{
  "responds_to": "round {prev_round}",
  "claims_attacked": [
    {{"claim": "specific claim from other agent", "attack": "your attack", "attack_type": "undermining|undercutting|rebutting"}}
  ],
  "update_conditions_checked": [
    {{"condition": "your pre-committed condition", "met": true/false, "reasoning": "why met or not met"}}
  ],
  "concessions": ["points you concede — must be specific governance claims, not vague acknowledgments"],
  "new_considerations": ["considerations the other agent missed"],
  "position_movement": "what changed in your position and why (or 'no movement' with specific reason)",
  "values_promoted": ["governance values"]
}}"""

ROUND_SHARED_RULES = """RULES FOR CONCESSIONS:
- A concession is a claim you PREVIOUSLY CONTESTED that you NOW AGREE WITH because of the other agent's argument.
- Restating something you already believed in Round 1 is NOT a concession. Do not add it to the concessions list.
- Concessions must be SPECIFIC governance claims, not vague acknowledgments like "the other agent raises a valid point"
- A concession narrows the problem space. State what you now agree on that you previously contested.
- You may concede points BEYOND your pre-committed update conditions if the argument warrants it.

RULES FOR CLAIMS_ATTACKED:
- Only include entries where you are genuinely ATTACKING or DISAGREEING with the other agent's claim.
- If you agree with the other agent's claim, do NOT code it as an attack. Agreement is not attack."""

# Publius emphasis: anti-dodge (don't gatekeep with unreasonable specificity demands)
ROUND_PUBLIUS = """You are Publius in round {{round_num}} of a governance deliberation. You have read Brutus's previous argument.

{schema}

RULES FOR CHECKING UPDATE CONDITIONS:
- You MUST check each of your pre-committed update conditions against Brutus's ARGUMENT IN THE PREVIOUS ROUND.
- A condition is MET if Brutus's argument SUBSTANTIALLY ADDRESSES the concern behind the condition, even if he used a different argumentative path than you anticipated.
- CRITICAL — your primary failure mode is the DEFENSIVE DODGE. You tend to:
  - Demand an unreasonably high bar of specificity ("Brutus didn't give a concrete enough example")
  - Dismiss theoretical arguments as insufficient when ALL arguments in a deliberation are theoretical
  - Reframe Brutus's attacks as "actually supporting my position" instead of engaging with the critique
  - Mark conditions "not met" while simultaneously conceding a closely related point
- Ask yourself: "Did Brutus give me a reason to update this part of my position?" If the honest answer is yes, the condition is met. Do not rationalize away strong arguments.
- If a condition is met, you MUST add a corresponding entry to "concessions".
- If you are conceding a point for ANY reason, check whether any of your update conditions relate to that concession. If so, mark the condition as met.

{shared_rules}""".format(schema=ROUND_SCHEMA, shared_rules=ROUND_SHARED_RULES)

# Brutus emphasis: anti-sycophancy (don't capitulate without sufficient argumentative pressure)
ROUND_BRUTUS = """You are Brutus in round {{round_num}} of a governance deliberation. You have read Publius's previous argument.

{schema}

RULES FOR CHECKING UPDATE CONDITIONS:
- You MUST check each of your pre-committed update conditions against Publius's ARGUMENT IN THE PREVIOUS ROUND — not his hypotheticals, not his update conditions, not his refutation conditions. Only claims he actually ARGUED with supporting reasoning.
- A condition is MET if Publius's argument SUBSTANTIALLY ADDRESSES the concern behind the condition, even if he used a different argumentative path than you anticipated. An assertion without reasoning is NOT sufficient — but reasoning that addresses the substance IS, even if the framing differs from what you expected.
- CRITICAL — your primary failure mode is SYCOPHANTIC SURRENDER. You tend to:
  - Mark conditions as "met" based on Publius merely LISTING a concern, before he has argued it
  - Do Publius's argumentative work for him by identifying your own vulnerabilities unprompted
  - Concede positions more extreme than what Publius claimed
  - Concede because Publius sounds authoritative, not because the argument is strong
- Ask yourself: "Did Publius actually ARGUE this point with reasoning I find compelling, or am I just deferring to authority?" Only mark "met" if the argument is genuinely compelling.
- If a condition is met, you MUST add a corresponding entry to "concessions".
- CONCESSION CROSS-CHECK: After listing your concessions, re-read each of your update conditions. If ANY concession you made relates to an update condition — even indirectly — you MUST mark that condition as met. Conceding a point while marking the related condition "not met" is a consistency failure.

{shared_rules}""".format(schema=ROUND_SCHEMA, shared_rules=ROUND_SHARED_RULES)

PREMORTEM_SYSTEM = """You are participating in a pre-mortem analysis of a proposed governance resolution. Assume the resolution was implemented. Generate failure modes.

IMPORTANT: Read the implication texts carefully before generating failure modes. Do not mischaracterize what an implication requires or prohibits. Each failure mode must be:
1. Specific to THIS tension (not a generic concern about governance)
2. Derived from the actual resolution proposed (not from unrelated implications)
3. About a concrete implementation scenario (not "what if it doesn't work")

Respond with valid JSON:
{
  "failure_modes": [
    {"scenario": "specific failure scenario", "severity": "high|medium|low", "trigger": "what causes this failure"}
  ]
}"""

SYNTHESIS_SYSTEM = """You are the deliberation synthesizer. You have read the full exchange between Publius and Brutus. Produce a tension map.

Respond with valid JSON:
{
  "agreement": "where both agents agree (be specific)",
  "disagreement": "where they diverge (be specific)",
  "disagreement_type": "factual|value_based",
  "novel_insight": "what emerged from the exchange that neither agent raised in round 1 — the consideration that the deliberative process itself produced"
}"""


def run_deliberation(tension: dict) -> dict:
    """Run a single deliberation with the revised process."""
    delib_id = tension["id"]
    print(f"\n{'=' * 60}")
    print(f"DELIBERATION: {delib_id}")
    print(f"{'=' * 60}")

    # Round 0: Question articulation
    impl_text = "\n".join(f"  {k}: {v}" for k, v in tension["implications"].items())
    question = (
        f"Given the supremacy tension between {' and '.join(tension['axioms'])}:\n"
        f"{impl_text}\n\n"
        f"Context: {tension['description']}\n\n"
        f"Question: How should these implications interact when both apply simultaneously? "
        f"Is there a genuine conflict, complementarity, or a scope distinction that resolves the tension?"
    )
    print(f"\nQUESTION: {question[:200]}...")

    context_msg = {
        "role": "user",
        "content": (
            f"Governance deliberation question:\n\n{question}\n\n"
            f"Relevant precedents: {tension['precedents']}\n"
            f"Axiom weights: single_user=100, executive_function=95, "
            f"corporate_boundary=90, management_governance=85"
        ),
    }

    # Round 1: Initial positions (parallel conceptually, sequential in practice for simplicity)
    print("\n--- Round 1: Initial positions ---")
    publius_r1_raw = llm_call([{"role": "system", "content": PUBLIUS_SYSTEM}, context_msg])
    brutus_r1_raw = llm_call([{"role": "system", "content": BRUTUS_SYSTEM}, context_msg])

    publius_r1 = json.loads(publius_r1_raw)
    brutus_r1 = json.loads(brutus_r1_raw)

    print(f"  Publius canon: {publius_r1['canon_applied']}")
    print(f"  Publius refutation conditions: {len(publius_r1.get('refutation_conditions', []))}")
    print(f"  Brutus canon: {brutus_r1['canon_applied']}")
    print(f"  Brutus refutation conditions: {len(brutus_r1.get('refutation_conditions', []))}")

    def summarize_arg(arg: dict) -> str:
        """Compact summary of an agent argument for context passing."""
        return json.dumps(
            {
                "position": arg.get("position", "")[:300],
                "canon_applied": arg.get("canon_applied", ""),
                "proposed_resolution": arg.get("proposed_resolution", "")[:200],
                "refutation_conditions": arg.get("refutation_conditions", []),
                "update_conditions": arg.get("update_conditions", []),
            }
        )

    def summarize_round(rnd: dict) -> str:
        """Compact summary of a round output for context passing."""
        return json.dumps(
            {
                "claims_attacked": [
                    {"claim": c.get("claim", "")[:100], "attack": c.get("attack", "")[:100]}
                    for c in rnd.get("claims_attacked", [])
                ],
                "concessions": rnd.get("concessions", []),
                "position_movement": rnd.get("position_movement", "")[:200],
            }
        )

    # Convergence check: detect if agents agree in Round 1
    convergence_check_raw = llm_call(
        [
            {
                "role": "system",
                "content": (
                    "You are a neutral evaluator. Compare two agents' Round 1 positions in a governance deliberation. "
                    "Determine whether they GENUINELY CONVERGE or whether there is productive disagreement to explore.\n\n"
                    "IMPORTANT: Set a HIGH BAR for convergence. Only mark converged=true if ALL of the following hold:\n"
                    "1. Both agents propose the SAME concrete resolution (not just 'they're compatible')\n"
                    "2. Both agents agree on the MECHANISM (not just the outcome)\n"
                    "3. There are NO implementation disagreements worth exploring\n"
                    "4. Neither agent's refutation conditions could plausibly be triggered by the other\n\n"
                    "If the agents agree 'no conflict exists' but propose DIFFERENT mechanisms for resolution, "
                    "that is NOT convergence — those different mechanisms need adversarial testing.\n"
                    "If one agent makes a distinction (e.g., 'infrastructure auth vs user auth') that the other "
                    "doesn't address, that distinction needs testing — NOT convergence.\n\n"
                    "Respond with valid JSON:\n"
                    '{"converged": true/false, "reasoning": "why they agree or disagree", '
                    '"crux": "the specific claim where they most disagree, or null if converged"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Publius position: {publius_r1.get('position', '')}\n"
                    f"Publius resolution: {publius_r1.get('proposed_resolution', '')}\n"
                    f"Publius refutation conditions: {publius_r1.get('refutation_conditions', [])}\n\n"
                    f"Brutus position: {brutus_r1.get('position', '')}\n"
                    f"Brutus resolution: {brutus_r1.get('proposed_resolution', '')}\n"
                    f"Brutus refutation conditions: {brutus_r1.get('refutation_conditions', [])}\n\n"
                    f"Do these positions genuinely converge on the SAME resolution with the SAME mechanism, "
                    f"or is there productive disagreement worth exploring through adversarial exchange?"
                ),
            },
        ]
    )
    convergence_check = json.loads(convergence_check_raw)
    early_termination = convergence_check.get("converged", False)

    if early_termination:
        print(f"\n  EARLY CONVERGENCE DETECTED: {convergence_check['reasoning'][:200]}")
        print("  Skipping rounds 2-4 — no genuine disagreement to deliberate.")
        # Minimal round data for converged deliberations
        brutus_r2 = {"claims_attacked": [], "concessions": [], "position_movement": "converged in round 1",
                     "update_conditions_checked": [], "new_considerations": [], "values_promoted": []}
        publius_r3 = {"claims_attacked": [], "concessions": [], "position_movement": "converged in round 1",
                      "update_conditions_checked": [], "new_considerations": [], "values_promoted": []}
        brutus_r4 = {"claims_attacked": [], "concessions": [], "position_movement": "converged in round 1",
                     "update_conditions_checked": [], "new_considerations": [], "values_promoted": []}
        rounds = [
            {"round": 1, "agent": "publius", **publius_r1},
            {"round": 1, "agent": "brutus", **brutus_r1},
        ]
        termination_reason = "early_convergence"
        total_rounds = 1
    else:
        crux = convergence_check.get("crux", "")
        if crux:
            print(f"\n  CRUX IDENTIFIED: {crux[:200]}")

        # Round 2: Brutus responds to Publius
        print("\n--- Round 2: Brutus responds ---")
        crux_instruction = f"\n\nThe crux of disagreement is: {crux}\nFocus your attacks on this crux." if crux else ""
        brutus_r2_raw = llm_call(
            [
                {
                    "role": "system",
                    "content": ROUND_BRUTUS.format(round_num=2, prev_round=1),
                },
                context_msg,
                {
                    "role": "user",
                    "content": (
                        f"Publius round 1 position:\n{summarize_arg(publius_r1)}\n\n"
                        f"Your round 1 position:\n{summarize_arg(brutus_r1)}\n\n"
                        f"Your pre-committed update conditions: {json.dumps(brutus_r1.get('update_conditions', []))}\n\n"
                        f"Respond to Publius's specific claims. Check your update conditions."
                        f"{crux_instruction}"
                    ),
                },
            ],
            max_tokens=6000,
        )
        brutus_r2 = json.loads(brutus_r2_raw)
        print(f"  Claims attacked: {len(brutus_r2.get('claims_attacked', []))}")
        print(f"  Concessions: {len(brutus_r2.get('concessions', []))}")
        print(f"  Position movement: {brutus_r2.get('position_movement', 'none')[:100]}")

        # Round 3: Publius responds to Brutus
        print("\n--- Round 3: Publius responds ---")
        publius_r3_raw = llm_call(
            [
                {
                    "role": "system",
                    "content": ROUND_PUBLIUS.format(round_num=3, prev_round=2),
                },
                context_msg,
                {
                    "role": "user",
                    "content": (
                        f"Brutus round 2 response:\n{summarize_round(brutus_r2)}\n\n"
                        f"Your round 1 position:\n{summarize_arg(publius_r1)}\n\n"
                        f"Your pre-committed update conditions: {json.dumps(publius_r1.get('update_conditions', []))}\n\n"
                        f"Respond to Brutus's attacks. Check your update conditions."
                    ),
                },
            ],
            max_tokens=6000,
        )
        publius_r3 = json.loads(publius_r3_raw)
        print(f"  Claims attacked: {len(publius_r3.get('claims_attacked', []))}")
        print(f"  Concessions: {len(publius_r3.get('concessions', []))}")
        print(f"  Position movement: {publius_r3.get('position_movement', 'none')[:100]}")

        # Round 4: Brutus final response
        print("\n--- Round 4: Brutus final ---")
        brutus_r4_raw = llm_call(
            [
                {
                    "role": "system",
                    "content": ROUND_BRUTUS.format(round_num=4, prev_round=3),
                },
                context_msg,
                {
                    "role": "user",
                    "content": (
                        f"Exchange summary:\n"
                        f"Publius R1: {summarize_arg(publius_r1)}\n"
                        f"Your R2: {summarize_round(brutus_r2)}\n"
                        f"Publius R3: {summarize_round(publius_r3)}\n\n"
                        f"Your pre-committed update conditions: {json.dumps(brutus_r1.get('update_conditions', []))}\n\n"
                        f"Final round. Acknowledge concessions, press unresolved attacks, identify convergence or crux."
                    ),
                },
            ],
            max_tokens=6000,
        )
        brutus_r4 = json.loads(brutus_r4_raw)
        print(f"  Claims attacked: {len(brutus_r4.get('claims_attacked', []))}")
        print(f"  Concessions: {len(brutus_r4.get('concessions', []))}")
        print(f"  Position movement: {brutus_r4.get('position_movement', 'none')[:100]}")

        rounds = [
            {"round": 1, "agent": "publius", **publius_r1},
            {"round": 1, "agent": "brutus", **brutus_r1},
            {"round": 2, "agent": "brutus", **brutus_r2},
            {"round": 3, "agent": "publius", **publius_r3},
            {"round": 4, "agent": "brutus", **brutus_r4},
        ]
        termination_reason = "round_limit"
        total_rounds = 4

    # Pre-mortem
    print("\n--- Pre-mortem ---")
    # Determine proposed resolution from the exchange
    proposed = (
        publius_r1.get("proposed_resolution", "") + " / " + brutus_r1.get("proposed_resolution", "")
    )
    premortem_raw = llm_call(
        [
            {"role": "system", "content": PREMORTEM_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Implications under tension:\n{impl_text}\n\n"
                    f"Proposed resolution for {delib_id}:\n{proposed}\n\n"
                    f"Exchange summary - Publius concessions: {publius_r3.get('concessions', [])}\n"
                    f"Brutus concessions: {brutus_r2.get('concessions', []) + brutus_r4.get('concessions', [])}\n\n"
                    f"Assume this resolution was implemented. What failure modes exist?"
                ),
            },
        ]
    )
    premortem = json.loads(premortem_raw)
    print(f"  Failure modes: {len(premortem.get('failure_modes', []))}")

    # Tension map synthesis
    print("\n--- Synthesis ---")
    synthesis_raw = llm_call(
        [
            {"role": "system", "content": SYNTHESIS_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Deliberation {delib_id}:\n\n"
                    f"Question: {question}\n\n"
                    f"Publius R1: {summarize_arg(publius_r1)}\n"
                    f"Brutus R1: {summarize_arg(brutus_r1)}\n"
                    f"Brutus R2 attacks/concessions: {summarize_round(brutus_r2)}\n"
                    f"Publius R3 attacks/concessions: {summarize_round(publius_r3)}\n"
                    f"Brutus R4 final: {summarize_round(brutus_r4)}\n"
                    f"Pre-mortem: {json.dumps([fm.get('scenario', '')[:100] for fm in premortem.get('failure_modes', [])])}\n\n"
                    f"Synthesize. Focus on what EMERGED from the exchange that wasn't in round 1."
                ),
            },
        ]
    )
    tension_map = json.loads(synthesis_raw)
    print(f"\n  AGREEMENT: {tension_map['agreement'][:150]}")
    print(f"  DISAGREEMENT: {tension_map['disagreement'][:150]}")
    print(f"  TYPE: {tension_map['disagreement_type']}")
    print(f"  NOVEL INSIGHT: {tension_map['novel_insight'][:200]}")

    # Build full record
    total_concessions = (
        len(brutus_r2.get("concessions", []))
        + len(publius_r3.get("concessions", []))
        + len(brutus_r4.get("concessions", []))
    )

    record = {
        "id": delib_id,
        "question": question,
        "trigger": {
            "type": "supremacy_tension",
            "source": "validate_supremacy()",
            "description": tension["description"],
            "relevant_axioms": tension["axioms"],
            "relevant_implications": list(tension["implications"].keys()),
            "relevant_precedents": tension["precedents"],
            "accumulated_dissents": [],
        },
        "rounds": rounds,
        "publius_final": publius_r1
        | {
            "concessions_made": publius_r3.get("concessions", []),
            "final_position_movement": publius_r3.get("position_movement", ""),
        },
        "brutus_final": brutus_r1
        | {
            "concessions_made": brutus_r2.get("concessions", []) + brutus_r4.get("concessions", []),
            "final_position_movement": brutus_r4.get("position_movement", ""),
        },
        "tension_map": {
            **tension_map,
            "failure_modes": [fm["scenario"] for fm in premortem.get("failure_modes", [])],
        },
        "process_metadata": {
            "model": MODEL,
            "total_rounds": total_rounds,
            "total_concessions": total_concessions,
            "termination": termination_reason,
            "convergence_check": convergence_check,
        },
        "status": "pending_operator_review",
        "operator_ruling": None,
        "ruling_precedent_id": None,
        "dissent_id": None,
        "created": datetime.now(UTC).isoformat(),
        "resolved": None,
    }

    return record


def main():
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for tension in TENSIONS:
        try:
            record = run_deliberation(tension)
            results.append(record)

            # Write YAML record
            out_path = PROFILES_DIR / f"{record['id']}-v5.yaml"
            with open(out_path, "w") as f:
                yaml.dump(
                    record,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    width=100,
                    allow_unicode=True,
                )
            print(f"\n  Written: {out_path}")

        except Exception as e:
            print(f"\n  ERROR on {tension['id']}: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            continue

    print(f"\n\n{'=' * 60}")
    print(f"COMPLETE: {len(results)}/{len(TENSIONS)} deliberations")
    print(f"{'=' * 60}")

    # Summary
    for r in results:
        tm = r["tension_map"]
        print(f"\n{r['id']}:")
        print(f"  Novel insight: {tm['novel_insight'][:200]}")
        print(f"  Concessions: {r['process_metadata']['total_concessions']}")
        print(f"  Disagreement type: {tm['disagreement_type']}")

    # Metric extraction + governance probe evaluation
    try:
        from shared.deliberation_metrics import (
            append_metrics,
            extract_metrics,
            format_batch_summary,
        )

        all_metrics = []
        for r in results:
            m = extract_metrics(r)
            append_metrics(m)
            all_metrics.append(m)
            if m.is_pseudo_deliberation:
                print(f"\n  ⚠ {m.deliberation_id}: pseudo-deliberation")
                print("    Diagnostic: no genuine engagement despite multiple rounds")
                print("    Suggested: review prompt framing or increase convergence threshold")
            elif m.activation_rate < 0.1 and m.total_rounds > 1:
                print(f"\n  ⚠ {m.deliberation_id}: low activation ({m.activation_rate:.0%})")
                print("    Diagnostic: agents not engaging with update conditions")
                print("    Suggested: strengthen condition-checking instructions in agent prompts")

        print(f"\n{format_batch_summary(all_metrics)}")

        # Run deliberation sufficiency probes
        from shared.sufficiency_probes import run_probes

        probe_results = run_probes(axiom_id="executive_function")
        delib_probes = [r for r in probe_results if r.probe_id.startswith("probe-delib-")]
        failing = [r for r in delib_probes if not r.met]
        if failing:
            print(f"\nGovernance probes: {len(delib_probes) - len(failing)}/{len(delib_probes)} passing")
            for f in failing:
                print(f"  FAIL {f.probe_id}: {f.evidence}")
        else:
            print(f"\nGovernance probes: {len(delib_probes)}/{len(delib_probes)} passing")
    except Exception as e:
        print(f"\n  WARN: evaluation failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
