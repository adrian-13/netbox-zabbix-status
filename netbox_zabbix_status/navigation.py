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
        ('Konzistencia', (
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:unmonitored_devices',
                link_text='Nepokryté zariadenia',
                permissions=['dcim.view_device'],
            ),
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:unmonitored_vms',
                link_text='Nepokryté VM',
                permissions=['virtualization.view_virtualmachine'],
            ),
            PluginMenuItem(
                link='plugins:netbox_zabbix_status:unmatched_hosts',
                link_text='Nespárované hosty',
                permissions=['netbox_zabbix_status.view_zabbixhost'],
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
