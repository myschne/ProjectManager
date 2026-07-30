from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "project_manager.db"

STATUS_OPTIONS = ["Not started", "In progress", "Blocked", "Done"]
PRIORITY_OPTIONS = ["Low", "Medium", "High", "Critical"]


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
                priority TEXT NOT NULL DEFAULT 'Medium',
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
                due_date TEXT,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()


def query_df(query: str, params: tuple = ()) -> pd.DataFrame:
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn, params=params)


def execute(query: str, params: tuple = ()) -> None:
    with closing(get_connection()) as conn:
        conn.execute(query, params)
        conn.commit()


def add_project(name: str, owner: str, status: str, priority: str, due_date: date | None, notes: str) -> None:
    execute(
        """
        INSERT INTO projects (name, owner, status, priority, due_date, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name.strip(),
            owner.strip(),
            status,
            priority,
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
        INSERT INTO tasks (project_id, title, owner, status, priority, due_date, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            title.strip(),
            owner.strip(),
            status,
            priority,
            due_date.isoformat() if due_date else None,
            notes.strip(),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def update_project(project_id: int, status: str, priority: str, due_date: date | None, notes: str) -> None:
    execute(
        """
        UPDATE projects
        SET status = ?, priority = ?, due_date = ?, notes = ?
        WHERE id = ?
        """,
        (status, priority, due_date.isoformat() if due_date else None, notes.strip(), project_id),
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


def parse_date(value: object) -> date | None:
    if value is None or pd.isna(value) or value == "":
        return None
    return date.fromisoformat(str(value))


def days_until(value: object) -> int | None:
    parsed = parse_date(value)
    if parsed is None:
        return None
    return (parsed - date.today()).days


def style_app() -> None:
    st.set_page_config(page_title="Project Manager", page_icon="PM", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2rem;
            max-width: 1180px;
        }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(128, 132, 149, 0.35);
            border-radius: 8px;
            padding: 14px 16px;
            background: rgba(128, 132, 149, 0.08);
        }
        .section-title {
            font-size: 1.02rem;
            font-weight: 700;
            margin: 0.5rem 0 0.4rem;
        }
        .muted {
            color: #677083;
            font-size: 0.92rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_counts(tasks: pd.DataFrame) -> dict[str, int]:
    counts = tasks["status"].value_counts().to_dict() if not tasks.empty else {}
    return {status: int(counts.get(status, 0)) for status in STATUS_OPTIONS}


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
    active_projects = projects[projects["status"] != "Done"] if not projects.empty else projects
    overdue_tasks = tasks[
        (tasks["status"] != "Done") & tasks["due_date"].notna() & (tasks["due_date"].apply(days_until) < 0)
    ] if not tasks.empty else tasks
    blocked_tasks = tasks[tasks["status"] == "Blocked"] if not tasks.empty else tasks

    metric_cols = st.columns(4)
    metric_cols[0].metric("Active projects", len(active_projects))
    metric_cols[1].metric("Open tasks", len(tasks[tasks["status"] != "Done"]) if not tasks.empty else 0)
    metric_cols[2].metric("Blocked tasks", len(blocked_tasks))
    metric_cols[3].metric("Overdue tasks", len(overdue_tasks))

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


def render_project_form() -> None:
    with st.form("add_project", clear_on_submit=True):
        st.markdown('<div class="section-title">Add Project</div>', unsafe_allow_html=True)
        name = st.text_input("Project name")
        col1, col2, col3 = st.columns(3)
        owner = col1.text_input("Owner")
        status = col2.selectbox("Status", STATUS_OPTIONS, index=1)
        priority = col3.selectbox("Priority", PRIORITY_OPTIONS, index=1)
        due = st.date_input("Due date", value=None)
        notes = st.text_area("Notes", height=90)
        submitted = st.form_submit_button("Add project", type="primary")
        if submitted:
            if name.strip():
                add_project(name, owner, status, priority, due, notes)
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
        col1, col2, col3 = st.columns(3)
        status = col1.selectbox("Project status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(project["status"]))
        priority = col2.selectbox("Project priority", PRIORITY_OPTIONS, index=PRIORITY_OPTIONS.index(project["priority"]))
        due = col3.date_input("Project due date", value=parse_date(project["due_date"]))
        notes = st.text_area("Project notes", value=project["notes"] or "", height=100)
        save_col, delete_col = st.columns([1, 5])
        if save_col.button("Save project", type="primary"):
            update_project(project_id, status, priority, due, notes)
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

    for _, task in project_tasks.sort_values(["status", "due_date"], na_position="last").iterrows():
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
    st.dataframe(projects.drop(columns=["created_at"], errors="ignore"), hide_index=True, width="stretch")

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

    st.title("Project Manager")
    st.caption("Track projects, tasks, owners, priorities, blockers, and upcoming deadlines.")

    projects = query_df("SELECT * FROM projects ORDER BY created_at DESC")
    tasks = query_df("SELECT * FROM tasks ORDER BY created_at DESC")

    tabs = st.tabs(["Dashboard", "Add", "Projects", "Tables"])
    with tabs[0]:
        render_dashboard(projects, tasks)
    with tabs[1]:
        left, right = st.columns(2)
        with left:
            render_project_form()
        with right:
            render_task_form(projects)
    with tabs[2]:
        render_project_detail(projects, tasks)
    with tabs[3]:
        render_tables(projects, tasks)


if __name__ == "__main__":
    main()
