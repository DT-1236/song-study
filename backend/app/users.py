"""Who a request acts as. Nothing authenticates yet, so every request is the
seeded default user; OAuth later replaces `current_user_id` alone."""

from typing import Annotated

from fastapi import Depends

# The row migration 0016 seeds.
DEFAULT_USER_ID = 1


def current_user_id() -> int:
    """The id of the user making the request."""
    return DEFAULT_USER_ID


# Routes give it DEFAULT_USER_ID as a plain default too, so calling one
# directly (as the tests do) acts as the default user without a request.
CurrentUser = Annotated[int, Depends(current_user_id)]
