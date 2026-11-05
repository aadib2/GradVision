"""Shared base classes for request schemas."""

from typing import ClassVar

from pydantic import BaseModel, model_validator


class PartialUpdate(BaseModel):
    """Base for PATCH bodies: every field is optional, omit one to leave it unchanged.

    Fields named in `non_nullable` may be omitted but not sent as an explicit null,
    because the column behind them is NOT NULL (or the response schema requires a
    value). Leave nullable columns (e.g. notes, due_date) out of the set so clients
    can still clear them.
    """

    non_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_explicit_nulls(self):
        nulls = sorted(
            name
            for name in self.non_nullable & self.model_fields_set
            if getattr(self, name) is None
        )
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self
