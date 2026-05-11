"""agents/coordination_tui/app.py — Coordination dashboard Textual TUI."""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import var
from textual.widgets import DataTable, Footer, Header, Label, Static

from agents.coordination_tui.data import (
    DashboardState,
    dispatch_to_lane,
    load_all,
)

REFRESH_INTERVAL = 10.0

CI_ICONS = {
    "pass": "[green]PASS[/]",
    "fail": "[red]FAIL[/]",
    "pending": "[yellow]PEND[/]",
    "none": "[dim]---[/]",
    "unknown": "[dim]?[/]",
}
STATUS_COLORS = {"active": "green", "idle": "yellow", "shift": "cyan", "error": "red"}


def _format_idle(seconds: int) -> str:
    if seconds <= 0:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60}m"


class LaneTable(DataTable):
    pass


class TaskTable(DataTable):
    pass


class PRTable(DataTable):
    pass


class QuotaPanel(Static):
    def render_quota(self, state: DashboardState) -> None:
        if state.quota is None:
            self.update("[dim]Quota: unavailable[/]")
            return

        q = state.quota
        bar_len = 20
        filled = int(q.pressure * bar_len)
        empty = bar_len - filled

        if q.throttle_level == "emergency" or q.throttle_level == "pause":
            color = "red"
        elif q.throttle_level == "throttle":
            color = "yellow"
        else:
            color = "green"

        bar = f"[{color}]{'█' * filled}[/][dim]{'░' * empty}[/]"
        lines = [
            f"[bold]Quota[/]  {bar} {q.pressure:.0%}",
            f"Level:  [{color}]{q.throttle_level.upper()}[/]",
            f"24h:    ${q.window_24h_cost:.2f} / ${q.budget:.2f}",
        ]
        if not q.governance_healthy:
            lines.append("[bold red]⚠ GOVERNANCE UNHEALTHY[/]")
        self.update("\n".join(lines))


class TaskCountPanel(Static):
    def render_counts(self, counts: dict[str, int]) -> None:
        total = sum(counts.values())
        offered = counts.get("offered", 0)
        claimed = counts.get("claimed", 0)
        in_progress = counts.get("in_progress", 0)
        done = counts.get("done", 0)
        lines = [
            f"[bold]Tasks[/]  {total} total",
            f"Offered:     [green]{offered}[/]",
            f"Claimed:     [yellow]{claimed}[/]",
            f"In-progress: [cyan]{in_progress}[/]",
            f"Done:        [dim]{done}[/]",
        ]
        self.update("\n".join(lines))


