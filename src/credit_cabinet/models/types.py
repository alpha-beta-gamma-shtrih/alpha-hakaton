from enum import StrEnum

from sqlalchemy import JSON, Enum, Numeric
from sqlalchemy.dialects.postgresql import JSONB

MONEY = Numeric(18, 2)
RATE = Numeric(6, 3)
JSON_VALUE = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def enum_type(enum: type[StrEnum], name: str | None = None) -> Enum:
    return Enum(
        enum,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name or enum.__name__.lower(),
    )
