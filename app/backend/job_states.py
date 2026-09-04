"""Shared job lifecycle state definitions."""

ACTIVE_STATUSES = frozenset({"starting", "running", "collecting"})
DONE_STATUSES = frozenset({"finished", "failed", "cancelled"})