class CoordinationApp(App):
    TITLE = "Hapax Coordination Dashboard"
    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1;
    }
    #lane-container {
        height: 100%;
        border: solid $accent;
    }
    #task-container {
        height: 100%;
        border: solid $accent;
    }
    #pr-container {
        height: 100%;
        border: solid $accent;
    }
    #status-container {
        height: 100%;
        border: solid $accent;
        layout: vertical;
    }
    #lane-container > Label,
    #task-container > Label,
    #pr-container > Label,
    #status-container > Label {
        text-style: bold;
        padding: 0 1;
        color: $text;
        background: $accent;
        width: 100%;
    }
    LaneTable, TaskTable, PRTable {
        height: 1fr;
    }
    QuotaPanel {
        height: auto;
        padding: 1;
    }
    TaskCountPanel {
        height: auto;
        padding: 1;
    }
    #refresh-label {
        dock: bottom;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("d", "dispatch", "Dispatch task → lane"),
        Binding("q", "quit", "Quit"),
    ]

    state: var[DashboardState] = var(DashboardState)

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="lane-container"):
            yield Label("Lane Health")
            yield LaneTable(id="lane-table")
        with Container(id="task-container"):
            yield Label("Task Queue (WSJF)")
            yield TaskTable(id="task-table")
        with Container(id="pr-container"):
            yield Label("PR Pipeline")
            yield PRTable(id="pr-table")
        with Container(id="status-container"):
            yield Label("System Status")
            yield QuotaPanel(id="quota-panel")
            yield TaskCountPanel(id="task-count-panel")
            yield Static("", id="refresh-label")
        yield Footer()

    def on_mount(self) -> None:
        lane_table = self.query_one("#lane-table", LaneTable)
        lane_table.add_columns("Lane", "Plat", "Status", "Idle", "Task", "PR")
        lane_table.cursor_type = "row"

        task_table = self.query_one("#task-table", TaskTable)
        task_table.add_columns("WSJF", "Task", "Status", "Effort", "Assigned", "Plat")
        task_table.cursor_type = "row"

        pr_table = self.query_one("#pr-table", PRTable)
        pr_table.add_columns("PR#", "Title", "Branch", "CI", "Author")
        pr_table.cursor_type = "row"

        self.do_refresh()
        self.set_interval(REFRESH_INTERVAL, self.do_refresh)

    @work(exclusive=True)
    async def do_refresh(self) -> None:
        new_state = await load_all()
        self.state = new_state
        self._render_tables(new_state)

    def _render_tables(self, s: DashboardState) -> None:
        lane_table = self.query_one("#lane-table", LaneTable)
        lane_table.clear()
        for lane in s.lanes:
            color = STATUS_COLORS.get(lane.status, "white")
            lane_table.add_row(
                lane.name,
                lane.platform,
                f"[{color}]{lane.status}[/]",
                _format_idle(lane.idle_seconds),
                lane.current_task or "-",
                lane.current_pr or "-",
                key=lane.name,
            )

        task_table = self.query_one("#task-table", TaskTable)
        task_table.clear()
        for task in s.tasks:
            status_color = {"offered": "green", "claimed": "yellow", "in_progress": "cyan"}.get(
                task.status, "white"
            )
            task_table.add_row(
                f"{task.wsjf:.1f}",
                task.title,
                f"[{status_color}]{task.status}[/]",
                task.effort_class,
                task.assigned_to if task.assigned_to != "unassigned" else "[dim]-[/]",
                ",".join(task.platform_suitability),
                key=task.task_id,
            )

        pr_table = self.query_one("#pr-table", PRTable)
        pr_table.clear()
        for pr in s.prs:
            pr_table.add_row(
                f"#{pr.number}",
                pr.title,
                pr.branch,
                CI_ICONS.get(pr.ci_status, pr.ci_status),
                pr.author,
                key=str(pr.number),
            )

        quota_panel = self.query_one("#quota-panel", QuotaPanel)
        quota_panel.render_quota(s)

        count_panel = self.query_one("#task-count-panel", TaskCountPanel)
        count_panel.render_counts(s.task_counts)

        refresh_label = self.query_one("#refresh-label", Static)
        if s.refreshed_at:
            refresh_label.update(f"Last refresh: {s.refreshed_at.strftime('%H:%M:%S')} UTC")

    def action_refresh(self) -> None:
        self.do_refresh()

    @work(exclusive=True)
    async def action_dispatch(self) -> None:
        lane_table = self.query_one("#lane-table", LaneTable)
        task_table = self.query_one("#task-table", TaskTable)

        lane_row_key = lane_table.cursor_row
        task_row_key = task_table.cursor_row

        if lane_row_key is None or task_row_key is None:
            self.notify("Select a lane and task first", severity="warning")
            return

        if lane_row_key >= len(self.state.lanes) or task_row_key >= len(self.state.tasks):
            self.notify("Invalid selection", severity="warning")
            return

        lane = self.state.lanes[lane_row_key]
        task = self.state.tasks[task_row_key]

        msg = (
            f"cc-claim {task.task_id} && implement it per the task description. "
            f"Read the task file first: cat ~/Documents/Personal/20-projects/"
            f"hapax-cc-tasks/active/{task.task_id}.md"
        )

        await dispatch_to_lane(lane, msg)
        self.notify(f"Dispatched {task.task_id} → {lane.name} ({lane.platform})")

    def action_quit(self) -> None:
        self.exit()
