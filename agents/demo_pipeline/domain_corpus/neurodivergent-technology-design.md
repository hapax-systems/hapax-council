---
topic: neurodivergent-technology-design
keywords: [universal design, neurodivergent UX, ADHD tools, autism accommodation, sensory considerations, routine support]
relevance: [accessibility, executive-function, proactive-design, notification-design]
last_reviewed: 2026-03-05
---

# Neurodivergent Technology Design

## Overview

Technology design for neurodivergent users exists at the intersection of accessibility, universal design, and cognitive science. While mainstream accessibility work has historically focused on sensory and motor disabilities (screen readers, keyboard navigation, color contrast), the accommodation needs of neurodivergent users — particularly those with ADHD, autism, dyslexia, and related conditions — require a different design lens. The challenges are cognitive, executive, and sensory rather than primarily perceptual or motor. This document surveys the design principles, research evidence, and practical implications for building systems that accommodate neurodivergent users, with specific attention to how an autonomous agent system can serve as infrastructure-level accommodation.

## Universal Design and Its Extensions

### Universal Design for Learning (UDL)

Rose and Meyer (2002) and Rose (2016) developed the Universal Design for Learning framework, which extends architectural universal design principles (Connell et al., 1997) into the cognitive domain. UDL's three principles:

1. **Multiple means of engagement** — provide varied ways to motivate and sustain interest. Different learners (and users) are motivated by different things: novelty, routine, autonomy, structure, challenge, support.

2. **Multiple means of representation** — present information in multiple formats. Some users process text efficiently; others need visual representations; others benefit from audio. The key insight is that representation flexibility accommodates cognitive diversity, not just sensory differences.

3. **Multiple means of action and expression** — provide varied ways to interact and demonstrate understanding. For technology design, this means multiple interaction modalities: CLI, GUI, chat, notifications, automated reports.

UDL's core insight — that variability is the norm, not the exception — is foundational for neurodivergent technology design. Designing for the "average user" systematically excludes users whose cognitive profiles differ from the assumed average.

### Inclusive Design

Treviranus (2014) and the Inclusive Design Research Centre at OCAD University define inclusive design as design that considers the full range of human diversity with respect to ability, language, culture, gender, and age. Three dimensions distinguish inclusive design from accessibility compliance:

1. **Recognize diversity and uniqueness.** Design for the margins, not the center. Solutions that work for edge cases often improve the experience for everyone.

2. **Inclusive process.** Users with diverse needs should participate in the design process, not merely be consulted after the fact.

3. **Broader beneficial impact.** Design choices that accommodate specific needs frequently benefit all users. Curb cuts designed for wheelchairs benefit cyclists, parents with strollers, and delivery workers.

The "curb cut effect" (Blackwell, 2016) is particularly relevant: many accommodations designed for neurodivergent users — clear structure, reduced cognitive load, proactive notifications, consistent patterns — improve usability for all users. A system designed to compensate for ADHD executive function deficits produces a system that is more usable for neurotypical operators as well.

## ADHD-Specific Design Considerations

### Time Blindness and Temporal Design

Time blindness — the subjective distortion of time perception — is one of the most functionally impairing features of ADHD. Barkley and Fischer (2019) demonstrated that adults with ADHD show significant impairment in time estimation, time reproduction, and temporal discounting compared to controls. The practical manifestations:

- **Underestimation of duration:** tasks that will take 2 hours feel like they'll take 30 minutes
- **Missing transitions:** the passage from "plenty of time" to "deadline passed" happens without subjective awareness
- **Temporal myopia:** future consequences are deeply discounted, making long-term planning feel abstract and uncompelling

Design implications for autonomous systems:

**External temporal structure.** The system provides temporal scaffolding that the operator's internal clock cannot: health checks every 15 minutes, daily briefings at fixed times, weekly maintenance on schedules. These create an external rhythm that compensates for impaired internal time-keeping.

**Proactive time-anchored notifications.** Meeting prep generated before the meeting, briefings delivered before the workday begins, alerts delivered when action is needed — not stored in a queue to be checked "when the operator remembers."

**Deadline awareness.** Systems that make deadlines visible and salient, rather than relying on the operator to track them internally.

### Hyperfocus and Task Switching

ADHD hyperfocus — the capacity for intense, sustained attention on engaging tasks — is the complement of distractibility. Ashinoff and Abu-Akel (2021) characterize hyperfocus as a state of heightened attentional engagement that is difficult to disengage from voluntarily. Design implications:

