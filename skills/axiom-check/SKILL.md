---
name: axiom-check
description: Check axiom compliance of the current project. Use when the user asks about axiom status, compliance, governance, or runs /axiom-check.
---

Check axiom compliance of the current project.

Run:

```bash
cd ~/projects/hapax-council && eval "$(direnv export bash 2>/dev/null)" && uv run python -c "
import asyncio
from shared.axiom_registry import load_axioms, load_implications, validate_supremacy
from shared.axiom_precedents import PrecedentStore

async def check():
    # Constitutional axioms
    const = load_axioms(scope='constitutional')
    if const:
        print('## Constitutional Axioms')
        for ax in const:
            imps = load_implications(ax.id)
            t0 = [i for i in imps if i.tier == 'T0']
            print(f'\n### {ax.id} (weight={ax.weight}, {len(t0)} T0 blocks, {len(imps)} total)')
            for imp in t0:
                print(f'  [BLOCK] {imp.id}: {imp.text}')
            suf = [i for i in imps if i.mode == 'sufficiency']
            if suf:
                by_level = {}
                for s in suf:
                    by_level[s.level] = by_level.get(s.level, 0) + 1
                parts = [f'{v} {k}' for k, v in sorted(by_level.items())]
                print(f'  Sufficiency: {len(suf)} requirements ({chr(44).join(parts)})')

    # Domain axioms
    domain = load_axioms(scope='domain')
    if domain:
        print(f'\n## Domain Axioms ({len(domain)})')
        for ax in domain:
            imps = load_implications(ax.id)
            t0 = [i for i in imps if i.tier == 'T0']
            print(f'\n### {ax.id} [domain:{ax.domain}] (weight={ax.weight}, {len(t0)} T0 blocks, {len(imps)} total)')
            for imp in t0:
                print(f'  [BLOCK] {imp.id}: {imp.text}')
            suf = [i for i in imps if i.mode == 'sufficiency']
            if suf:
                by_level = {}
                for s in suf:
                    by_level[s.level] = by_level.get(s.level, 0) + 1
                parts = [f'{v} {k}' for k, v in sorted(by_level.items())]
                print(f'  Sufficiency: {len(suf)} requirements ({chr(44).join(parts)})')

    # Supremacy check
    tensions = validate_supremacy()
    if tensions:
        print(f'\n## Supremacy: {len(tensions)} tension(s) for review')
        for t in tensions:
            print(f'  - {t.domain_impl_id}: {t.note}')
    else:
        print('\nSupremacy: no tensions')

    try:
        store = PrecedentStore()
        pending = await store.get_pending_review()
        if pending:
            print(f'\n## Pending Review: {len(pending)} agent precedent(s)')
            for p in pending:
                print(f'  - {p.id}: {p.situation[:80]}...')
        else:
            print('\nNo pending precedents.')
    except Exception as e:
        print(f'\nPrecedent store unavailable: {e}')

asyncio.run(check())
"
```

Review the output and suggest any compliance concerns for the current work.
