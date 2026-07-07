from netbox.plugins import PluginMenu, PluginMenuItem

from .zabbix import get_config

_groups = [
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
]

# Konzistenčné pohľady majú zmysel len pri zapnutom párovaní s NetBoxom
if get_config().get('matching_enabled', True):
    _groups.append(
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
        ))
    )

menu = PluginMenu(
    label='Zabbix',
    icon_class='mdi mdi-radar',
    groups=tuple(_groups),
)