**Respect hyperfocus.** Notifications should be interruptive only for genuinely urgent matters. Routine information (daily briefings, weekly reports) should be available when the operator surfaces from hyperfocus, not forced into their attention during deep work.

**Enable graceful re-entry.** When the operator does emerge from hyperfocus (or is interrupted), the system should make it easy to understand what happened while they were focused. The briefing agent and activity analyzer serve this function — they provide a summary of system state changes.

**Support task switching.** Context switching is costly for everyone but disproportionately costly for ADHD (Cepeda et al., 2001). The system reduces forced context switches by handling routine matters autonomously — the operator doesn't need to interrupt creative work to check if Docker containers are healthy.

### Task Initiation and Activation Energy

Task initiation — beginning a task — is a specific executive function deficit in ADHD, distinct from the ability to sustain effort once started. The subjective experience is not "I don't want to do this" but "I cannot make myself begin." This parallels the physics concept of activation energy: the energy required to start a reaction exceeds the energy required to sustain it.

Design implications:

**Reduce activation energy for common tasks.** Templates, quick-capture macros, pre-populated forms, and sensible defaults all reduce the cognitive cost of task initiation. The system's QuickAdd macros (9 macros for common note types) and Templater templates (16 templates) directly address this.

**Automate initiation entirely where possible.** If a task should happen regularly, the system should initiate it — not present a reminder for the operator to initiate it. Reminders require the operator to overcome the initiation barrier; automation bypasses it entirely.

**Provide starting points, not blank pages.** Pre-generated meeting prep documents, pre-populated briefings, and agent-generated drafts are more valuable than blank templates because they provide cognitive momentum.

## Autism-Specific Design Considerations

### Sensory Considerations

Many autistic individuals experience sensory processing differences — heightened sensitivity to visual, auditory, or tactile stimulation (Marco et al., 2011). For technology design:

**Visual clutter.** Interfaces with excessive visual elements, animations, or unpredictable layout changes can be overwhelming. Clean, predictable interfaces with consistent structure reduce sensory load.

**Notification modality.** Auditory notifications may be startling or aversive. The system's notification architecture (ntfy push notifications with configurable priority, desktop notifications via notify-send) allows the operator to choose modality and intensity.

**Consistent patterns.** Unpredictable interface behavior — elements that move, change appearance, or behave differently in different contexts — creates sensory and cognitive dissonance. Consistent conventions (same CLI patterns, same notification format, same file naming) provide the predictability that autistic users often strongly prefer.

### Routine and Structure

Autistic individuals frequently rely on routines and structured environments for self-regulation (Gotham et al., 2015). Disruptions to routine can be genuinely destabilizing, not merely inconvenient. Technology design implications:

**Support routine maintenance.** The system's scheduled operations (daily briefings at 07:00, meeting prep at 06:30, weekly scans on defined days) create and maintain routines that the operator can rely on.

**Provide structure for unstructured tasks.** When a task is inherently unstructured (creative writing, brainstorming, architecture exploration), the system can provide scaffolding that creates manageable structure without constraining the content.

**Make changes explicit.** When the system's behavior changes (new agent, modified schedule, updated model), the change should be explicitly communicated, not silently deployed. Unexpected behavioral changes are disorienting.

### Cognitive Strengths

Neurodivergent design should accommodate challenges *and* leverage strengths. Common autistic cognitive strengths include:

- **Pattern recognition:** ability to identify patterns, inconsistencies, and structures that neurotypical individuals miss
- **Systematic thinking:** preference for and skill in systematic, rule-based analysis
- **Deep domain knowledge:** tendency toward intense, thorough engagement with topics of interest
- **Attention to detail:** capacity for fine-grained analysis

The system's architecture leverages these strengths: the operator designs the system architecture (pattern recognition, systematic thinking), sets the axioms (rule-based analysis), and provides deep domain knowledge. The system handles the routine maintenance that these strengths don't naturally address.

## The Intersection: ADHD + Autism

The co-occurrence of ADHD and autism is well-documented. Leitner (2014) found that 30-80% of autistic individuals meet criteria for ADHD, and 20-50% of those with ADHD have autistic traits. The combination creates a distinctive profile:

