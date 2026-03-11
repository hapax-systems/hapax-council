/**
 * Knowledge model — bundled version of hapaxromana/knowledge/management-sufficiency.yaml.
 *
 * This is the single source of interview questions and requirement metadata
 * for the plugin. When the YAML model changes, this file must be updated.
 */

export interface Requirement {
  id: string;
  category: "foundational" | "structural" | "enrichment";
  description: string;
  source: string;
  check: {
    type: "file_exists" | "min_count" | "field_populated" | "field_coverage" | "any_content" | "derived";
    path?: string;
    filter?: Record<string, string>;
    field?: string;
    min?: number;
    threshold?: number;
  };
  acquisition: {
    method: "interview" | "nudge" | "external";
    question: string | null;
    outputType: "person_note" | "reference_doc" | "frontmatter_update" | null;
    personScoped: boolean;
  };
  priority: number;
  dependsOn: string[];
}

export const REQUIREMENTS: Requirement[] = [
  // ── Foundational ──────────────────────────────────────────
  {
    id: "direct-reports",
    category: "foundational",
    description: "Person notes for all direct reports with type, role, team, status.",
    source: "All 3 books",
    check: { type: "min_count", path: "10-work/people", filter: { type: "person", status: "active" }, min: 1 },
    acquisition: {
      method: "interview",
      question: "Let's set up your team. Who are your direct reports? For each person, I need their name, role, and which team they're on.",
      outputType: "person_note",
      personScoped: false,
    },
    priority: 100,
    dependsOn: [],
  },
  {
    id: "team-assignment",
    category: "foundational",
    description: "Every active person note has a team field populated.",
    source: "TT",
    check: { type: "field_populated", path: "10-work/people", filter: { type: "person", status: "active" }, field: "team" },
    acquisition: {
      method: "interview",
      question: "What team is {name} on?",
      outputType: "frontmatter_update",
      personScoped: true,
    },
    priority: 95,
    dependsOn: ["direct-reports"],
  },
  {
    id: "1on1-cadence",
    category: "foundational",
    description: "Every active person note has cadence set.",
    source: "SP, EP",
    check: { type: "field_populated", path: "10-work/people", filter: { type: "person", status: "active" }, field: "cadence" },
    acquisition: {
      method: "interview",
      question: "How often do you meet with {name} for 1:1s? (weekly, biweekly, monthly)",
      outputType: "frontmatter_update",
      personScoped: true,
    },
    priority: 95,
    dependsOn: ["direct-reports"],
  },
  {
    id: "manager-context",
    category: "foundational",
    description: "Operator's manager is documented as a person note.",
    source: "SP",
    check: { type: "min_count", path: "10-work/people", filter: { type: "person", role: "manager" }, min: 1 },
    acquisition: {
      method: "interview",
      question: "Who is your manager? What's their role/title?",
      outputType: "person_note",
      personScoped: false,
    },
    priority: 90,
    dependsOn: [],
  },
  {
    id: "company-mission",
    category: "foundational",
    description: "Company mission documented.",
    source: "SP",
    check: { type: "file_exists", path: "10-work/references/company-mission.md" },
    acquisition: {
      method: "interview",
      question: "What's your company's mission or purpose statement? Even a rough version helps.",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 90,
    dependsOn: [],
  },

  // ── Structural ────────────────────────────────────────────
  {
    id: "operating-principles",
    category: "structural",
    description: "Company or team values/operating principles documented.",
    source: "SP",
    check: { type: "file_exists", path: "10-work/references/operating-principles.md" },
    acquisition: {
      method: "interview",
      question: "Does your company or team have documented values or operating principles? What are they?",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 60,
    dependsOn: [],
  },
  {
    id: "org-structure",
    category: "structural",
    description: "Org hierarchy documented — reporting lines, spans of control.",
    source: "EP",
    check: { type: "file_exists", path: "10-work/references/org-chart.md" },
    acquisition: {
      method: "interview",
      question: "Let's map your org structure. Who reports to you? Who do you report to? Are there peer managers? What's the broader reporting chain?",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 60,
    dependsOn: ["direct-reports", "manager-context"],
  },
  {
    id: "team-topology-type",
    category: "structural",
    description: "Team type set for each team.",
    source: "TT",
    check: { type: "field_coverage", path: "10-work/people", filter: { type: "person", status: "active" }, field: "team-type", threshold: 80 },
    acquisition: {
      method: "interview",
      question: "What type of team is {team}? Options: stream-aligned (delivers end-to-end value), enabling (helps others adopt capabilities), complicated-subsystem (specialist domain), platform (internal services).",
      outputType: "frontmatter_update",
      personScoped: false,
    },
    priority: 60,
    dependsOn: ["direct-reports", "team-assignment"],
  },
  {
    id: "team-interaction-modes",
    category: "structural",
    description: "Interaction modes between team pairs documented.",
    source: "TT",
    check: { type: "file_exists", path: "10-work/references/team-interactions.md" },
    acquisition: {
      method: "interview",
      question: "How do your teams interact with each other? For each pair of teams that work together, what's the interaction mode? (collaboration, X-as-a-Service, facilitating)",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 60,
    dependsOn: ["team-topology-type"],
  },
  {
    id: "operating-cadence",
    category: "structural",
    description: "Meeting cadences documented.",
    source: "SP",
    check: { type: "file_exists", path: "10-work/references/operating-cadence.md" },
    acquisition: {
      method: "interview",
      question: "What recurring meetings do you have? For each, what's the purpose, frequency, and attendees?",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 60,
    dependsOn: [],
  },
  {
    id: "key-stakeholders",
    category: "structural",
    description: "Person notes for non-report stakeholders.",
    source: "SP",
    check: { type: "min_count", path: "10-work/people", filter: { type: "person", role: "stakeholder" }, min: 1 },
    acquisition: {
      method: "interview",
      question: "Who are key stakeholders outside your direct reports? Think: skip-levels, cross-functional partners, executives you interact with regularly.",
      outputType: "person_note",
      personScoped: false,
    },
    priority: 60,
    dependsOn: [],
  },
  {
    id: "decision-approach",
    category: "structural",
    description: "Decision framework documented.",
    source: "SP",
    check: { type: "file_exists", path: "10-work/references/decision-framework.md" },
    acquisition: {
      method: "interview",
      question: "How are decisions typically made on your team? Is there a framework (RAPID, DACI, consensus)? Who has decision rights for different domains?",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 60,
    dependsOn: [],
  },
  {
    id: "team-charters",
    category: "structural",
    description: "Per-team mission and scope documented.",
    source: "SP",
    check: { type: "file_exists", path: "10-work/references/team-charters.md" },
    acquisition: {
      method: "interview",
      question: "For each team you manage, what's their mission and scope? What are they responsible for? What's explicitly outside their scope?",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 60,
    dependsOn: ["team-assignment"],
  },

  // ── Enrichment ────────────────────────────────────────────
  {
    id: "career-goals",
    category: "enrichment",
    description: "Person notes have 3-year career goal documented.",
    source: "SP, EP",
    check: { type: "field_coverage", path: "10-work/people", filter: { type: "person", status: "active" }, field: "career-goal-3y", threshold: 50 },
    acquisition: {
      method: "interview",
      question: "What's {name}'s career goal for the next 3 years, as you understand it?",
      outputType: "frontmatter_update",
      personScoped: true,
    },
    priority: 35,
    dependsOn: ["direct-reports"],
  },
  {
    id: "skill-will",
    category: "enrichment",
    description: "Person notes have skill-level and will-signal populated.",
    source: "SP",
    check: { type: "field_coverage", path: "10-work/people", filter: { type: "person", status: "active" }, field: "skill-level", threshold: 50 },
    acquisition: {
      method: "interview",
      question: "For {name}, how would you assess their skill level (developing, career, advanced, expert) and will/motivation signal (high, moderate, low)?",
      outputType: "frontmatter_update",
      personScoped: true,
    },
    priority: 35,
    dependsOn: ["direct-reports"],
  },
  {
    id: "cognitive-load",
    category: "enrichment",
    description: "Person notes have numeric cognitive-load (1-5).",
    source: "TT, EP",
    check: { type: "field_coverage", path: "10-work/people", filter: { type: "person", status: "active" }, field: "cognitive-load", threshold: 80 },
    acquisition: {
      method: "interview",
      question: "For {name}, how would you rate their cognitive load right now on a 1-5 scale? 1 = very light, 3 = balanced, 5 = overwhelmed",
      outputType: "frontmatter_update",
      personScoped: true,
    },
    priority: 35,
    dependsOn: ["direct-reports"],
  },
  {
    id: "working-with-me",
    category: "enrichment",
    description: "Operator management style document.",
    source: "SP",
    check: { type: "file_exists", path: "10-work/references/working-with-me.md" },
    acquisition: {
      method: "interview",
      question: "Let's create your \"working with me\" doc. How do you prefer to communicate, receive feedback, and make decisions? What should people know about your working style?",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 35,
    dependsOn: [],
  },
  {
    id: "feedback-style",
    category: "enrichment",
    description: "Per-person feedback preferences documented.",
    source: "SP",
    check: { type: "field_coverage", path: "10-work/people", filter: { type: "person", status: "active" }, field: "feedback-style", threshold: 50 },
    acquisition: {
      method: "interview",
      question: "How does {name} prefer to receive feedback? (direct, written, in-person, with examples, etc.)",
      outputType: "frontmatter_update",
      personScoped: true,
    },
    priority: 35,
    dependsOn: ["direct-reports"],
  },
  {
    id: "growth-vectors",
    category: "enrichment",
    description: "Per-person development areas documented.",
    source: "EP",
    check: { type: "field_coverage", path: "10-work/people", filter: { type: "person", status: "active" }, field: "growth-vector", threshold: 50 },
    acquisition: {
      method: "interview",
      question: "What's {name}'s primary growth vector right now? What skill or area are they actively developing?",
      outputType: "frontmatter_update",
      personScoped: true,
    },
    priority: 35,
    dependsOn: ["direct-reports"],
  },
  {
    id: "performance-framework",
    category: "enrichment",
    description: "Career ladder and performance designations documented.",
    source: "SP, EP",
    check: { type: "file_exists", path: "10-work/references/career-ladder.md" },
    acquisition: {
      method: "interview",
      question: "Does your company have a career ladder or performance framework? What are the levels? What's the promotion process?",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 35,
    dependsOn: [],
  },
  {
    id: "dora-metrics",
    category: "enrichment",
    description: "DORA metrics tracked.",
    source: "EP",
    check: { type: "file_exists", path: "10-work/references/dora-metrics.md" },
    acquisition: {
      method: "interview",
      question: "Do you track DORA metrics? Where? What are current values for your team(s)?",
      outputType: "reference_doc",
      personScoped: false,
    },
    priority: 35,
    dependsOn: [],
  },
];

export function getInterviewableRequirements(): Requirement[] {
  return REQUIREMENTS.filter((r) => r.acquisition.method === "interview");
}
