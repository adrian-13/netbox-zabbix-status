"""Tenký wrapper nad zabbix_utils klientom.

Konfigurácia sa číta z PLUGINS_CONFIG['netbox_zabbix_status']. Klient sa vytvára
per-použitie — auth cez API token je bezstavový, netreba login/logout session.
"""
from django.conf import settings
from django.core.cache import cache

from zabbix_utils import ZabbixAPI

PLUGIN_NAME = 'netbox_zabbix_status'
HISTORY_LIMIT = 500


class ZabbixConfigError(Exception):
    """Plugin nie je nakonfigurovaný (chýba api_url alebo api_token)."""


def get_config() -> dict:
    return settings.PLUGINS_CONFIG.get(PLUGIN_NAME, {})


def get_setting(key, default=None):
    """Runtime nastavenie správania: DB singleton (Zabbix → Nastavenia v UI)
    má prednosť pred PLUGINS_CONFIG. Pri nedostupnej DB (štart, migrácie)
    bezpečne padá na statickú konfiguráciu. Pripojenie (api_url/api_token)
    týmto nejde — to zostáva výhradne v PLUGINS_CONFIG/env."""
    try:
        from .models import ZabbixConfiguration
        obj = ZabbixConfiguration.objects.first()
    except Exception:
        obj = None
    if obj is not None and hasattr(obj, key):
        return getattr(obj, key)
    return get_config().get(key, default)


def get_client() -> ZabbixAPI:
    cfg = get_config()
    if not cfg.get('api_url') or not cfg.get('api_token'):
        raise ZabbixConfigError(
            "Nastav 'api_url' a 'api_token' v PLUGINS_CONFIG['netbox_zabbix_status'] "
            '(env ZABBIX_API_URL / ZABBIX_API_TOKEN).'
        )
    return ZabbixAPI(
        url=cfg['api_url'],
        token=cfg['api_token'],
        validate_certs=cfg.get('verify_ssl', True),
    )


def get_web_url() -> str:
    """Základ URL Zabbix UI pre deep-linky (web_url s fallbackom na api_url)."""
    cfg = get_config()
    return (cfg.get('web_url') or cfg.get('api_url') or '').rstrip('/')


def get_live_problems(hostid: int) -> list:
    """Aktívne problémy hosta priamo zo Zabbixu, s krátkou Redis cache
    (cache_ttl sekúnd), aby opakované načítanie tabu nezaťažovalo Zabbix API.
    Chyby (nedostupné API, chýbajúca konfigurácia) nechá preletieť — volajúci
    spadne späť na DB snapshot."""
    cache_key = f'{PLUGIN_NAME}:problems:{hostid}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    api = get_client()
    params = dict(
        hostids=[hostid],
        # objectid = triggerid (source=trigger je jediný typ problémov, ktoré
        # sledujeme) — potrebné na priamy odkaz na problém v Zabbixe (tr_events.php)
        output=['eventid', 'objectid', 'name', 'severity', 'acknowledged',
                'suppressed', 'clock', 'opdata'],
        selectTags='extend',
        severities=list(range(int(get_setting('min_severity', 2)), 6)),
        recent=False,
        sortfield='eventid',
    )
    if not get_setting('include_suppressed', False):
        params['suppressed'] = False
    problems = api.problem.get(**params)
    cache.set(cache_key, problems, int(get_setting('cache_ttl', 30)))
    return problems


def get_host_inventory(hostid: int) -> dict:
    """GPS súradnice hosta z jeho Zabbix inventory, priamo z API — podobne ako
    história problémov sa nikde neukladá (treba len raz, pri predvyplnení
    importného formulára). Prázdny dict, ak host nemá inventory zapnuté alebo
    súradnice nevyplnené."""
    cache_key = f'{PLUGIN_NAME}:inventory:{hostid}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    api = get_client()
    hosts = api.host.get(
        hostids=[hostid],
        output=[],
        selectInventory=['location_lat', 'location_lon'],
    )
    # Zabbix vráti 'inventory': [] (nie {}) keď má host vypnuté inventory
    inventory = (hosts[0].get('inventory') or {}) if hosts else {}
    cache.set(cache_key, inventory, int(get_setting('cache_ttl', 30)))
    return inventory


def get_problem_history(hostid: int, time_from: int, time_till: int) -> list:
    """História problémov hosta (aj vyriešených) vzniknutých v danom časovom
    okne, priamo zo Zabbix API — na rozdiel od aktívnych problémov sa nikde
    neukladá (história nepotrebuje prierezové filtre naprieč hostami ako
    dashboard, a nemá zmysel ju držať v NetBox DB navždy rastúcu).

    Filtrované podľa času VZNIKU (clock), nie podľa prekrytia s oknom —
    jednoduchšia a jednoznačná sémantika bez drahého overlap dopytu.

    event.get s value=1 vráti jeden riadok na vznik problému a jeho r_eventid
    (id "resolution" udalosti, 0 = stále aktívny) — ale nie priamo čas
    vyriešenia (r_clock nie je platné output pole event.get). Čas vyriešenia
    sa preto dotiahne druhým, dávkovým dopytom podľa r_eventid a doplní sa
    do výsledku ako 'r_clock', aby volajúci nemusel riešiť dvojfázovosť."""
    cache_key = f'{PLUGIN_NAME}:history:{hostid}:{time_from}:{time_till}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    api = get_client()
    events = api.event.get(
        hostids=[hostid],
        source=0,  # EVENT_SOURCE_TRIGGERS
        object=0,  # EVENT_OBJECT_TRIGGER
        value=1,   # riadky vzniku problému
        time_from=time_from,
        time_till=time_till,
        # objectid = triggerid, potrebné na priamy odkaz na problém (tr_events.php)
        output=['eventid', 'objectid', 'name', 'severity', 'clock', 'r_eventid',
                'acknowledged'],
        selectTags='extend',
        severities=list(range(int(get_setting('min_severity', 2)), 6)),
        sortfield=['clock'],
        sortorder='DESC',
        limit=HISTORY_LIMIT,
    )

    resolution_ids = sorted({
        e['r_eventid'] for e in events if e.get('r_eventid') not in (None, '0')
    })
    resolution_clocks = {}
    if resolution_ids:
        resolutions = api.event.get(eventids=resolution_ids, output=['eventid', 'clock'])
        resolution_clocks = {r['eventid']: r['clock'] for r in resolutions}
    for e in events:
        e['r_clock'] = resolution_clocks.get(e.get('r_eventid'), '0')

    cache.set(cache_key, events, int(get_setting('cache_ttl', 30)))
    return events
