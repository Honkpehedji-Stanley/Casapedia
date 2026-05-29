"""Helpers de formatage pour l'affichage des KPI (français : espace insécable, €, m²)."""

NBSP = " "  # espace fine insécable, séparateur de milliers FR


def _group_thousands(value, decimals=0):
    formatted = f"{value:,.{decimals}f}"
    # 1,234,567.0 -> 1 234 567 (séparateur FR)
    return formatted.replace(",", NBSP).replace(".", ",")


def format_number(value, decimals=0):
    if value is None:
        return "—"
    return _group_thousands(value, decimals)


def format_euro(value, decimals=0):
    if value is None:
        return "—"
    return f"{_group_thousands(value, decimals)}{NBSP}€"


def format_euro_m2(value, decimals=0):
    if value is None:
        return "—"
    return f"{_group_thousands(value, decimals)}{NBSP}€/m²"


def format_compact(value):
    """Format compact pour les grands volumes : 1,2 M / 345 k."""
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}".replace(".", ",") + f"{NBSP}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}{NBSP}k"
    return _group_thousands(value)
