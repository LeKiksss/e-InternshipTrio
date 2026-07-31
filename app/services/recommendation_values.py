"""Canonical numeric values used by roaming recommendation matching."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

METRIC_NAMES = (
    "data_gb",
    "local_minutes",
    "international_minutes",
    "sms",
)
CANONICAL_QUANTUM = Decimal("0.000001")


def canonical_decimal(value, *, field="value", nonnegative=True):
    """Return one finite Decimal at the database's exact six-place scale."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be a number.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
        number = number.quantize(CANONICAL_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a number.") from error
    if not number.is_finite():
        raise ValueError(f"{field} must be finite.")
    if nonnegative and number < 0:
        raise ValueError(f"{field} cannot be negative.")
    return number


def canonical_string(value, *, field="value"):
    return format(canonical_decimal(value, field=field), ".6f")


def canonical_metrics(values):
    return {
        metric: canonical_decimal(values.get(metric, 0), field=metric)
        for metric in METRIC_NAMES
    }


def canonical_metric_floats(values):
    return {metric: float(value) for metric, value in canonical_metrics(values).items()}
