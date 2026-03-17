# Hapax Corpora: Content Scheduling Intelligence Research

Research into how an ambient display agent should decide what content to show, when,
for how long, and how often -- given 10 injection source categories and an operator
with ADHD/autism who explicitly rejects visual emptiness.

---

## 1. Attention Management for Ambient Displays

### The SEEV Model (Wickens et al., 2003)

The most directly applicable framework from aviation human factors. SEEV predicts
where visual attention goes based on four weighted factors:

- **Salience** (bottom-up): How much the element stands out physically -- motion,
  color contrast, size. Motion captures attention more reliably than color or animation.
- **Effort** (bottom-up): How much perceptual work is needed to process it.
  Lower effort = more likely to be noticed peripherally.
- **Expectancy** (top-down): How likely the operator expects new information at
  that location/channel. Habitual patterns build expectancy.
- **Value** (top-down): How relevant the information is to current goals.

The model predicts **percentage dwell time** (PDT) -- the proportion of attention
allocated to each area. For Hapax Corpora, this maps directly to: how much screen
real estate and persistence should each injection source get?

**Actionable insight**: Each content source can be scored on these four dimensions.
A health alert during high-stress biometrics = high salience + high value. A profile
fact during deep coding = low value + low expectancy. The SEEV score becomes the
utility input.

### The Matthews Peripheral Display Toolkit (2004)

Defines five **notification levels** for peripheral displays:

1. **Ignore** -- no display change needed
2. **Change blind** -- subtle update that won't be noticed unless the operator
   happens to look (color drift, slow text fade)
3. **Make aware** -- noticeable but non-interruptive change (new text appears,
   element moves)
4. **Interrupt** -- demands attention shift (flash, motion burst, contrast spike)
5. **Demand action** -- blocks peripheral mode entirely

Each injection source should map to one of these levels based on urgency. The toolkit
also identifies three concerns for peripheral display developers:

- **Abstraction**: Raw data must be simplified to be glanceable
- **Notification level assignment**: Rules mapping input conditions to urgency tiers
- **Transitions**: How the display changes when new content arrives (abrupt for
  interrupt-level, gradual for change-blind)

### Calm Technology Principles (Weiser & Brown, 1995; Case, 2015)

Core principle: information should move smoothly between periphery and center of
attention, and back. The canonical example is Weiser's "Dangling String" -- an
ethernet cable visualization that twitches with network traffic. You notice it
when you want to; it doesn't demand attention.

For Hapax Corpora, the key implication is that **most content should be
change-blind or make-aware level**. The display should feel like a living
environment, not a notification center. Only true alerts (health, governance
violations) should reach interrupt level.

### ATC and ICU Alert Design

Both domains have extensively studied **alert fatigue** -- the phenomenon where
too many alarms cause operators to ignore or disable them:

- ICU research: 85-99% of clinical alarms are false positives. The "cry wolf
  effect" causes operators to ignore even genuine alarms.
- ATC research: "Subtle visual ambient alarms can be effective, with little to
  no impact from opacity and duration variations" -- even quiet signals work if
  the operator trusts the system.
- ICU graduated delay: Severe deviations alarm immediately; moderate deviations
  get a 14-19 second delay (reduces false alarms 50-67%).
- Trend-based alarms complement threshold-based alarms, reducing false positives
  by 33%.

**Actionable insight**: Hapax Corpora should use graduated urgency delays. A
biometric spike might wait 10 seconds before visual escalation (is it transient?).
A governance violation escalates immediately. Most content is ambient and never
escalates at all.

---

## 2. Content Scheduling Under Uncertainty

### Multi-Armed Bandits for Content Selection

