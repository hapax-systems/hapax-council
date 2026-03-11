/**
 * Question templates for the knowledge sufficiency interview.
 *
 * Maps requirement IDs to conversational questions with follow-up prompts
 * and extraction instructions.
 */
import type { Requirement } from "./knowledge-model";
import { REQUIREMENTS } from "./knowledge-model";

export interface QuestionContext {
  requirement: Requirement;
  question: string;          // Resolved question text (with {name}/{team} substituted)
  followUp: string;          // Follow-up prompt if answer is incomplete
  extractionPrompt: string;  // Prompt sent to LLM for structured extraction
}

/**
 * Build a question context for a requirement.
 * For person-scoped questions, pass the person name to substitute {name}.
 * For team-scoped questions, pass the team name to substitute {team}.
 */
export function buildQuestion(
  req: Requirement,
  context?: { name?: string; team?: string }
): QuestionContext {
  let question = req.acquisition.question || req.description;
  if (context?.name) {
    question = question.replace(/\{name\}/g, context.name);
  }
  if (context?.team) {
    question = question.replace(/\{team\}/g, context.team);
  }

  const followUp = getFollowUp(req.id);
  const extractionPrompt = buildExtractionPrompt(req, question);

  return { requirement: req, question, followUp, extractionPrompt };
}

function getFollowUp(requirementId: string): string {
  const followUps: Record<string, string> = {
    "direct-reports": "Can you list any more? I want to make sure I have everyone.",
    "team-assignment": "Got it. Are there any people on multiple teams or in transition?",
    "1on1-cadence": "And do you have a preferred day/time for this 1:1?",
    "manager-context": "How often do you meet with your manager?",
    "company-mission": "Is there a more formal version, or is this the working statement?",
    "operating-principles": "Are there any unwritten norms that matter as much as the formal values?",
    "org-structure": "Are there any dotted-line relationships I should know about?",
    "key-stakeholders": "Anyone else who significantly impacts your team's work?",
  };
  return followUps[requirementId] || "Anything else to add on this topic?";
}

function buildExtractionPrompt(req: Requirement, question: string): string {
  if (req.acquisition.outputType === "person_note") {
    return `Extract structured data from the user's answer. The user was asked:
"${question}"

Return valid JSON matching this EXACT schema:
{
  "people": [
    { "name": "Full Name", "role": "their role/title", "team": "team name" }
  ],
  "incomplete": false
}

Rules:
- The top-level key MUST be "people" containing an array
- Each person MUST have a "name" field
- "role" and "team" are optional — only include if explicitly stated
- Set "incomplete" to true if the user indicated there are more people
- Only extract what was explicitly stated`;
  }

  if (req.acquisition.outputType === "frontmatter_update") {
    return `Extract structured data from the user's answer. The user was asked:
"${question}"

Return valid JSON with the field values to update. Include "person": "Full Name" if the update is about a specific person.
If the answer is incomplete, include "incomplete": true in your response.
Only extract what was explicitly stated. Do not infer, guess, or add information.`;
  }

  return `Extract structured data from the user's answer. The user was asked:
"${question}"

Return valid JSON. Only extract what was explicitly stated. Do not infer, guess, or add information.
If the answer is incomplete, include "incomplete": true in your response.

The extracted data will be used to create a reference document with the extracted content.`;
}

/**
 * Get the next question to ask based on unsatisfied requirements.
 * Respects dependency ordering — won't ask about team-assignment
 * if direct-reports hasn't been satisfied yet.
 */
export function getNextQuestion(
  satisfiedIds: Set<string>,
  skippedIds: Set<string>,
  context?: { name?: string; team?: string }
): QuestionContext | null {
  const interviewable = REQUIREMENTS.filter(
    (r) => r.acquisition.method === "interview"
  );

  // Sort by priority descending
  const sorted = [...interviewable].sort((a, b) => b.priority - a.priority);

  for (const req of sorted) {
    // Skip already satisfied or skipped
    if (satisfiedIds.has(req.id) || skippedIds.has(req.id)) continue;

    // Check dependencies are satisfied
    const depsReady = req.dependsOn.every((dep) => satisfiedIds.has(dep));
    if (!depsReady) continue;

    return buildQuestion(req, context);
  }

  return null;
}
