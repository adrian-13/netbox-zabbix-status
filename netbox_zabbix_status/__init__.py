from netbox.plugins import PluginConfig

__version__ = '0.1.0'


class ZabbixStatusConfig(PluginConfig):
    name = 'netbox_zabbix_status'
    verbose_name = 'Zabbix Status'
    description = 'Read-only zobrazenie stavu Zabbix monitoringu v NetBoxe'
    version = __version__
    base_url = 'zabbix-status'
    min_version = '4.6.0'
    # api_url/api_token zámerne nie sú required_settings — plugin sa má načítať
    # aj nenakonfigurovaný; chýbajúca konfigurácia sa hlási až pri použití API.
    default_settings = {
        'api_url': '',
        'api_token': '',
        'web_url': '',
        'verify_ssl': True,
        'sync_interval': 5,
        'cache_ttl': 30,
        'min_severity': 2,
        'hostname_strip_domains': [],
        'match_by_ip': True,
        'sync_vms': True,
    }

    def ready(self):
        super().ready()
        # Explicitné importy registrujú system job, search index a dashboard widget
        from . import jobs, search, widgets  # noqa: F401


config = ZabbixStatusConfig
