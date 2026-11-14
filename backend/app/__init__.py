# Winnie backend package.
# Layering (dependencies point downward only):
#   api/routes  ->  services  ->  repositories  ->  models
#   services may also call integrations; routes never call integrations directly.
