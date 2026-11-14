"""Command-line tools. Run from backend/ as `uv run python -m app.cli.<name> --help`.

    import_roster      Import the e-board roster (prints SQL or applies it)
    create_demo_user   Create a demo login for the frontend
    preview_tracker    Dry-run a task-tracker export and print what would change
    import_tracker     Apply a task-tracker export to Supabase (needs --apply and a plan ID)
    prepare_planning   Turn calendar/task CSVs into the planning knowledge JSON
    prepare_pipeline   Turn a Spring calendar CSV into the planning taxonomy JSON
    preview_pipeline   Run the staged planning pipeline and save a private draft file

These are thin entry points: parse arguments, call a function in services/, print a summary.
Keep logic out of them so the API and the tests can reuse it. None of them is imported by the API.
"""
