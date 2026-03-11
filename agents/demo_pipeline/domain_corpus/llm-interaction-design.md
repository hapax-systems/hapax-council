---
topic: llm-interaction-design
keywords: [human-AI interaction, agentic UX, trust calibration, tool use, prompt engineering, AI transparency]
relevance: [tiered-architecture, agent-design, chat-interface, observability]
last_reviewed: 2026-03-05
---

# LLM Interaction Design and Agentic UX

## Overview

The design of human-LLM interaction is an emerging discipline that draws on decades of human-computer interaction (HCI) research while confronting fundamentally new challenges. LLMs are probabilistic, opaque, and capable of generating plausible but incorrect output — properties that demand new interaction patterns beyond traditional deterministic software design. For an autonomous agent system that places LLMs at multiple tiers of operation (interactive chat, on-demand analysis, autonomous monitoring), interaction design determines whether the system is trusted, usable, and effective. This document surveys the foundational research and its application to tiered agent architecture.

## Foundations: Guidelines for Human-AI Interaction

Amershi et al. (2019) at Microsoft Research produced the most widely cited set of human-AI interaction guidelines, derived from a systematic review of 150+ AI-related design recommendations and validated across 20 AI products. Their 18 guidelines are organized around four temporal phases:

### Initially (before interaction)

- **G1: Make clear what the system can do.** Set expectations about capabilities and limitations. For an agent system, this means each agent's scope and confidence should be explicit.
- **G2: Make clear how well the system can do what it can do.** Communicate uncertainty and reliability. Health monitoring agents that report deterministic checks should be distinguished from LLM agents that provide probabilistic analysis.

### During Interaction

- **G3: Time services based on context.** Deliver information when contextually relevant, not on a fixed schedule alone. The system's point-of-performance intervention principle aligns directly.
- **G4: Show contextually relevant information.** Reduce information overload by filtering to what matters now.
- **G5: Match relevant social norms.** AI behavior should align with social expectations — a briefing agent should write like a brief, not like a chatbot.
- **G6: Mitigate social biases.** Ensure system outputs don't reflect or amplify harmful biases.

### When Wrong

- **G8: Support efficient invocation.** Make it easy for the user to invoke the AI when needed — low activation cost.
- **G9: Support efficient dismissal.** Make it equally easy to dismiss or override AI output. The operator must be able to ignore any agent's recommendation without friction.
- **G10: Support efficient correction.** When the AI is wrong, enable quick correction without losing context.

### Over Time

- **G13: Learn from user behavior.** Adapt to the operator's patterns over time (the profiler agent's role).
- **G16: Convey the consequences of user actions.** Make clear what happens when the operator acts on agent recommendations.
- **G18: Notify users about changes.** When the system's behavior changes (model updates, new agents, modified schedules), communicate explicitly.

These guidelines provide a principled checklist for evaluating agent interaction design.

## Agentic UX: Beyond Chat

The term "agentic UX" emerged in 2023-2024 to describe interaction patterns where AI systems take autonomous actions rather than merely responding to prompts. This represents a fundamental shift from the conversational paradigm:

**Conversational AI** (chatbots, assistants): the user initiates every interaction, the AI responds, the user evaluates. The locus of control is with the user at all times.

**Agentic AI** (autonomous agents, multi-step workflows): the AI initiates actions, makes intermediate decisions, and may complete complex tasks with minimal user involvement. The locus of control shifts partially to the system.

Nielsen Norman Group's research on AI-driven interfaces (Budiu & Laubheimer, 2023) identifies key challenges of agentic UX:

**Visibility of system state.** When an agent operates autonomously (health checks, drift detection, knowledge maintenance), the operator needs visibility into what is happening without being required to monitor continuously. This tension — visibility without monitoring burden — is resolved through observability infrastructure that supports on-demand inspection (Langfuse traces, health history) combined with exception-based alerting.

**Appropriate automation level.** Parasuraman, Sheridan, and Wickens (2000) defined a 10-level automation taxonomy ranging from full human control to full automation. Different agent tasks warrant different automation levels:

