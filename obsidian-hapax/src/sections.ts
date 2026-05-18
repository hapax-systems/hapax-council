import type {
  SprintState,
  StimmungState,
  Nudge,
  Measure,
  Gate,
  ModelPosterior,
  NoteContext,
} from "./types";
import type { HealthState } from "./logos-client";

// ─── helpers ─────────────────────────────────────────────────────────────────

function badge(status: string): string {
  return `<span class="hapax-badge hapax-badge-${status.replace(/[^a-z0-9]/g, "-")}">${esc(status)}</span>`;
}

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function attr(s: string): string {
  return esc(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function pct(n: number): string {
  return (n * 100).toFixed(1) + "%";
}

function section(title: string, body: string, open = true): string {
  return `<details class="hapax-section" ${open ? "open" : ""}>
  <summary class="hapax-section-header">${esc(title)}</summary>
  <div class="hapax-section-body">${body}</div>
</details>`;
}

function actionBtn(label: string, action: string, cls = ""): string {
  return `<button class="hapax-action ${attr(cls)}" data-action="${attr(action)}">${esc(label)}</button>`;
}

// ─── Sprint ───────────────────────────────────────────────────────────────────

export function renderSprintStatus(sprint: SprintState): string {
  const blocking = sprint.blocking_gate
    ? ` <span class="hapax-badge hapax-badge-blocked">gate ${esc(sprint.blocking_gate)}</span>`
    : "";
  const body = `<p>Sprint ${sprint.current_sprint} Day ${sprint.current_day} —
    ${sprint.measures_completed}/${sprint.measures_total} completed,
    ${sprint.measures_in_progress} in-progress,
    ${sprint.measures_blocked} blocked${blocking}
  </p>`;
  return section("Sprint Status", body);
}

// ─── Stimmung ─────────────────────────────────────────────────────────────────

export function renderStimmungBadge(stimmung: StimmungState): string {
  const stance = stimmung.overall_stance;
  const body = `<span class="hapax-stimmung-dot hapax-stance-${attr(stance)}"></span>
  <span class="hapax-stance-label">${esc(stance)}</span>`;
  return section("Stimmung", body);
}

export function renderStimmungDetail(stimmung: StimmungState): string {
  const nonNominal = Object.entries(stimmung.dimensions).filter(
    ([, d]) => d.trend !== "stable" || d.value < 0.8,
  );
  if (nonNominal.length === 0) {
    return section("Stimmung Detail", "<p>All dimensions nominal.</p>", false);
  }
  const rows = nonNominal
    .map(
      ([dim, d]) =>
        `<tr><td>${esc(dim)}</td><td class="hapax-mono">${d.value.toFixed(2)}</td><td>${esc(d.trend)}</td></tr>`,
    )
    .join("");
  const body = `<table class="hapax-table"><thead><tr><th>Dimension</th><th>Value</th><th>Trend</th></tr></thead><tbody>${rows}</tbody></table>`;
  return section("Stimmung Detail", body);
}

// ─── Nudges ───────────────────────────────────────────────────────────────────

export function renderNudgeCount(nudges: Nudge[]): string {
  const count = nudges.length;
  const body =
    count === 0
      ? "<p>No active nudges.</p>"
      : `<p>${count} active nudge${count !== 1 ? "s" : ""}</p>`;
  return section("Nudges", body, false);
}

export function renderNudgeList(nudges: Nudge[]): string {
  if (nudges.length === 0) {
    return section("Nudges", "<p>No active nudges.</p>");
  }
  const items = nudges
    .sort((a, b) => b.priority_score - a.priority_score)
    .map(
      (n) =>
        `<div class="hapax-nudge-item">
      <div class="hapax-nudge-title">${esc(n.title)} ${badge(n.category)}</div>
      <div class="hapax-nudge-detail">${esc(n.detail)}</div>
      <div class="hapax-nudge-actions">
        ${actionBtn("Act", `nudge-act:${n.source_id}`, "hapax-action-primary")}
        ${actionBtn("Dismiss", `nudge-dismiss:${n.source_id}`)}
      </div>
    </div>`,
    )
    .join("");
  return section("Nudges", items);
}

// ─── Measure ─────────────────────────────────────────────────────────────────

export function renderMeasureDetail(measure: Measure): string {
  const wsjf =
    measure.effort_hours > 0
      ? (measure.posterior_gain / measure.effort_hours).toFixed(2)
      : "—";
  const actions = (() => {
    switch (measure.status) {
      case "pending":
        return actionBtn("Start", `measure-start:${measure.id}`, "hapax-action-primary");
      case "in-progress":
        return [
          actionBtn("Complete", `measure-complete:${measure.id}`, "hapax-action-primary"),
          actionBtn("Block", `measure-block:${measure.id}`),
          actionBtn("Skip", `measure-skip:${measure.id}`),
        ].join(" ");
      case "blocked":
        return actionBtn("Resume", `measure-resume:${measure.id}`);
      default:
        return "";
    }
  })();

  const body = `<table class="hapax-table">
    <tr><td>Status</td><td>${badge(measure.status)}</td></tr>
    <tr><td>Model</td><td>${esc(measure.model)}</td></tr>
    <tr><td>Day / Block</td><td class="hapax-mono">Day ${measure.day} / ${esc(measure.block)}</td></tr>
    <tr><td>Effort</td><td class="hapax-mono">${measure.effort_hours}h</td></tr>
    <tr><td>Posterior gain</td><td class="hapax-mono">+${measure.posterior_gain.toFixed(3)}</td></tr>
    <tr><td>WSJF</td><td class="hapax-mono">${wsjf}</td></tr>
    ${measure.gate ? `<tr><td>Gate</td><td class="hapax-mono">${esc(measure.gate)}</td></tr>` : ""}
    ${measure.completed_at ? `<tr><td>Completed</td><td>${esc(measure.completed_at)}</td></tr>` : ""}
  </table>
  ${measure.result_summary ? `<p class="hapax-result-summary">${esc(measure.result_summary)}</p>` : ""}
  <div class="hapax-actions">${actions}</div>`;
  return section(`${measure.id}: ${measure.title}`, body);
}

export function renderMeasureDeps(measure: Measure, allMeasures: Measure[]): string {
  if (measure.depends_on.length === 0 && measure.blocks.length === 0) {
    return "";
  }
  const lookup = new Map(allMeasures.map((m) => [m.id, m]));

  const depRows = measure.depends_on
    .map((id) => {
      const m = lookup.get(id);
      return `<tr><td class="hapax-mono">${esc(id)}</td><td>${m ? esc(m.title) : "—"}</td><td>${m ? badge(m.status) : "—"}</td></tr>`;
    })
    .join("");

  const blockRows = measure.blocks
    .map((id) => {
      const m = lookup.get(id);
      return `<tr><td class="hapax-mono">${esc(id)}</td><td>${m ? esc(m.title) : "—"}</td><td>${m ? badge(m.status) : "—"}</td></tr>`;
    })
    .join("");

  let body = "";
  if (depRows) {
    body += `<p><strong>Depends on:</strong></p><table class="hapax-table"><tbody>${depRows}</tbody></table>`;
  }
  if (blockRows) {
    body += `<p><strong>Blocks:</strong></p><table class="hapax-table"><tbody>${blockRows}</tbody></table>`;
  }

  return section("Dependencies", body, false);
}

// ─── Gate ─────────────────────────────────────────────────────────────────────

export function renderGateAssociation(gate: Gate): string {
  const body = `<table class="hapax-table">
    <tr><td>Gate</td><td class="hapax-mono">${esc(gate.id)}</td></tr>
    <tr><td>Status</td><td>${badge(gate.status)}</td></tr>
    <tr><td>Condition</td><td>${esc(gate.condition)}</td></tr>
    ${gate.result_value !== null ? `<tr><td>Result</td><td class="hapax-mono">${gate.result_value}</td></tr>` : ""}
  </table>`;
  return section("Gate Association", body, false);
}

export function renderGateDetail(gate: Gate, measures: Measure[]): string {
  const lookup = new Map(measures.map((m) => [m.id, m]));
  const downstreamRows = gate.downstream_measures
    .map((id) => {
      const m = lookup.get(id);
      return `<tr><td class="hapax-mono">${esc(id)}</td><td>${m ? esc(m.title) : "—"}</td><td>${m ? badge(m.status) : "—"}</td></tr>`;
    })
    .join("");

  const ackBtn =
    !gate.acknowledged && gate.status !== "pending"
      ? actionBtn("Acknowledge", `gate-acknowledge:${gate.id}`, "hapax-action-primary")
      : gate.acknowledged
        ? `<span class="hapax-badge hapax-badge-completed">acknowledged</span>`
        : "";

  const body = `<table class="hapax-table">
    <tr><td>Model</td><td>${esc(gate.model)}</td></tr>
    <tr><td>Status</td><td>${badge(gate.status)}</td></tr>
    <tr><td>Condition</td><td>${esc(gate.condition)}</td></tr>
    ${gate.result_value !== null ? `<tr><td>Result</td><td class="hapax-mono">${gate.result_value}</td></tr>` : ""}
    ${gate.trigger_measure ? `<tr><td>Trigger</td><td class="hapax-mono">${esc(gate.trigger_measure)}</td></tr>` : ""}
    ${gate.nudge_required ? `<tr><td>Nudge</td><td>required</td></tr>` : ""}
  </table>
  ${downstreamRows ? `<p><strong>Downstream measures:</strong></p><table class="hapax-table"><tbody>${downstreamRows}</tbody></table>` : ""}
  <div class="hapax-actions">${ackBtn}</div>`;
  return section(`${gate.id}: ${gate.title}`, body);
}

// ─── Model posterior ─────────────────────────────────────────────────────────

export function renderModelPosterior(model: string, posterior: ModelPosterior): string {
  const body = `<table class="hapax-table">
    <tr><td>Baseline</td><td class="hapax-mono">${pct(posterior.baseline)}</td></tr>
    <tr><td>Gained</td><td class="hapax-mono">+${pct(posterior.gained)}</td></tr>
    <tr><td>Current</td><td class="hapax-mono">${pct(posterior.current)}</td></tr>
    <tr><td>Possible</td><td class="hapax-mono">${pct(posterior.possible)}</td></tr>
    <tr><td>Completed</td><td class="hapax-mono">${posterior.completed}/${posterior.total}</td></tr>
  </table>`;
  return section(`Model: ${model}`, body, false);
}

export function renderPosteriorTable(models: Record<string, ModelPosterior>): string {
  const rows = Object.entries(models)
    .map(
      ([model, p]) =>
        `<tr>
      <td>${esc(model)}</td>
      <td class="hapax-mono">${pct(posterior_progress(p))}</td>
      <td class="hapax-mono">${pct(p.current)}</td>
      <td class="hapax-mono">+${pct(p.gained)}</td>
      <td class="hapax-mono">${p.completed}/${p.total}</td>
    </tr>`,
    )
    .join("");
  const body = `<table class="hapax-table">
    <thead><tr><th>Model</th><th>Progress</th><th>Current P</th><th>Gained</th><th>Done</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
  return section("Posterior Tracker", body);
}

function posterior_progress(p: ModelPosterior): number {
  if (p.total === 0) return 0;
  return p.completed / p.total;
}

// ─── Burndown ─────────────────────────────────────────────────────────────────

export function renderBurndown(sprint: SprintState): string {
  const pctDone =
    sprint.measures_total > 0
      ? (sprint.measures_completed / sprint.measures_total) * 100
      : 0;
  const effortPct =
    sprint.effort_total > 0
      ? (sprint.effort_completed / sprint.effort_total) * 100
      : 0;
  const body = `<div class="hapax-burndown-bar">
    <div class="hapax-burndown-fill" style="width:${pctDone.toFixed(1)}%"></div>
  </div>
  <p class="hapax-mono">${sprint.measures_completed}/${sprint.measures_total} measures (${pctDone.toFixed(0)}%) · ${sprint.effort_completed.toFixed(1)}/${sprint.effort_total.toFixed(1)}h (${effortPct.toFixed(0)}%)</p>
  <p>${sprint.measures_in_progress} in-progress · ${sprint.measures_blocked} blocked · ${sprint.measures_pending} pending · ${sprint.measures_skipped} skipped</p>`;
  return section("Burndown", body);
}

// ─── Health ───────────────────────────────────────────────────────────────────

export function renderHealthSnapshot(health: HealthState): string {
  const healthy = Array.isArray(health.healthy) ? health.healthy : [];
  const degraded = Array.isArray(health.degraded) ? health.degraded : [];
  const failed = Array.isArray(health.failed) ? health.failed : [];
  const body = `<p>${badge(health.status)}</p>
  <p>
    <span class="hapax-badge hapax-badge-completed">${healthy.length} healthy</span>
    ${degraded.length ? `<span class="hapax-badge hapax-badge-in-progress">${degraded.length} degraded</span>` : ""}
    ${failed.length ? `<span class="hapax-badge hapax-badge-blocked">${failed.length} failed</span>` : ""}
  </p>
  ${failed.length ? `<ul>${failed.map((f) => `<li class="hapax-mono">${esc(f)}</li>`).join("")}</ul>` : ""}
  ${degraded.length ? `<ul>${degraded.map((d) => `<li class="hapax-mono">${esc(d)}</li>`).join("")}</ul>` : ""}`;
  return section("Health", body, failed.length > 0 || degraded.length > 0);
}

// ─── Research context ─────────────────────────────────────────────────────────

export function renderResearchContext(
  noteContext: NoteContext,
  measures: Measure[],
  sprint: SprintState,
): string {
  const tags = noteContext.tags ?? [];
  const modelTag = noteContext.model;

  // Find measures whose model matches or whose tags overlap
  const related = measures.filter((m) => {
    if (modelTag && m.model === modelTag) return true;
    return tags.some((t) => m.model.toLowerCase().includes(t.toLowerCase()));
  });

  if (related.length === 0) {
    return section(
      "Research Context",
      `<p>No related measures found in Sprint ${sprint.current_sprint}.</p>`,
      false,
    );
  }

  const rows = related
    .map(
      (m) =>
        `<tr>
      <td class="hapax-mono">${esc(m.id)}</td>
      <td>${esc(m.title)}</td>
      <td>${badge(m.status)}</td>
    </tr>`,
    )
    .join("");

  const body = `<table class="hapax-table"><tbody>${rows}</tbody></table>`;
  return section("Research Context", body);
}
