"""Párovacia logika Zabbix host <-> NetBox Device/VM.

Čisté funkcie bez DB/API závislostí, aby sa dali unit-testovať samostatne.
Plná párovacia pipeline (hostid -> meno -> IP -> unmatched) príde v M2
spolu so sync jobom.
"""


def normalize_hostname(name: str, strip_domains=()) -> str:
    """Znormalizuje meno na porovnávanie: lowercase, orezané medzery a odrezaný
    prvý zhodný doménový suffix (napr. 'SW1.firma.sk' -> 'sw1' pre ['firma.sk'])."""
    normalized = name.strip().lower()
    for domain in strip_domains:
        suffix = '.' + domain.strip('.').lower()
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized
