"""Shared job lifecycle state definitions."""

ACTIVE_STATUSES = frozenset({"starting", "running", "collecting", "cancelling"})
DONE_STATUSES = frozenset({"finished", "failed", "cancelled"})
