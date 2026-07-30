from __future__ import annotations

import base64
import html
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "project_manager.db"
HERO_IMAGE_PATH = APP_DIR / "assets" / "project-hero.png"

STATUS_OPTIONS = ["Not started", "In progress", "Blocked", "Done"]
PRIORITY_OPTIONS = ["Low", "Medium", "High", "Critical"]

PRIORITY_CLASSES = {
    "Low": "note-low",
    "Medium": "note-medium",
    "High": "note-high",
    "Critical": "note-critical",
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_connection()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Not started',
                progress INTEGER NOT NULL DEFAULT 0,
                priority TEXT NOT NULL DEFAULT 'Medium',
                sort_order INTEGER NOT NULL DEFAULT 0,
                due_date TEXT,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                owner TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Not started',
                priority TEXT NOT NULL DEFAULT 'Medium',
                sort_order INTEGER NOT NULL DEFAULT 0,
                due_date TEXT,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """
        )
        project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
        if "progress" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN progress INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                UPDATE projects
                SET progress = CASE
                    WHEN status = 'Done' THEN 100
                    WHEN status = 'In progress' THEN 50
                    ELSE 0
                END
                """
            )
        if "sort_order" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE projects SET sort_order = id * 10")

        task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "sort_order" not in task_columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE tasks SET sort_order = id * 10")
        conn.commit()


def query_df(query: str, params: tuple = ()) -> pd.DataFrame:
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn, params=params)


def execute(query: str, params: tuple = ()) -> None:
    with closing(get_connection()) as conn:
        conn.execute(query, params)
        conn.commit()


def scalar(query: str, params: tuple = ()) -> object:
    with closing(get_connection()) as conn:
        row = conn.execute(query, params).fetchone()
        return row[0] if row else None


def next_project_sort_order() -> int:
    value = scalar("SELECT COALESCE(MAX(sort_order), 0) + 10 FROM projects")
    return int(value or 10)


def next_task_sort_order(project_id: int) -> int:
    value = scalar("SELECT COALESCE(MAX(sort_order), 0) + 10 FROM tasks WHERE project_id = ?", (project_id,))
    return int(value or 10)


def project_status_from_progress(progress: int) -> str:
    if progress >= 100:
        return "Done"
    if progress <= 0:
        return "Not started"
    return "In progress"


def add_project(name: str, owner: str, progress: int, priority: str, due_date: date | None, notes: str) -> None:
    status = project_status_from_progress(progress)
    execute(
        """
        INSERT INTO projects (name, owner, status, progress, priority, sort_order, due_date, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name.strip(),
            owner.strip(),
            status,
            progress,
            priority,
            next_project_sort_order(),
            due_date.isoformat() if due_date else None,
            notes.strip(),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def add_task(
    project_id: int,
    title: str,
    owner: str,
    status: str,
    priority: str,
    due_date: date | None,
    notes: str,
) -> None:
    execute(
        """
        INSERT INTO tasks (project_id, title, owner, status, priority, sort_order, due_date, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            title.strip(),
            owner.strip(),
            status,
            priority,
            next_task_sort_order(project_id),
            due_date.isoformat() if due_date else None,
            notes.strip(),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def update_project(project_id: int, progress: int, priority: str, due_date: date | None, notes: str) -> None:
    status = project_status_from_progress(progress)
    execute(
        """
        UPDATE projects
        SET status = ?, progress = ?, priority = ?, due_date = ?, notes = ?
        WHERE id = ?
        """,
        (status, progress, priority, due_date.isoformat() if due_date else None, notes.strip(), project_id),
    )


def update_task(task_id: int, status: str, priority: str, due_date: date | None, notes: str) -> None:
    execute(
        """
        UPDATE tasks
        SET status = ?, priority = ?, due_date = ?, notes = ?
        WHERE id = ?
        """,
        (status, priority, due_date.isoformat() if due_date else None, notes.strip(), task_id),
    )


def delete_project(project_id: int) -> None:
    execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
    execute("DELETE FROM projects WHERE id = ?", (project_id,))


def delete_task(task_id: int) -> None:
    execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def move_project(project_id: int, direction: int) -> None:
    comparator = "<" if direction < 0 else ">"
    ordering = "DESC" if direction < 0 else "ASC"
    with closing(get_connection()) as conn:
        current = conn.execute("SELECT id, sort_order FROM projects WHERE id = ?", (project_id,)).fetchone()
        if current is None:
            return
        neighbor = conn.execute(
            f"""
            SELECT id, sort_order
            FROM projects
            WHERE sort_order {comparator} ?
            ORDER BY sort_order {ordering}, id {ordering}
            LIMIT 1
            """,
            (current["sort_order"],),
        ).fetchone()
        if neighbor is None:
            return
        conn.execute("UPDATE projects SET sort_order = ? WHERE id = ?", (neighbor["sort_order"], current["id"]))
        conn.execute("UPDATE projects SET sort_order = ? WHERE id = ?", (current["sort_order"], neighbor["id"]))
        conn.commit()


def move_task(task_id: int, direction: int) -> None:
    comparator = "<" if direction < 0 else ">"
    ordering = "DESC" if direction < 0 else "ASC"
    with closing(get_connection()) as conn:
        current = conn.execute(
            "SELECT id, project_id, sort_order FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if current is None:
            return
        neighbor = conn.execute(
            f"""
            SELECT id, sort_order
            FROM tasks
            WHERE project_id = ? AND status != 'Done' AND sort_order {comparator} ?
            ORDER BY sort_order {ordering}, id {ordering}
            LIMIT 1
            """,
            (current["project_id"], current["sort_order"]),
        ).fetchone()
        if neighbor is None:
            return
        conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (neighbor["sort_order"], current["id"]))
        conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (current["sort_order"], neighbor["id"]))
        conn.commit()


def parse_date(value: object) -> date | None:
    if value is None or pd.isna(value) or value == "":
        return None
    return date.fromisoformat(str(value))


def days_until(value: object) -> int | None:
    parsed = parse_date(value)
    if parsed is None:
        return None
    return (parsed - date.today()).days


@st.cache_data(show_spinner=False)
def image_data_url(path: str) -> str:
    image_path = Path(path)
    mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def style_app() -> None:
    st.set_page_config(page_title="Project Manager", page_icon="PM", layout="wide")
    st.markdown(
        """
        <style>
        :root {
            --pm-coral: #ff6b6b;
            --pm-gold: #f6c85f;
            --pm-mint: #4ecdc4;
            --pm-blue: #45aaf2;
            --pm-ink: #243042;
        }
        .stApp {
            background:
                radial-gradient(circle at 10% 78%, rgba(27, 214, 180, 0.86), transparent 28rem),
                radial-gradient(circle at 38% 62%, rgba(36, 167, 174, 0.52), transparent 29rem),
                radial-gradient(circle at 80% 18%, rgba(33, 96, 174, 0.58), transparent 24rem),
                linear-gradient(135deg, #08131f 0%, #0b3140 45%, #0f3b72 100%);
            background-attachment: fixed;
        }
        .stApp::before,
        .stApp::after {
            content: "";
            position: fixed;
            top: 7rem;
            bottom: 2rem;
            width: 9rem;
            pointer-events: none;
            opacity: 0.24;
            z-index: 0;
        }
        .stApp::before {
            left: 0;
            background:
                linear-gradient(135deg, rgba(78, 205, 196, 0.32), transparent 55%),
                repeating-linear-gradient(160deg, transparent 0 18px, rgba(255, 255, 255, 0.12) 18px 21px);
            clip-path: polygon(0 0, 72% 10%, 38% 52%, 92% 100%, 0 100%);
        }
        .stApp::after {
            right: 0;
            background:
                linear-gradient(225deg, rgba(69, 170, 242, 0.26), transparent 55%),
                repeating-linear-gradient(25deg, transparent 0 20px, rgba(255, 255, 255, 0.10) 20px 23px);
            clip-path: polygon(100% 0, 28% 8%, 62% 48%, 12% 100%, 100% 100%);
        }
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2rem;
            max-width: 1180px;
            position: relative;
            z-index: 1;
        }
        .pm-hero {
            min-height: 210px;
            border: 1px solid rgba(78, 205, 196, 0.28);
            border-radius: 8px;
            overflow: hidden;
            margin: 0 0 1rem;
            background:
                linear-gradient(90deg, rgba(4, 17, 28, 0.93), rgba(5, 34, 49, 0.72) 44%, rgba(7, 54, 78, 0.24)),
                var(--pm-hero-image);
            background-size: cover;
            background-position: center right;
            box-shadow: 0 18px 50px rgba(0, 0, 0, 0.30);
        }
        .pm-hero-inner {
            width: min(62%, 650px);
            padding: 2.1rem 2.2rem;
        }
        .pm-hero-kicker {
            color: var(--pm-mint);
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }
        .pm-hero h1 {
            color: #ffffff;
            font-size: 2.85rem;
            line-height: 1.02;
            margin: 0;
        }
        .pm-hero p {
            color: rgba(255, 255, 255, 0.76);
            font-size: 1rem;
            margin: 0.8rem 0 0;
            max-width: 36rem;
        }
        .pm-hero-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 1.15rem;
        }
        .pm-hero-chip {
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 999px;
            color: #ffffff;
            font-size: 0.78rem;
            font-weight: 700;
            padding: 0.28rem 0.65rem;
            background: rgba(255, 255, 255, 0.10);
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--pm-coral);
        }
        div[data-testid="stForm"],
        div[data-testid="stExpander"] {
            border-color: rgba(78, 205, 196, 0.28);
        }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(78, 205, 196, 0.34);
            border-radius: 8px;
            padding: 14px 16px;
            background:
                linear-gradient(135deg, rgba(27, 214, 180, 0.18), rgba(33, 96, 174, 0.16)),
                rgba(4, 17, 28, 0.42);
            backdrop-filter: blur(8px);
        }
        .section-title {
            color: var(--pm-mint);
            font-size: 1.02rem;
            font-weight: 700;
            margin: 0.5rem 0 0.4rem;
        }
        .project-strip {
            border-left: 5px solid var(--pm-coral);
            padding: 0.65rem 0.8rem;
            margin: 0.45rem 0 0.75rem;
            border-radius: 8px;
            background: linear-gradient(90deg, rgba(69, 170, 242, 0.14), rgba(246, 200, 95, 0.08));
        }
        .project-strip strong {
            color: inherit;
        }
        .sticky-board {
            position: relative;
            min-height: 560px;
            padding: 1.5rem;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.14);
            background:
                radial-gradient(circle at 22px 22px, rgba(69, 170, 242, 0.10) 0 2px, transparent 2px 100%),
                linear-gradient(90deg, rgba(255, 107, 107, 0.08), transparent 16%, transparent 84%, rgba(78, 205, 196, 0.08)),
                linear-gradient(115deg, rgba(255, 255, 255, 0.96), rgba(244, 249, 246, 0.94)),
                repeating-linear-gradient(0deg, transparent 0 35px, rgba(69, 170, 242, 0.06) 35px 36px);
            background-size: 44px 44px, auto, auto, auto;
            box-shadow: inset 0 0 38px rgba(16, 24, 40, 0.10), 0 20px 50px rgba(0, 0, 0, 0.20);
            color: #1f2937;
            overflow-x: auto;
        }
        .sticky-board::before {
            content: "";
            position: absolute;
            left: 1.5rem;
            right: 1.5rem;
            top: 5.1rem;
            height: 7px;
            border-radius: 999px;
            background: linear-gradient(90deg, #ff6b6b, #f6c85f, #4ecdc4, #45aaf2);
            opacity: 0.36;
        }
        .sticky-board-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            color: #0f172a;
            margin-bottom: 1.2rem;
        }
        .sticky-board-title h2 {
            font-size: 1.4rem;
            margin: 0;
        }
        .sticky-board-title span {
            color: #475569;
            font-size: 0.92rem;
            font-weight: 700;
        }
        .sticky-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.35rem;
            align-items: start;
            justify-content: start;
        }
        .sticky-column {
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }
        .sticky-board.has-one-project .sticky-grid {
            display: block;
        }
        .sticky-board.has-one-project .sticky-column {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 250px));
            gap: 1rem;
            align-items: start;
        }
        .sticky-board.has-one-project .project-note {
            grid-column: span 1;
        }
        .sticky-note {
            position: relative;
            color: #1f2937;
            border-radius: 2px;
            padding: 0.9rem 0.9rem 0.85rem;
            box-shadow: 0 12px 18px rgba(15, 23, 42, 0.22);
            transform: rotate(var(--tilt, -1deg));
            background-image:
                repeating-linear-gradient(0deg, transparent 0 22px, rgba(31, 41, 55, 0.13) 22px 23px),
                linear-gradient(180deg, rgba(255, 255, 255, 0.26), rgba(255, 255, 255, 0));
        }
        .sticky-note::after {
            content: "";
            position: absolute;
            left: 18%;
            right: 18%;
            bottom: -10px;
            height: 12px;
            border-radius: 50%;
            background: rgba(15, 23, 42, 0.20);
            filter: blur(7px);
            z-index: -1;
        }
        .project-note {
            min-height: 116px;
            background-color: #ff7f50;
        }
        .project-note.done {
            background-color: #8fd694;
        }
        .project-note.blocked {
            background-color: #ff6b6b;
        }
        .task-note {
            min-height: 112px;
            font-size: 0.92rem;
        }
        .note-low {
            background-color: #b9fbc0;
        }
        .note-medium {
            background-color: #73e0c3;
        }
        .note-high {
            background-color: #ffd166;
        }
        .note-critical {
            background-color: #ff6b9a;
        }
        .note-blocked {
            outline: 3px solid rgba(239, 68, 68, 0.72);
        }
        .note-done {
            opacity: 0.66;
        }
        .sticky-note h3,
        .sticky-note h4 {
            color: #111827;
            font-family: "Comic Sans MS", "Segoe Print", cursive;
            line-height: 1.05;
            margin: 0;
        }
        .sticky-note h3 {
            font-size: 1.75rem;
        }
        .sticky-note h4 {
            font-size: 1.2rem;
            text-decoration: underline;
            text-decoration-thickness: 3px;
            text-underline-offset: 0.18rem;
        }
        .sticky-meta {
            color: #334155;
            font-size: 0.82rem;
            font-weight: 700;
            margin-top: 0.45rem;
        }
        .sticky-body {
            color: #243042;
            font-family: "Comic Sans MS", "Segoe Print", cursive;
            font-size: 1rem;
            font-weight: 700;
            line-height: 1.2;
            margin-top: 0.55rem;
            white-space: pre-wrap;
        }
        .sticky-progress {
            height: 10px;
            border-radius: 999px;
            background: rgba(15, 23, 42, 0.18);
            margin-top: 0.75rem;
            overflow: hidden;
        }
        .sticky-progress span {
            display: block;
            height: 100%;
            border-radius: inherit;
            background: linear-gradient(90deg, #0ea5e9, #22c55e);
        }
        .due-note {
            width: fit-content;
            min-width: 86px;
            min-height: 64px;
            padding: 0.55rem 0.65rem;
            margin-left: auto;
            background-color: #ff3fb4;
            transform: rotate(3deg);
        }
        .due-note h4 {
            font-size: 0.96rem;
        }
        .empty-board-note {
            max-width: 340px;
            margin: 3rem auto;
            text-align: center;
        }
        .muted {
            color: #677083;
            font-size: 0.92rem;
        }
        @media (max-width: 760px) {
            .stApp::before,
            .stApp::after {
                display: none;
            }
            .pm-hero {
                min-height: 250px;
                background:
                    linear-gradient(180deg, rgba(8, 12, 22, 0.94), rgba(8, 12, 22, 0.68)),
                    var(--pm-hero-image);
                background-position: center;
            }
            .pm-hero-inner {
                width: auto;
                padding: 1.5rem;
            }
            .pm-hero h1 {
                font-size: 2.15rem;
            }
            .sticky-board {
                padding: 1rem;
            }
            .sticky-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    hero_style = ""
    if HERO_IMAGE_PATH.exists():
        hero_style = f' style="--pm-hero-image: url({image_data_url(str(HERO_IMAGE_PATH))});"'
    st.markdown(
        f"""
        <div class="pm-hero"{hero_style}>
            <div class="pm-hero-inner">
                <h1>Project Manager</h1>
                <p>Track owners, deadlines, priorities, blockers, and percent-complete progress in one colorful command center.</p>
                <div class="pm-hero-chips">
                    <span class="pm-hero-chip">Progress bars</span>
                    <span class="pm-hero-chip">Deadline radar</span>
                    <span class="pm-hero-chip">Task mix</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_counts(tasks: pd.DataFrame) -> dict[str, int]:
    counts = tasks["status"].value_counts().to_dict() if not tasks.empty else {}
    return {status: int(counts.get(status, 0)) for status in STATUS_OPTIONS}


def project_progress_summary(projects: pd.DataFrame) -> int:
    if projects.empty:
        return 0
    return int(round(projects["progress"].fillna(0).mean()))


def escape_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value), quote=True)


def format_short_date(value: object) -> str:
    parsed = parse_date(value)
    if parsed is None:
        return ""
    return f"{parsed.month}/{parsed.day}"


def note_tilt(seed: int) -> str:
    tilts = ["-1.5deg", "1deg", "-0.7deg", "1.4deg", "-1deg", "0.6deg"]
    return tilts[seed % len(tilts)]


def priority_class(priority: object) -> str:
    return PRIORITY_CLASSES.get(str(priority), "note-medium")


def upcoming_items(projects: pd.DataFrame, tasks: pd.DataFrame) -> pd.DataFrame:
    project_rows = projects.copy()
    project_rows["type"] = "Project"
    project_rows["title"] = project_rows["name"]

    task_rows = tasks.copy()
    task_rows["type"] = "Task"

    cols = ["type", "title", "owner", "status", "priority", "due_date"]
    combined = pd.concat([project_rows[cols], task_rows[cols]], ignore_index=True)
    if combined.empty:
        return combined
    combined = combined[combined["due_date"].notna() & (combined["status"] != "Done")].copy()
    combined["days_left"] = combined["due_date"].apply(days_until)
    return combined.sort_values(["days_left", "priority"], ascending=[True, True]).head(10)


def render_dashboard(projects: pd.DataFrame, tasks: pd.DataFrame) -> None:
    active_projects = projects[projects["progress"] < 100] if not projects.empty else projects
    overdue_tasks = tasks[
        (tasks["status"] != "Done") & tasks["due_date"].notna() & (tasks["due_date"].apply(days_until) < 0)
    ] if not tasks.empty else tasks
    blocked_tasks = tasks[tasks["status"] == "Blocked"] if not tasks.empty else tasks

    metric_cols = st.columns(4)
    metric_cols[0].metric("Active projects", len(active_projects))
    metric_cols[1].metric("Open tasks", len(tasks[tasks["status"] != "Done"]) if not tasks.empty else 0)
    metric_cols[2].metric("Avg project progress", f"{project_progress_summary(projects)}%")
    metric_cols[3].metric("Overdue tasks", len(overdue_tasks))

    if not projects.empty:
        st.markdown('<div class="section-title">Project Progress</div>', unsafe_allow_html=True)
        for _, project in projects.sort_values(["progress", "due_date"], ascending=[True, True], na_position="last").head(6).iterrows():
            st.markdown(
                f"""
                <div class="project-strip">
                    <strong>{project['name']}</strong>
                    <span class="muted"> - {project['owner'] or "Unassigned"} - {project['priority']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.progress(int(project["progress"]), text=f'{int(project["progress"])}% complete')

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown('<div class="section-title">Near-Term Focus</div>', unsafe_allow_html=True)
        items = upcoming_items(projects, tasks)
        if items.empty:
            st.info("No upcoming due dates yet.")
        else:
            st.dataframe(
                items[["type", "title", "owner", "status", "priority", "due_date", "days_left"]],
                hide_index=True,
                width="stretch",
            )

    with right:
        st.markdown('<div class="section-title">Task Mix</div>', unsafe_allow_html=True)
        counts = status_counts(tasks)
        st.bar_chart(pd.DataFrame({"status": counts.keys(), "tasks": counts.values()}).set_index("status"))


def render_board_order_controls(projects: pd.DataFrame, tasks: pd.DataFrame) -> None:
    if projects.empty:
        return

    with st.expander("Arrange post-its"):
        st.markdown('<div class="section-title">Project order</div>', unsafe_allow_html=True)
        ordered_projects = projects.sort_values(["sort_order", "id"])
        for position, (_, project) in enumerate(ordered_projects.iterrows()):
            label_col, left_col, right_col = st.columns([5, 1, 1])
            label_col.write(f"{position + 1}. {project['name']}")
            if left_col.button("<", key=f"project_left_{project['id']}", disabled=position == 0):
                move_project(int(project["id"]), -1)
                st.rerun()
            if right_col.button(">", key=f"project_right_{project['id']}", disabled=position == len(ordered_projects) - 1):
                move_project(int(project["id"]), 1)
                st.rerun()

        st.markdown('<div class="section-title">Task order</div>', unsafe_allow_html=True)
        for _, project in ordered_projects.iterrows():
            project_tasks = tasks[
                (tasks["project_id"] == int(project["id"])) & (tasks["status"] != "Done")
            ] if not tasks.empty else tasks
            if project_tasks.empty:
                continue
            st.write(project["name"])
            ordered_tasks = project_tasks.sort_values(["sort_order", "id"])
            for position, (_, task) in enumerate(ordered_tasks.iterrows()):
                label_col, up_col, down_col = st.columns([5, 1, 1])
                label_col.write(f"{position + 1}. {task['title']}")
                if up_col.button("Up", key=f"task_up_{task['id']}", disabled=position == 0):
                    move_task(int(task["id"]), -1)
                    st.rerun()
                if down_col.button("Down", key=f"task_down_{task['id']}", disabled=position == len(ordered_tasks) - 1):
                    move_task(int(task["id"]), 1)
                    st.rerun()


def render_board(projects: pd.DataFrame, tasks: pd.DataFrame) -> None:
    render_board_order_controls(projects, tasks)

    project_count = len(projects)
    task_count = len(tasks[tasks["status"] != "Done"]) if not tasks.empty else 0
    board_classes = "sticky-board has-one-project" if project_count == 1 else "sticky-board"
    board_html = [
        f'<div class="{board_classes}">'
        '<div class="sticky-board-title">'
        "<h2>Desk Board</h2>"
        "<span>Color coded by priority</span>"
        "</div>"
    ]

    if projects.empty:
        board_html.append(
            '<div class="sticky-note note-high empty-board-note" style="--tilt: -1deg;">'
            "<h3>Add a project</h3>"
            '<div class="sticky-body">Your post-it board will appear here once projects and tasks exist.</div>'
            "</div>"
        )
    else:
        board_html.append('<div class="sticky-grid">')
        for index, (_, project) in enumerate(projects.sort_values(["sort_order", "id"]).iterrows()):
            project_id = int(project["id"])
            project_tasks = tasks[tasks["project_id"] == project_id] if not tasks.empty else tasks
            open_tasks = project_tasks[project_tasks["status"] != "Done"] if not project_tasks.empty else project_tasks
            project_classes = ["sticky-note", "project-note"]
            if int(project["progress"]) >= 100:
                project_classes.append("done")
            if not open_tasks.empty and (open_tasks["status"] == "Blocked").any():
                project_classes.append("blocked")

            due = format_short_date(project["due_date"])
            due_html = ""
            if due:
                due_html = (
                    '<div class="sticky-note due-note" style="--tilt: 3deg;">'
                    "<h4>Due</h4>"
                    f'<div class="sticky-body">{escape_text(due)}</div>'
                    "</div>"
                )

            board_html.append(
                '<div class="sticky-column">'
                f'<div class="{" ".join(project_classes)}" style="--tilt: {note_tilt(index)};">'
                f"<h3>{escape_text(project['name'])}</h3>"
                f'<div class="sticky-meta">{escape_text(project["owner"] or "Unassigned")} - {escape_text(project["priority"])}</div>'
                f'<div class="sticky-progress"><span style="width: {int(project["progress"])}%;"></span></div>'
                f'<div class="sticky-meta">{int(project["progress"])}% complete</div>'
                "</div>"
                f"{due_html}"
            )

            if open_tasks.empty:
                board_html.append(
                    '<div class="sticky-note note-low task-note" style="--tilt: 1deg;">'
                    "<h4>Clear</h4>"
                    '<div class="sticky-body">No open tasks</div>'
                    "</div>"
                )
            else:
                for task_index, (_, task) in enumerate(open_tasks.sort_values(["sort_order", "id"]).iterrows()):
                    classes = ["sticky-note", "task-note", priority_class(task["priority"])]
                    if task["status"] == "Blocked":
                        classes.append("note-blocked")
                    if task["status"] == "Done":
                        classes.append("note-done")
                    task_due = format_short_date(task["due_date"])
                    task_meta = f"{task['status']} - {task['priority']}"
                    if task_due:
                        task_meta = f"{task_meta} - due {task_due}"
                    note_text = task["notes"] or task["title"]
                    board_html.append(
                        f'<div class="{" ".join(classes)}" style="--tilt: {note_tilt(project_id + task_index)};">'
                        f"<h4>{escape_text(task['title'])}</h4>"
                        f'<div class="sticky-meta">{escape_text(task_meta)}</div>'
                        f'<div class="sticky-body">{escape_text(note_text)}</div>'
                        "</div>"
                    )
            board_html.append("</div>")
        board_html.append("</div>")

    board_html.append("</div>")
    st.markdown("".join(board_html), unsafe_allow_html=True)
    st.caption(f"Showing {project_count} projects and {task_count} open tasks. Edit projects and tasks from the Add or Projects tabs.")


def render_project_form() -> None:
    with st.form("add_project", clear_on_submit=True):
        st.markdown('<div class="section-title">Add Project</div>', unsafe_allow_html=True)
        name = st.text_input("Project name")
        col1, col2 = st.columns(2)
        owner = col1.text_input("Owner")
        priority = col2.selectbox("Priority", PRIORITY_OPTIONS, index=1)
        progress = st.slider("Percent complete", min_value=0, max_value=100, value=0, step=5)
        due = st.date_input("Due date", value=None)
        notes = st.text_area("Notes", height=90)
        submitted = st.form_submit_button("Add project", type="primary")
        if submitted:
            if name.strip():
                add_project(name, owner, progress, priority, due, notes)
                st.success("Project added.")
                st.rerun()
            else:
                st.warning("Project name is required.")


def render_task_form(projects: pd.DataFrame) -> None:
    if projects.empty:
        st.info("Add a project before creating tasks.")
        return

    project_lookup = {row["name"]: int(row["id"]) for _, row in projects.iterrows()}
    with st.form("add_task", clear_on_submit=True):
        st.markdown('<div class="section-title">Add Task</div>', unsafe_allow_html=True)
        project_name = st.selectbox("Project", list(project_lookup.keys()))
        title = st.text_input("Task title")
        col1, col2, col3 = st.columns(3)
        owner = col1.text_input("Task owner")
        status = col2.selectbox("Task status", STATUS_OPTIONS, index=1)
        priority = col3.selectbox("Task priority", PRIORITY_OPTIONS, index=1)
        due = st.date_input("Task due date", value=None)
        notes = st.text_area("Task notes", height=90)
        submitted = st.form_submit_button("Add task", type="primary")
        if submitted:
            if title.strip():
                add_task(project_lookup[project_name], title, owner, status, priority, due, notes)
                st.success("Task added.")
                st.rerun()
            else:
                st.warning("Task title is required.")


def render_project_detail(projects: pd.DataFrame, tasks: pd.DataFrame) -> None:
    if projects.empty:
        st.info("No projects yet.")
        return

    project_lookup = {row["name"]: int(row["id"]) for _, row in projects.iterrows()}
    selected_name = st.selectbox("Project", list(project_lookup.keys()))
    project_id = project_lookup[selected_name]
    project = projects[projects["id"] == project_id].iloc[0]
    project_tasks = tasks[tasks["project_id"] == project_id] if not tasks.empty else tasks

    with st.expander("Project details", expanded=True):
        st.progress(int(project["progress"]), text=f'{int(project["progress"])}% complete')
        progress = st.slider(
            "Project percent complete",
            min_value=0,
            max_value=100,
            value=int(project["progress"]),
            step=5,
        )
        col1, col2 = st.columns(2)
        priority = col1.selectbox("Project priority", PRIORITY_OPTIONS, index=PRIORITY_OPTIONS.index(project["priority"]))
        due = col2.date_input("Project due date", value=parse_date(project["due_date"]))
        notes = st.text_area("Project notes", value=project["notes"] or "", height=100)
        save_col, delete_col = st.columns([1, 5])
        if save_col.button("Save project", type="primary"):
            update_project(project_id, progress, priority, due, notes)
            st.success("Project updated.")
            st.rerun()
        if delete_col.button("Delete project"):
            delete_project(project_id)
            st.warning("Project deleted.")
            st.rerun()

    st.markdown('<div class="section-title">Tasks</div>', unsafe_allow_html=True)
    if project_tasks.empty:
        st.info("No tasks for this project yet.")
        return

    for _, task in project_tasks.sort_values(["sort_order", "id"]).iterrows():
        with st.expander(task["title"], expanded=task["status"] != "Done"):
            col1, col2, col3 = st.columns(3)
            task_status = col1.selectbox(
                "Status",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(task["status"]),
                key=f"task_status_{task['id']}",
            )
            task_priority = col2.selectbox(
                "Priority",
                PRIORITY_OPTIONS,
                index=PRIORITY_OPTIONS.index(task["priority"]),
                key=f"task_priority_{task['id']}",
            )
            task_due = col3.date_input(
                "Due date",
                value=parse_date(task["due_date"]),
                key=f"task_due_{task['id']}",
            )
            task_notes = st.text_area("Notes", value=task["notes"] or "", key=f"task_notes_{task['id']}")
            save_col, delete_col = st.columns([1, 5])
            if save_col.button("Save task", key=f"save_task_{task['id']}", type="primary"):
                update_task(int(task["id"]), task_status, task_priority, task_due, task_notes)
                st.success("Task updated.")
                st.rerun()
            if delete_col.button("Delete task", key=f"delete_task_{task['id']}"):
                delete_task(int(task["id"]))
                st.warning("Task deleted.")
                st.rerun()


def render_tables(projects: pd.DataFrame, tasks: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">All Projects</div>', unsafe_allow_html=True)
    st.dataframe(
        projects.drop(columns=["created_at", "sort_order"], errors="ignore"),
        hide_index=True,
        width="stretch",
        column_config={
            "progress": st.column_config.ProgressColumn(
                "progress",
                format="%d%%",
                min_value=0,
                max_value=100,
            )
        },
    )

    st.markdown('<div class="section-title">All Tasks</div>', unsafe_allow_html=True)
    if tasks.empty:
        st.info("No tasks yet.")
    else:
        task_table = tasks.merge(projects[["id", "name"]], left_on="project_id", right_on="id", suffixes=("", "_project"))
        task_table = task_table.rename(columns={"name": "project"})
        st.dataframe(
            task_table[["project", "title", "owner", "status", "priority", "due_date", "notes"]],
            hide_index=True,
            width="stretch",
        )


def main() -> None:
    style_app()
    init_db()

    render_header()

    projects = query_df("SELECT * FROM projects ORDER BY sort_order ASC, id ASC")
    tasks = query_df("SELECT * FROM tasks ORDER BY sort_order ASC, id ASC")

    tabs = st.tabs(["Dashboard", "Board", "Add", "Projects", "Tables"])
    with tabs[0]:
        render_dashboard(projects, tasks)
    with tabs[1]:
        render_board(projects, tasks)
    with tabs[2]:
        left, right = st.columns(2)
        with left:
            render_project_form()
        with right:
            render_task_form(projects)
    with tabs[3]:
        render_project_detail(projects, tasks)
    with tabs[4]:
        render_tables(projects, tasks)


if __name__ == "__main__":
    main()
