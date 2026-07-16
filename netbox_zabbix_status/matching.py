"""Párovacia logika Zabbix host <-> NetBox Device/VM.

HostMatcher pracuje nad predpripravenými mapami (builduje ich sync.py z DB),
takže samotné párovanie je čistá funkcia a dá sa unit-testovať bez DB/API.
"""
from .choices import MatchMethodChoices


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


class HostMatcher:
    """Páruje Zabbix hosty na NetBox objekty. Poradie: meno -> IP -> nespárované.

    Mapy mien: {normalizované meno: [pk, ...]} zvlášť pre devices a VM.
    Mapy IP: {ip string: [(kind, pk), ...]} — primary IP majú prednosť pred
    ľubovoľnou priradenou IP. Zhoda platí len ak je jednoznačná (práve jeden
    kandidát); nejednoznačné zhody sa radšej nepárujú, aby sync nič nepokazil.
    """

    def __init__(self, device_names, vm_names, primary_ips, any_ips,
                 strip_domains=(), match_by_ip=True):
        self.device_names = device_names
        self.vm_names = vm_names
        self.primary_ips = primary_ips
        self.any_ips = any_ips
        self.strip_domains = strip_domains
        self.match_by_ip = match_by_ip

    def match(self, zabbix_host: dict):
        """Vráti (kind, pk, match_method); kind je 'device' / 'vm' / None.

        zabbix_host je dict z host.get (kľúče 'host', 'name', 'interfaces').
        """
        # 1) podľa mena — skúša technické aj viditeľné meno
        for raw in (zabbix_host.get('host', ''), zabbix_host.get('name', '')):
            if not raw:
                continue
            key = normalize_hostname(raw, self.strip_domains)
            for kind, names in (('device', self.device_names), ('vm', self.vm_names)):
                candidates = names.get(key, ())
                if len(candidates) == 1:
                    return kind, candidates[0], MatchMethodChoices.NAME

        # 2) podľa IP zo Zabbix interfejsov
        if self.match_by_ip:
            ips = {i.get('ip') for i in zabbix_host.get('interfaces', []) if i.get('ip')}
            ips.discard('127.0.0.1')
            for ip_map in (self.primary_ips, self.any_ips):
                targets = set()
                for ip in ips:
                    targets.update(ip_map.get(ip, ()))
                if len(targets) == 1:
                    kind, pk = next(iter(targets))
                    return kind, pk, MatchMethodChoices.IP

        return None, None, MatchMethodChoices.NONE


def match_unmatched_host(matcher: HostMatcher, zabbix_host: dict, claimed: set):
    """Obálka nad `HostMatcher.match()`, ktorá navyše zaručí 1:1 párovanie —
    ak by matcher.match() vrátil kandidáta, ktorý je už v `claimed` (iný
    ZabbixHost už naň ukazuje, či už z DB pred týmto behom, alebo mu ho
    priradil tento istý beh o riadok skôr), namiesto neho vráti
    (None, None, MatchMethodChoices.NONE) — host ostane nespárovaný, radšej
    než aby ukradol cudziu väzbu (DB UniqueConstraint by to aj tak zamietlo
    a spadla by celá sync transakcia). Pri úspešnej voľnej zhode `claimed`
    rovno aktualizuje (mutuje set), aby ju nemohol zabrať aj ďalší host
    v tom istom behu spracovaný o riadok neskôr. `matcher.match()` sám osebe
    ostáva čistá funkcia (testovateľná bez tohto stavu) — táto obálka je
    jediné miesto, ktoré zavádza mutabilitu, používa ju `sync.run_sync()`
    aj hromadné prepárovanie (bulk re-match)."""
    kind, pk, method = matcher.match(zabbix_host)
    if kind is not None and (kind, pk) in claimed:
        return None, None, MatchMethodChoices.NONE
    if kind is not None:
        claimed.add((kind, pk))
    return kind, pk, method
