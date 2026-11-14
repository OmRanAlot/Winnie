"""Winnie backend.

Layering (dependencies point downward only):
    api/routes  ->  services  ->  repositories  ->  models
Services may also call integrations; routes never call integrations directly.
"""
