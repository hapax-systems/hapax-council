export interface SlashCommand {
  name: string;
  description: string;
  template: string;
  /** If true, only available in work vault (has 10-work/). */
  workOnly?: boolean;
}

const COMMANDS: SlashCommand[] = [
  {
    name: "/prep",
    description: "Prepare for the next 1:1 with this person",
    template:
      "Review this person note and prepare talking points for our next 1:1. Surface open loops, recent wins, coaching experiment status, and questions to ask. Do not draft feedback language.",
    workOnly: true,
  },
  {
    name: "/review-week",
    description: "Review this person's week",
    template:
      "Summarize this person's week based on available data — meetings attended, tasks completed, any signals of cognitive load change. Observable data only.",
    workOnly: true,
  },
  {
    name: "/growth",
    description: "Assess growth trajectory",
    template:
      "Review this person's growth vectors, career goal, current gaps, and coaching hypotheses. Identify what's progressing and what needs attention. Do not suggest feedback language.",
    workOnly: true,
  },
  {
    name: "/team-risks",
    description: "Surface team-level risks",
    template:
      "Analyze the active note for risk signals: stale 1:1s, high cognitive load, overdue coaching, topology mismatches. Prioritize by urgency.",
    workOnly: true,
  },
  {
    name: "/setup",
    description: "Start or resume management data setup interview",
    template: "__SETUP_START__",
    workOnly: true,
  },
  {
    name: "/setup skip",
    description: "Skip the current setup question",
    template: "__SETUP_SKIP__",
    workOnly: true,
  },
  {
    name: "/setup status",
    description: "Show setup progress",
    template: "__SETUP_STATUS__",
    workOnly: true,
  },
];

export function matchCommands(input: string, isWorkVault = true): SlashCommand[] {
  const trimmed = input.trim().toLowerCase();
  if (!trimmed.startsWith("/")) return [];
  return COMMANDS.filter(
    (cmd) =>
      (isWorkVault || !cmd.workOnly) &&
      (cmd.name.startsWith(trimmed) || cmd.name === trimmed)
  );
}

export function getCommands(isWorkVault = true): SlashCommand[] {
  return isWorkVault ? COMMANDS : COMMANDS.filter((cmd) => !cmd.workOnly);
}