- **Level 10 (full automation):** Health checks, scheduled backups, knowledge maintenance — no human involvement needed for routine operation
- **Level 7 (execute automatically, inform human):** Briefing generation, meeting prep — the system acts and notifies, the human reviews
- **Level 4 (suggest alternatives):** Research agent, code review — the system provides analysis, the human decides
- **Level 1 (human decides everything):** Architecture decisions, people management — the system provides context but never recommends

The three-tier architecture maps naturally to this taxonomy: Tier 3 (autonomous) operates at levels 7-10, Tier 2 (on-demand) at levels 3-6, and Tier 1 (interactive) at levels 1-4.

## Trust Calibration

Lee and See (2004) established the foundational framework for trust in automation, identifying three dimensions:

- **Performance** — the competence of the automated system (does it work?)
- **Process** — the degree to which the system's algorithms are understandable (how does it work?)
- **Purpose** — the degree to which the system's intent aligns with the user's goals (why does it work this way?)

For LLM-based systems, trust calibration is particularly challenging because:

**LLMs fail unpredictably.** Unlike traditional software where failure modes are enumerable, LLMs can produce plausible but incorrect output in ways that are difficult to detect. This makes trust calibration harder — the operator cannot develop reliable intuitions about when to trust and when to verify.

**Overreliance is a documented risk.** Buçinca et al. (2021) demonstrated that explanations and confidence indicators often increase trust without improving decision quality — users trust explainable AI more even when the explanations are misleading. This argues for designing systems that encourage appropriate skepticism rather than maximizing trust.

**Appropriate trust requires transparency.** Langfuse observability, where every LLM call is traced with inputs, outputs, token counts, and latency, serves a trust calibration function. The operator can inspect any agent's reasoning chain, verify that the correct model was used, and identify when an agent is operating outside its competence.

Design strategies for trust calibration in the system:

1. **Deterministic where possible.** Health monitoring uses zero-LLM checks. Drift detection compares source code against documentation deterministically before using an LLM for synthesis. This establishes a trust baseline — when the system reports a container is down, it is factually correct.

2. **Clearly delineated LLM boundaries.** Agents that use LLMs are explicitly marked. The operator knows which outputs are deterministic facts and which are probabilistic synthesis.

3. **Verifiable outputs.** Briefings cite their sources (health data, activity logs). Research agent outputs include Qdrant retrieval context. The operator can trace any claim to its origin.

4. **Graceful failure communication.** When an agent fails or produces uncertain output, this is communicated explicitly with suggested next actions — not hidden or minimized.

## Tool Use and Structured Outputs

Schick et al. (2023) formalized the concept of tool-augmented language models in "Toolformer," demonstrating that LLMs can learn to invoke external tools (calculators, search engines, APIs) to overcome their inherent limitations. The broader ecosystem has since adopted tool use as a standard pattern:

**Function calling** (OpenAI, Anthropic): LLMs generate structured tool invocations that are executed by the host system, with results returned for further reasoning. This pattern enables agents to interact with real infrastructure — querying Qdrant, checking Docker container status, reading files.

**Structured outputs** (JSON mode, schema-constrained generation): LLMs produce outputs conforming to predefined schemas, enabling reliable downstream processing. For agent systems, this means agent outputs can be programmatically consumed, stored, and displayed — not just read by humans.

**ReAct pattern** (Yao et al., 2022): alternating reasoning and action steps, where the LLM reasons about what tool to use, uses it, observes the result, and reasons again. This pattern is foundational to most production agent systems.

The system's tool use design follows several principles from this research:

- **Tools are well-scoped.** Each tool does one thing with clear semantics. A Qdrant search tool searches; it does not also summarize or filter.
- **Tool results are transparent.** The operator can see what tools were invoked, what arguments were passed, and what results were returned (via Langfuse traces).
- **Fallback chains.** When a tool fails (Qdrant unreachable, model overloaded), the system degrades gracefully rather than producing garbage output.

## Google PAIR: People + AI Research

Google's People + AI Research (PAIR) initiative has produced extensive practical guidance for human-AI interaction, synthesized in their People + AI Guidebook (2019, updated ongoing). Key principles relevant to agent system design:

