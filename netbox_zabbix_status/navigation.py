from netbox.plugins import PluginMenu, PluginMenuItem

menu = PluginMenu(
    label='Zabbix',
    icon_class='mdi mdi-radar',
    groups=(
        ('Monitoring', (
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:dashboard',
                link_text='Dashboard',
                permissions=['netbox_zabbix_status.view_zabbixhost'],
            ),
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:zabbixhost_list',
                link_text='Hosts',
                permissions=['netbox_zabbix_status.view_zabbixhost'],
            ),
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:zabbixproblem_list',
                link_text='Problems',
                permissions=['netbox_zabbix_status.view_zabbixproblem'],
            ),
        )),
        ('Configuration', (
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:settings',
                link_text='Settings',
                permissions=['netbox_zabbix_status.change_zabbixconfiguration'],
            ),
        )),
    ),
)
