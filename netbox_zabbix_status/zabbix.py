"""Tenký wrapper nad zabbix_utils klientom.

Konfigurácia sa číta z PLUGINS_CONFIG['netbox_zabbix_status']. Klient sa vytvára
per-použitie — auth cez API token je bezstavový, netreba login/logout session.
"""
from django.conf import settings
from django.core.cache import cache

from zabbix_utils import ZabbixAPI

PLUGIN_NAME = 'netbox_zabbix_status'


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
        output=['eventid', 'name', 'severity', 'acknowledged', 'suppressed',
                'clock', 'opdata'],
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