**Determine if AI adds value.** Not every problem benefits from an LLM. The system's use of deterministic checks (health monitoring, introspection) alongside LLM-powered analysis (briefings, research) reflects this principle — LLMs are used where probabilistic synthesis adds genuine value, not as a universal hammer.

**Set the right expectations.** PAIR recommends showing examples of both good and poor AI performance to calibrate user expectations. In practice, this means the system should not present LLM output with false confidence — uncertainty should be visible.

**Design for failure gracefully.** AI systems will be wrong. The interaction design should assume errors and make recovery easy. For an autonomous system, this means self-healing loops (health monitor auto-fix), explicit error notifications, and easy manual override.

**Feedback and adaptation.** PAIR recommends mechanisms for users to provide feedback that improves system performance. The profiler agent serves this function — it learns about the operator over time, and the operator can correct mischaracterizations.

## The Conversational Interface in Agent Systems

Despite the shift toward agentic patterns, conversational interfaces remain the primary interaction modality for interactive-tier agents. Clark et al. (2019) surveyed the state of speech and language HCI research, identifying persistent challenges:

**Expectation management.** Users anthropomorphize conversational interfaces, projecting capabilities the system does not have. Clear capability communication (what the system can and cannot do) is essential.

**Repair mechanisms.** Conversation breaks down. The interface needs mechanisms for the user to redirect, correct, or restart without losing context.

**Mixed-initiative interaction.** The most effective conversational agents support both user-initiated and system-initiated dialogue. The system's chat interface with slash commands (user-initiated) alongside proactive nudges (system-initiated) exemplifies this pattern.

## Transparency and Explainability

Liao and Vaughan (2024) provide a comprehensive survey of explainable AI (XAI) research, distinguishing between:

- **Model-level transparency** — understanding how the model works internally
- **Output-level explanations** — understanding why a specific output was produced
- **System-level transparency** — understanding how the overall system operates

For agent systems, system-level transparency is most relevant. The operator does not need to understand transformer attention patterns; they need to understand:

1. Which agents ran and when
2. What data each agent consumed
3. What model was used for each LLM call
4. What the agent's output was
5. How confident the agent is

This is precisely what observability infrastructure (Langfuse) provides — system-level transparency through comprehensive tracing.

## References

- Amershi, S., Weld, D., Vorvoreanu, M., Fourney, A., Nushi, B., Collisson, P., ... & Horvitz, E. (2019). Guidelines for human-AI interaction. *Proceedings of the 2019 CHI Conference on Human Factors in Computing Systems*, 1-13.
- Buçinca, Z., Malaya, M. B., & Gajos, K. Z. (2021). To trust or to think: Cognitive forcing functions can reduce overreliance on AI in AI-assisted decision-making. *Proceedings of the ACM on Human-Computer Interaction*, 5(CSCW1), 1-21.
- Budiu, R., & Laubheimer, P. (2023). AI-driven interfaces: Emerging UX patterns. *Nielsen Norman Group*.
- Clark, L., Pantidi, N., Cooney, O., Doyle, P., Garber, D., Golsteijn, C., ... & Cowan, B. R. (2019). What makes a good conversation? Challenges in designing truly conversational agents. *Proceedings of the 2019 CHI Conference on Human Factors in Computing Systems*, 1-12.
- Google PAIR. (2019). *People + AI Guidebook*. https://pair.withgoogle.com/guidebook
- Lee, J. D., & See, K. A. (2004). Trust in automation: Designing for appropriate reliance. *Human Factors*, 46(1), 50-80.
- Liao, Q. V., & Vaughan, J. W. (2024). AI transparency in the age of LLMs: A human-centered research roadmap. *Harvard Data Science Review*, 6(1).
- Parasuraman, R., Sheridan, T. B., & Wickens, C. D. (2000). A model for types and levels of human interaction with automation. *IEEE Transactions on Systems, Man, and Cybernetics — Part A*, 30(3), 286-297.
- Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Hambro, E., ... & Scialom, T. (2023). Toolformer: Language models can teach themselves to use tools. *Advances in Neural Information Processing Systems*, 36.
- Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2022). ReAct: Synergizing reasoning and acting in language models. *arXiv preprint arXiv:2210.03629*.