The core problem: given N content sources, which one to show next, balancing
exploitation (show what's worked) with exploration (try less-shown sources)?

**Epsilon-greedy** (simplest):
- With probability (1-epsilon), show the highest-utility content
- With probability epsilon, show a random content source
- Typical epsilon: 0.1-0.2 (explore 10-20% of the time)
- Dead simple to implement, no complex math

**Softmax / Boltzmann exploration** (recommended for Hapax Corpora):
- Compute a utility score for each content source
- Apply softmax with temperature to convert scores to probabilities
- Sample from the resulting distribution
- Temperature controls randomness: high temp = more uniform, low temp = greedy
- At temperature 1.0, options weighted 2, 3, 5 have probabilities ~20%, 30%, 50%

**Thompson Sampling** (more principled):
- Maintain a Beta distribution for each content source's "success rate"
- Sample from each distribution, pick the highest sample
- Naturally balances exploration/exploitation
- Slightly more complex but very robust

**Contextual bandits** extend these with context features (time of day, operator
activity, biometric state). The context determines which content is likely
valuable right now.

**Practical recommendation**: Softmax with temperature is the sweet spot for
Hapax Corpora. It requires only:
1. A utility score per content source (computed from SEEV-like factors)
2. A temperature parameter (can be fixed or adjusted by activity state)
3. A single random sample

This runs in microseconds and produces naturally varied but preference-weighted
content selection.

### Recency and Freshness Scoring

Content that was shown recently should be penalized to prevent repetition:

- **Exponential decay**: `recency_penalty = e^(-lambda * time_since_shown)`
  Drops fast initially, then levels off. Lambda controls half-life.
- **Half-life model**: Set a half-life per content type. Profile facts might have
  a 5-minute half-life (show again after 5 min at 50% weight). Health alerts
  have a 30-second half-life (re-eligible quickly if still relevant).
- **Evergreen vs ephemeral**: Some content (shader modulation, time-of-day
  evolution) is continuous and doesn't need recency penalization. Discrete items
  (profile facts, nudges) do.

---

## 3. Temporal Models of Interest

### Habituation Curves

Repeated exposure to the same stimulus reduces attention -- this is habituation.
Key findings:

- **The 2.5-second attention benchmark**: In media research, the first 2.5 seconds
  of exposure have disproportionate impact. After 2.5 seconds, the attention
  curve flattens dramatically.
- **Inverse duration effect**: For higher-level stimuli (words, faces), longer
  exposure actually *decreases* recognition performance. The brain stops
  processing after initial encoding.
- **Semi-familiarity preference**: Fully novel stimuli and fully familiar stimuli
  are both less preferred than semi-familiar ones (optimal arousal model). This
  suggests content should be shown often enough to be recognizable but not so
  often it becomes wallpaper.
- **Neural habituation as parsing**: The brain uses habituation to suppress
  recently-identified visual objects, freeing perception for new stimuli. This
  is *functional* -- it means the display should actively rotate content to work
  *with* this mechanism.

### Practical Dwell Time Recommendations

Based on habituation research and ambient display literature:

| Content Type | Recommended Dwell | Rationale |
|---|---|---|
| Profile facts (text) | 20-45s | Long enough to read peripherally, short enough to not habituate |
| Health/governance alerts | 5-15s at interrupt level, then fade to ambient | Graduated: grab attention, then release |
| Camera feed injection | 30-90s | Visual complexity sustains interest longer than text |
| Shader parameter changes | Continuous/gradual | These ARE the ambient layer; smooth evolution, not discrete |
| Activity label | Persistent until change | Static reference information, not attention-competing |
| Supplementary cards | 30-60s | Tool results from conversation; reference until stale |
| Nudges | 45-90s at make-aware, then fade | Need enough time to register peripherally |
| Voice state indicator | Persistent during session | Functional signal, not content |
| Biometric modulation | Continuous | Maps to shader parameters; no discrete "show" |
| Studio moments | 10-20s flash | Ephemeral by nature (audio events) |

### The Novelty Window

From habituation research, there's an optimal "novelty window" where content
is interesting:

```
Interest
  ^
  |     /\
  |    /  \
  |   /    \----------- (ambient wallpaper level)
  |  /
  | /
  +-------------------------> Exposure count
    1st  2nd  3rd  4th+
```

First exposure: high novelty, high interest. Second: still interesting, pattern
recognition engaged. Third: becoming familiar, interest declining. Fourth+:
habituated, becomes background texture.

For profile facts (which number in the hundreds in Qdrant), this means any given
fact should appear roughly every 15-30 minutes to stay in the semi-familiar zone.
With a pool of ~200 facts and 30-second display windows, the natural rotation
cycle is about 100 minutes before repeats -- well within the novelty window.

---

## 4. Context-Dependent Relevance

### Interruptibility Research

Gloria Mark's foundational research on interruptions:

- **23 minutes 15 seconds**: Average time to regain deep focus after an
  interruption.
- **Interrupted tasks take 2x longer** and contain **2x as many errors**.
- **Same-context interruptions are beneficial**; different-context interruptions
  are disruptive. A coding-related nudge during coding = helpful. A calendar
  reminder during deep coding = harmful.
- **275 interruptions per day** is typical in office environments -- the ambient
  display must NOT contribute to this.

### Activity-Based Content Mapping

| Operator Activity | Appropriate Content | Avoid |
|---|---|---|
| **Deep coding** | Shader warmth, profile facts (tech-related), GPU status | Calendar alerts, social nudges, camera feeds |
| **Music production** | Audio-reactive visuals, studio moments, camera artistry | Text-heavy content, governance alerts (unless critical) |
| **Meeting/call** | Minimal -- voice state indicator, very subtle ambient | Anything attention-competing; reduce all to change-blind level |
| **Idle/browsing** | Full content rotation, camera feeds, profile facts, nudges | Nothing to avoid -- this is maximum injection time |
| **Break/away** | Time-of-day evolution, slow shader drift | Everything discrete -- operator isn't watching |

### Implementation Approach

The activity label (injection source #7) becomes the **context key** that modulates
all other injection sources. Each source gets a per-activity **relevance multiplier**:

```
utility(source, activity) = base_utility(source) * relevance(source, activity)
                            * recency_penalty(source) * salience_boost(source)
```

During "deep coding", most sources get relevance multiplier 0.1-0.3 (still possible
but unlikely). During "idle", all sources get 1.0. This naturally reduces
interruption density during focus work without completely silencing the display
(which the operator explicitly rejects).

---

## 5. Neurodivergent Attention Patterns

### ADHD: The Optimal Stimulation Model

Zentall's Optimal Stimulation Theory (OST) is the key framework:

- ADHD brains have a **higher stimulation threshold** for optimal performance
  due to lower baseline dopamine levels.
- **Understimulation is actively uncomfortable** -- it produces restlessness,
  task-switching, and self-stimulation behaviors.
- The operator's rejection of emptiness ("I DON'T LIKE EMPTINESS AT ALL") is
  a textbook expression of this. An empty display = understimulation.
- The **Yerkes-Dodson curve is narrower** for ADHD: the zone between
  understimulation and overwhelm is smaller, requiring more precise calibration.

### Stochastic Resonance and Background Stimulation

Research on noise and ADHD performance:

- White/pink noise **improves** cognitive performance in ADHD participants while
  **impairing** neurotypical participants (Soderlund et al., 2007).
- The moderate brain arousal (MBA) model: environmental noise introduces internal
  neural noise that boosts signal detection in dopamine-depleted systems.
- Recent research questions whether stochastic resonance specifically is the
  mechanism (pure tones also help), but the practical finding holds: **ambient
  stimulation helps ADHD focus**.

**Critical insight for Hapax Corpora**: The visual display IS the stochastic
resonance. Continuous, varied, moderate visual stimulation serves the same
function as background noise -- it raises baseline arousal toward the optimal
zone. This is not distraction; it is *functional background stimulation*.

The display should therefore:
- **Never be empty or static** (confirms the operator's instinct)
- Maintain **moderate visual complexity** at all times
- Use **continuous evolution** (shader drift, color evolution) as the base layer
- Layer discrete content on top of this continuous base

### Autism: Pattern Recognition and Predictability

Research on autistic visual processing:

- **Enhanced pattern recognition**: Autistic people detect fine-grained visual
  patterns that neurotypicals miss. The display can be more visually complex
  than typical ambient displays because the operator will extract meaning from
  subtle patterns.
- **Preference for predictability with variation**: Not rigid sameness, but
  *structured variation*. The display should have recognizable patterns that
  evolve rather than random chaos.
- **Increased pattern separation** (hippocampal): The operator will notice and
  distinguish between similar-but-different visual states. Content that is
  too similar will feel repetitive faster.
- **Sensory regulation through visual engagement**: Repetitive visual patterns
  can serve a regulatory function -- comfort through structured stimulation.

### AuDHD Dual Profile

The combination creates specific requirements:

- **Need for stimulation** (ADHD) + **need for structure** (autism) = the display
  should be **reliably active but patterned, not random**.
- **Novelty-seeking** (ADHD) + **predictability preference** (autism) = content
  should rotate on a **recognizable schedule** with **surprise within structure**.
  Like a jazz standard: the form is known, the improvisation is novel.
- **Sensory seeking AND sensitivity** can coexist: high tolerance for structured
  visual complexity, low tolerance for chaotic or jarring transitions.

### Design Implications

1. **Base visual layer always active** -- shaders, color evolution, particle systems
2. **Transitions are smooth, never jarring** -- fade in/out, not pop in/pop out
3. **Content rotation has rhythm** -- not metronome-regular, but recognizably
   patterned (every 30-90 seconds, something changes)
4. **Visual complexity is moderate-high** -- more than typical calm tech
   recommendations, calibrated for ADHD stimulation needs
5. **Structure is visible** -- signal zones in consistent positions, consistent
   visual language per content type

---

## 6. Practical Architecture: The Utility Sampler

### Requirements

- Runs every 10-15 seconds (the "tick")
- Evaluates 10 content source categories
- Produces a decision: what to inject, at what notification level, for how long
- Minimal compute (no ML inference, no network calls during scoring)
- Adapts to operator activity, time of day, and biometric state

### Proposed Architecture: Weighted Softmax Sampler

```
                        Context Vector
                    (activity, time, biometrics)
                              |
                              v
    +--------------------------------------------------+
    |           Per-Source Utility Scoring               |
    |                                                    |
    |  For each source s in [1..10]:                     |
    |    base_score(s)      -- configured weight          |
    |    * relevance(s, ctx) -- activity/context mult     |
    |    * freshness(s)      -- recency decay             |
    |    * urgency(s)        -- any pending alerts?       |
    |    * novelty(s)        -- content pool diversity    |
    |    = utility(s)                                    |
    +--------------------------------------------------+
                              |
                              v
    +--------------------------------------------------+
    |           Softmax Temperature Selection            |
    |                                                    |
    |  P(s) = exp(utility(s) / tau)                     |
    |         / sum(exp(utility(j) / tau) for all j)    |
    |                                                    |
    |  tau = temperature (activity-dependent):           |
    |    deep_focus: 0.5 (more greedy, fewer surprises)  |
    |    idle:       2.0 (more uniform, more variety)    |
    |    default:    1.0                                  |
    +--------------------------------------------------+
                              |
                              v
    +--------------------------------------------------+
    |           Sample & Dispatch                        |
    |                                                    |
    |  selected = weighted_random(sources, P)            |
    |  notification_level = classify(utility(selected))  |
    |  dwell_time = dwell_table[selected.type]           |
    |  dispatch(selected, notification_level, dwell)     |
    +--------------------------------------------------+
```

### Component Details

**Context Vector** (gathered once per tick):
- `activity`: Current operator activity label (from source #7)
- `time_of_day`: Hour, mapped to energy curve (morning=ramp, afternoon=dip, evening=wind-down)
- `biometric_state`: Latest HR/stress classification (calm/elevated/high)
- `voice_active`: Boolean, voice session in progress
- `last_injection_time`: Per-source timestamps

**Utility Scoring** (pure arithmetic, no ML):

```python
def utility(source, ctx):
    score = source.base_weight                    # configured: 0.1 to 1.0
    score *= relevance_matrix[source.type][ctx.activity]  # 0.0 to 1.5
    score *= freshness(source, ctx.now)           # exponential decay from last show
    score *= urgency_boost(source)                # 1.0 normally, 3.0+ for pending alerts
    score *= novelty(source)                      # content diversity within source pool
    return score
```

**Freshness function**:
```python
def freshness(source, now):
    elapsed = now - source.last_shown
    half_life = source.half_life_seconds  # e.g., 120s for profile facts
    return 1.0 - exp(-0.693 * elapsed / half_life)
    # Returns 0.0 immediately after shown, 0.5 at half-life, ~1.0 after 3x half-life
```

**Notification level classification**:
```python
def classify(utility_score):
    if utility_score > 5.0:   return INTERRUPT       # health alert, governance violation
    if utility_score > 2.0:   return MAKE_AWARE      # nudge, new calendar event
    if utility_score > 0.5:   return CHANGE_BLIND     # profile fact, camera feed
    return IGNORE                                     # suppress this tick
```

**Urgency pipeline** (separate from utility sampling):
True urgent items (health alerts, governance violations) bypass the sampler entirely
and inject immediately at interrupt level. The sampler handles ambient/background
content. This is the ICU "graduated delay" pattern: critical items are never
delayed by the sampling cycle.

### State Machine for Display Density

The display should maintain a target content density that varies by context:

```
State: AMBIENT (default)
  - Target: 2-4 visible content elements + continuous shader base
  - Tick interval: 15 seconds
  - New injection probability: ~60% per tick

State: FOCUSED (deep work detected)
  - Target: 0-2 visible content elements + continuous shader base
  - Tick interval: 30 seconds (slower rotation)
  - New injection probability: ~30% per tick
  - All injections at change-blind level maximum

State: RECEPTIVE (idle, browsing, break)
  - Target: 3-6 visible content elements + continuous shader base
  - Tick interval: 10 seconds (faster rotation)
  - New injection probability: ~80% per tick
  - Full notification level range available

State: PRESENTING (meeting/call)
  - Target: 0-1 visible content elements + continuous shader base
  - Tick interval: 60 seconds
  - New injection probability: ~10% per tick
  - Only change-blind transitions
```

### What NOT to Build

- **No full RL system**: Reinforcement learning requires thousands of episodes to
  converge. A single operator generates maybe 100 ticks per day. The utility
  scoring approach works immediately with hand-tuned weights.
- **No preference learning from gaze**: Would require eye tracking hardware and
  complex calibration. Save for later.
- **No LLM calls in the scoring loop**: The 15-second tick must be pure
  arithmetic. LLM calls happen elsewhere (generating content, classifying
  activity) and their outputs feed into the context vector.
- **No complex state tracking**: The sampler is essentially stateless except for
  `last_shown` timestamps and the current display state. No episode memory,
  no user modeling, no session tracking.

### Tuning Strategy

Start with hand-tuned weights and observe:

1. Set base weights equal (1.0 for all sources)
2. Set relevance matrix from the activity table in section 4
3. Set half-lives from the dwell time table in section 3
4. Run for a week with logging
5. Adjust based on: which sources are never selected (boost), which dominate
   (reduce), which feel intrusive (lower relevance in certain activities)

The operator can also provide explicit nudges: "show more camera", "fewer profile
facts" -- these adjust base weights directly.

---

## Key Takeaways

1. **Use SEEV-inspired utility scoring**: Salience, effort, expectancy, value --
   adapted as base weight, relevance, freshness, urgency.

2. **Softmax temperature selection**: Not greedy (boring), not uniform (chaotic).
   Temperature varies by activity state.

3. **Five notification levels** (Matthews): Most content is change-blind or
   make-aware. Interrupt is rare and earned.

4. **Never empty**: The ADHD optimal stimulation model confirms the operator's
   instinct. Visual emptiness = understimulation = discomfort. The shader base
   layer is always active.

5. **Respect focus**: During deep work, reduce injection rate, cap notification
   level, slow rotation. Same-context content only.

6. **Exponential freshness decay**: Prevents repetition naturally. Half-life
   per content type. Profile facts ~2min, alerts ~30s, camera ~5min.

7. **Structure with surprise**: The AuDHD profile wants recognizable patterns
   with novel content within them. Regular rhythm, varied payload.

8. **Graduated urgency**: Critical items bypass the sampler. Everything else
   goes through utility scoring. No alert fatigue.

9. **Hand-tuned, not learned**: Start with expert weights, adjust from
   observation. ML comes later (if ever) when there's enough interaction data.

10. **The display is functional stimulation**: It's not decoration or
    distraction. For an ADHD brain, ambient visual complexity serves the same
    role as background music -- it raises baseline arousal toward the productive
    zone.

---

## Sources

### Attention Management & Ambient Displays
- [Matthews et al. - A Toolkit for Managing User Attention in Peripheral Displays](http://www.madpickle.net/scott/pubs/p321-matthews.pdf)
- [Weiser & Brown - Designing Calm Technology](https://people.csail.mit.edu/rudolph/Teaching/weiser.pdf)
- [Case - Principles of Calm Technology](https://www.caseorganic.com/post/principles-of-calm-technology)
- [Wickens et al. - SEEV Model of Visual Attention Allocation](https://corescholar.libraries.wright.edu/cgi/viewcontent.cgi?article=1108&context=isap_2007)
- [Wickens - Noticing Events in the Visual Workplace: SEEV and NSEEV Models](https://www.researchgate.net/publication/303107878_Noticing_events_in_the_visual_workplace_The_SEEV_and_NSEEV_models)
- [Understanding and Applying the SEEV Model in Design](https://www.linkedin.com/pulse/understanding-applying-seev-model-design-insight-visual-pumpurs)
- [From Awareness to Action: Ambient Display for Self-regulated Usage](https://dl.acm.org/doi/10.1145/3749507)

### Alert Fatigue & Clinical/ATC Systems
- [Patient Monitoring Alarms in the ICU](https://ccforum.biomedcentral.com/articles/10.1186/cc12525)
- [Alarms in the ICU: Reducing False Alarms](https://pmc.ncbi.nlm.nih.gov/articles/PMC137277/)
- [ATC Alarms, Alerts, and Warnings](https://rosap.ntl.bts.gov/view/dot/65620/dot_65620_DS1.pdf)
- [Optimizing Multimodal Alarms to Mitigate Inattentional Blindness in ATC](https://www.sciencedirect.com/science/article/abs/pii/S0003687025000535)
- [Novel Continuous Real-Time Vital Signs Viewer for ICU](https://pmc.ncbi.nlm.nih.gov/articles/PMC10799282/)
- [Mark - The Cost of Interrupted Work: More Speed and Stress](https://ics.uci.edu/~gmark/chi08-mark.pdf)

### Content Scheduling & Bandits
- [Li et al. - Contextual-Bandit Approach to Personalized News Article Recommendation](https://www.researchgate.net/publication/45903533_A_Contextual-Bandit_Approach_to_Personalized_News_Article_Recommendation)
- [Eugene Yan - Bandits for Recommender Systems](https://eugeneyan.com/writing/bandits/)
- [VK Team - Contextual Multi-Armed Bandits for Content Recommendation](https://vkteam.medium.com/contextual-multi-armed-bandits-for-content-recommendation-or-not-by-bernoulli-alone-21d52be00f0)
- [Sutton & Barto - Softmax Action Selection](http://incompleteideas.net/book/ebook/node17.html)
- [Determining Optimal Temperature for Softmax in RL](https://www.sciencedirect.com/science/article/abs/pii/S1568494618302758)
- [Zarf - Randomness with Temperature](https://blog.zarfhome.com/2020/02/randomness-with-temperature)

### Habituation & Temporal Interest
- [Visual Exploration in Adults: Habituation, Mere Exposure, or Optimal Arousal?](https://link.springer.com/article/10.3758/s13420-021-00484-3)
- [Neural Habituation Enhances Novelty Detection](https://pmc.ncbi.nlm.nih.gov/articles/PMC7447193/)
- [The Magical 2.5 Seconds Media Attention Benchmark](https://www.eye-square.com/en/wp-content/uploads/sites/4/2020/03/MediaAttentionBenchmark-EngFullBLUECOVERS.pdf)
- [Freshness Scoring with Half-Life Decay Functions](https://arxiv.org/html/2509.19376)

### Neurodivergent Attention
- [ADDitude - Brain Stimulation and ADHD Cravings](https://www.additudemag.com/brain-stimulation-and-adhd-cravings-dependency-and-regulation/)
- [ADDept - ADHD Optimal Stimulation: Finding the Sweet Spot](https://www.addept.org/living-with-adult-add-adhd/finding-adhd-sweet-spot-optimal-stimulation)
- [Zentall - Optimal Stimulation as Theoretical Basis of Hyperactivity](https://www.researchgate.net/publication/21975989_Optimal_stimulation_as_theoretical_basis_of_hyperactivity)
- [Soderlund - Noise is Beneficial for Cognitive Performance in ADHD](https://pubmed.ncbi.nlm.nih.gov/17683456/)
- [Stochastic Resonance Not Required for Pink Noise Benefits](https://www.sciencedirect.com/science/article/abs/pii/S0028393224001763)
- [White Noise Effects on Sub-, Normal, and Super-Attentive Children](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0112768)
- [Arousal Dysregulation and Executive Dysfunction in ADHD](https://www.frontiersin.org/journals/psychiatry/articles/10.3389/fpsyt.2023.1336040/full)
- [Visual Perception in Autism: Neuroimaging Review](https://pmc.ncbi.nlm.nih.gov/articles/PMC7350544/)
- [Pattern Unifies Autism](https://pmc.ncbi.nlm.nih.gov/articles/PMC7907419/)
- [Autism360 - Autism Pattern Recognition](https://www.autism360.com/autism-pattern-recognition/)
- [Trans-diagnostic Investigation of Hyperfocus and Monotropism](https://journals.sagepub.com/doi/10.1177/27546330241237883)
- [AuDHD Identity: Living With Two Neurotypes](https://sensoryoverload.info/audhd/audhd-identity/)

### Information Foraging & Content Relevance
- [Pirolli & Card - Information Foraging](https://dl.acm.org/doi/fullHtml/10.1145/223904.223911)
- [Inverse Foraging: Inferring User Interest in Pervasive Displays](https://www.researchgate.net/publication/354593090_Inverse_Foraging_Inferring_Users'_Interest_in_Pervasive_Displays)
- [NNGroup - Information Foraging Theory](https://www.nngroup.com/articles/information-foraging/)

### Architecture & Scheduling
- [Asynchronous Tool Usage for Real-Time Agents (event-driven FSM)](https://arxiv.org/html/2410.21620v1)
- [MetaAgent: Multi-Agent Systems Based on FSMs](https://arxiv.org/html/2507.22606v1)
- [Confluent - Real-Time Decisioning and Autonomous Data Systems](https://www.confluent.io/blog/real-time-decisioning-autonomous-data-systems/)

### VJ Software & Generative Art
- [VJ Software Guide 2026](https://vjgalaxy.com/blogs/resources-digital-assets/vj-software-guide-2026-from-vjing-to-generative-art)
- [AI-VJ: Automated Visual Performance](https://ai-vj.com/)
- [Resolume VJ Software](https://www.resolume.com/)
