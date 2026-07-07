from netbox.search import SearchIndex, register_search

from .models import ZabbixHost


@register_search
class ZabbixHostIndex(SearchIndex):
    model = ZabbixHost
    fields = (
        ('name', 100),
        ('visible_name', 110),
        ('proxy_name', 300),
    )
    display_attrs = ('device', 'virtual_machine', 'status', 'match_method')
