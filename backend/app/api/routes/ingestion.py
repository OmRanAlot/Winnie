# /ingestion — pulling tasks out of meetings and existing docs.
# TODO:
#   POST /ingestion/meetings                 upload audio / transcript -> task candidates
#   POST /ingestion/sync/task-tracker        pull the Google Sheets tracker
#   POST /ingestion/sync/docs                scan meeting notes / agendas in Google Docs
#   GET  /ingestion/candidates               extracted tasks awaiting human confirmation
#   POST /ingestion/candidates/{id}/confirm  (and /reject)
