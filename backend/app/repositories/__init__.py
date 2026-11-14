# Data-access layer (repository pattern).
# Each repo: find_all / find_by_id / create / update / delete + domain queries.
# Services depend on the interface, so storage can change and tests can use in-memory fakes.
