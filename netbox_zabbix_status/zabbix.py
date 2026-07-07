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
    cfg = get_config()
    cache_key = f'{PLUGIN_NAME}:problems:{hostid}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    api = get_client()
    problems = api.problem.get(
        hostids=[hostid],
        output=['eventid', 'name', 'severity', 'acknowledged', 'clock', 'opdata'],
        selectTags='extend',
        severities=list(range(int(cfg.get('min_severity', 2)), 6)),
        recent=False,
        sortfield='eventid',
    )
    cache.set(cache_key, problems, int(cfg.get('cache_ttl', 30)))
    return problems
