"""Database access.

    repository.py   Supabase reads and writes for seats, people (alias matching), meetings, tasks
                    and dependencies. Uses the client from integrations/supabase_client.py.

Services call this module; routes never do. Tests replace the client with tests/fake_supabase.py.
"""
