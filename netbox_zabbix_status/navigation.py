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
                link_text='Hosty',
                permissions=['netbox_zabbix_status.view_zabbixhost'],
            ),
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:zabbixproblem_list',
                link_text='Problémy',
                permissions=['netbox_zabbix_status.view_zabbixproblem'],
            ),
        )),
        ('Konfigurácia', (
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:settings',
                link_text='Nastavenia',
                permissions=['netbox_zabbix_status.change_zabbixconfiguration'],
            ),
        )),
    ),
)
