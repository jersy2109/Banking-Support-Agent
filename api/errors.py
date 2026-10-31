"""One error shape for the whole API, so callers (including the agent) can act on a code."""

from fastapi import HTTPException


def api_error(status_code, code, message, headers=None, **extra):
    """Raise-able error whose JSON body is {"detail": {"code": ..., "message": ..., ...}}."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra}, headers=headers)
