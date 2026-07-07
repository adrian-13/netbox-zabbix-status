from netbox.plugins import PluginTemplateExtension

from .zabbix import get_setting, get_web_url


class ZabbixHostPanel(PluginTemplateExtension):
    """Kompaktná karta so stavom monitoringu v pravom stĺpci Device/VM stránky.
    Číta výhradne z DB snapshotu — žiadne Zabbix API volanie pri renderi."""

    models = ('dcim.device', 'virtualization.virtualmachine')

    def right_page(self):
        # Runtime check — pri vypnutom párovaní panel zmizne okamžite, bez reštartu
        if not get_setting('matching_enabled', True):
            return ''
        obj = self.context['object']
        host = obj.zabbix_hosts.first()
        web_url = get_web_url()
        return self.render('netbox_zabbix_status/inc/host_panel.html', extra_context={
            'zabbix_host': host,
            'tab_url': f'{obj.get_absolute_url()}zabbix/' if host else None,
            'zabbix_dashboard_url': (
                f'{web_url}/zabbix.php?action=host.dashboard.view&hostid={host.zabbix_hostid}'
                if host and web_url else None
            ),
        })


template_extensions = (ZabbixHostPanel,)
