"""Who a request acts as: the user its session cookie says logged in (see
app/auth.py)."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request


def current_user_id(request: Request) -> int:
    """The id of the user making the request; a 401 if they aren't logged in."""
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Log in to continue.")
    return user_id


CurrentUser = Annotated[int, Depends(current_user_id)]
