"""API-key scope vocabulary shared by the auth middleware and key administration.

read (GET data), write (upload/run/archive/sync), admin (users, keys, audit log), * (everything).
Older scope names are accepted as aliases.
"""
API_SCOPES = {"read", "write", "admin", "*"}
SCOPE_ALIASES = {"reconciliation:read": "read", "audit:read": "read", "uploads:write": "write",
                 "reconciliation:run": "write", "workspace:admin": "admin"}
ADMIN_PATH_PREFIXES = ("/api/auth/users", "/api/auth/api-keys", "/api/auth/organizations", "/api/agent/v1/audit-events")


def effective_scopes(scopes) -> set:
    return {SCOPE_ALIASES.get(s, s) for s in (scopes or [])} & API_SCOPES
