# Project Manager

A local Streamlit app for tracking projects, tasks, owners, priorities, blockers, and due dates.

## Run

```powershell
pip install -r requirements.txt
streamlit run app.py
```

The app stores data in `project_manager.db` in this folder.

## Data persistence

Local desktop runs keep data in `project_manager.db`. Hosted Streamlit apps can lose runtime-created files when the app sleeps, restarts, or redeploys, so use the sidebar `Data Backup` widget to download a JSON backup and restore it later if needed.