**Competing needs.** ADHD craves novelty and stimulation; autistic processing favors routine and predictability. The system must accommodate both: provide stable, predictable infrastructure (autistic need for routine) while the operator's actual work involves novel problem-solving (ADHD need for stimulation).

**Executive function compounded.** Both conditions independently impair executive function, and the combination is more than additive. The system's aggressive externalization of executive functions (automated routines, proactive notifications, zero-config defaults) addresses this compounded impairment.

**Strengths compounded.** The combination also compounds strengths: the systematic depth of autistic thinking combined with the creative divergence of ADHD produces novel connections and unexpected insights. The system should support and enable this creative pattern, not constrain it.

## Proactive vs. Reactive Design

Traditional software is reactive — it waits for user input and responds. For neurodivergent users, this model has a fundamental flaw: it assumes the user will initiate interactions at appropriate times. When task initiation is impaired, a reactive system becomes effectively inaccessible — not because the user can't use it, but because they can't make themselves begin using it.

Proactive design inverts the interaction model:

- The system generates the morning briefing before the operator asks
- Health checks run on timers, not on operator-remembered invocations
- Meeting prep materializes before the meeting, not when the operator remembers to request it
- Notifications push to the operator rather than waiting in a queue to be checked

This proactive approach directly addresses the task initiation deficit: the system performs the initiation, and the operator responds. Responding to a delivered briefing is cognitively cheaper than remembering to request one.

## Notification Design for Neurodivergent Users

Notification design is particularly consequential for neurodivergent users:

**Notification fatigue.** Both ADHD and autistic individuals are susceptible to notification fatigue — the tendency to habituate to notifications and eventually ignore them entirely. The system must be judicious: only notify for actionable items, consolidate where possible (daily digests rather than per-event notifications), and preserve the signal-to-noise ratio.

**Urgency calibration.** If everything is urgent, nothing is. The system's notification architecture should support priority levels, with genuinely urgent notifications (service down, backup failed) clearly distinguished from informational notifications (briefing available, digest ready).

**Delivery timing.** Notifications delivered during hyperfocus are either ignored or disruptive. Where possible, non-urgent notifications should be batched and delivered at natural transition points (morning briefing, end of day).

**Actionability.** Every notification should include what to do about it. A notification that says "Qdrant unhealthy" without remediation guidance creates anxiety without enabling resolution — particularly problematic for individuals whose executive function makes "figure out what to do" a significant additional cognitive burden.

## References

- Ashinoff, B. K., & Abu-Akel, A. (2021). Hyperfocus: The forgotten frontier of attention. *Psychological Research*, 85(1), 1-19.
- Barkley, R. A., & Fischer, M. (2019). Time estimation and reproduction in young adults with ADHD combined type. *Journal of Attention Disorders*, 23(4), 351-361.
- Blackwell, A. G. (2016). The curb cut effect. *Stanford Social Innovation Review*, Winter 2017.
- Cepeda, N. J., Cepeda, M. L., & Kramer, A. F. (2001). Task switching and attention deficit hyperactivity disorder. *Journal of Abnormal Child Psychology*, 28(3), 213-226.
- Connell, B. R., Jones, M., Mace, R., Mueller, J., Mullick, A., Ostroff, E., ... & Vanderheiden, G. (1997). The principles of universal design. *The Center for Universal Design, NC State University*.
- Gotham, K., Bishop, S. L., Hus, V., Huerta, M., Lund, S., Buja, A., ... & Lord, C. (2015). Exploring the relationship between anxiety and insistence on sameness in autism spectrum disorders. *Autism Research*, 6(1), 33-41.
- Leitner, Y. (2014). The co-occurrence of autism and attention deficit hyperactivity disorder in children — what do we know? *Frontiers in Human Neuroscience*, 8, 268.
- Marco, E. J., Hinkley, L. B. N., Hill, S. S., & Nagarajan, S. S. (2011). Sensory processing in autism: A review of neurophysiologic findings. *Pediatric Research*, 69(5 Pt 2), 48R-54R.
- Rose, D. H. (2016). Universal design for learning. In L. Meyer, D. Rose, & D. Gordon (Eds.), *Universal Design for Learning: Theory and Practice*. CAST Professional Publishing.
- Rose, D. H., & Meyer, A. (2002). *Teaching Every Student in the Digital Age: Universal Design for Learning*. ASCD.
- Treviranus, J. (2014). Leveraging the web as a platform for economic inclusion. *Behavioral Sciences & the Law*, 32(1), 94-103.
