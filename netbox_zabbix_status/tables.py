import django_tables2 as tables

from netbox.tables import NetBoxTable, columns

from .models import ZabbixHost, ZabbixProblem

SEVERITY_BADGE = """
{% load helpers %}
{% if value is not None %}
  {% badge record.get_max_severity_display bg_color=record.get_max_severity_color %}
{% else %}
  {{ ''|placeholder }}
{% endif %}
"""

PROBLEM_SEVERITY_BADGE = """
{% load helpers %}
{% badge record.get_severity_display bg_color=record.get_severity_color %}
"""


class ZabbixHostTable(NetBoxTable):
    name = tables.Column(linkify=True, verbose_name='Meno')
    visible_name = tables.Column(verbose_name='Viditeľné meno')
    device = tables.Column(linkify=True)
    virtual_machine = tables.Column(linkify=True, verbose_name='VM')
    site = tables.Column(accessor='site', linkify=True, orderable=False)
    status = columns.ChoiceFieldColumn(verbose_name='Stav')
    match_method = columns.ChoiceFieldColumn(verbose_name='Párovanie')
    agent_available = columns.ChoiceFieldColumn(verbose_name='Agent')
    snmp_available = columns.ChoiceFieldColumn(verbose_name='SNMP')
    problem_count = tables.Column(verbose_name='Problémy')
    max_severity = tables.TemplateColumn(
        template_code=SEVERITY_BADGE, verbose_name='Max. severita', order_by='max_severity'
    )
    in_maintenance = columns.BooleanColumn(verbose_name='Maintenance')
    last_synced = columns.DateTimeColumn(verbose_name='Sync')
    tags = columns.TagColumn(url_name='plugins:netbox_zabbix_status:zabbixhost_list')
    # Edit = ručné priradenie k zariadeniu/VM; ostatné dáta sú synced (read-only)
    actions = columns.ActionsColumn(actions=('edit',))

    class Meta(NetBoxTable.Meta):
        model = ZabbixHost
        fields = (
            'pk', 'id', 'name', 'visible_name', 'zabbix_hostid', 'device',
            'virtual_machine', 'site', 'status', 'match_method',
            'agent_available', 'snmp_available', 'ipmi_available', 'jmx_available',
            'active_available', 'in_maintenance', 'proxy_name', 'problem_count',
            'max_severity', 'last_synced', 'tags',
        )
        default_columns = (
            'name', 'device', 'virtual_machine', 'status', 'match_method',
            'problem_count', 'max_severity', 'last_synced',
        )


class ZabbixProblemTable(NetBoxTable):
    severity = tables.TemplateColumn(
        template_code=PROBLEM_SEVERITY_BADGE, verbose_name='Severita', order_by='severity'
    )
    name = tables.Column(verbose_name='Problém')
    host = tables.Column(linkify=True)
    device = tables.Column(accessor='host__device', linkify=True, verbose_name='Zariadenie')
    virtual_machine = tables.Column(accessor='host__virtual_machine', linkify=True, verbose_name='VM')
    site = tables.Column(accessor='host__site', linkify=True, orderable=False)
    acknowledged = columns.BooleanColumn(verbose_name='Ack')
    started = columns.DateTimeColumn(verbose_name='Od')
    opdata = tables.Column(verbose_name='Operational data')
    actions = columns.ActionsColumn(actions=())

    class Meta(NetBoxTable.Meta):
        model = ZabbixProblem
        fields = (
            'pk', 'id', 'severity', 'name', 'host', 'device', 'virtual_machine',
            'site', 'acknowledged', 'started', 'opdata',
        )
        default_columns = (
            'severity', 'name', 'device', 'virtual_machine', 'site',
            'acknowledged', 'started',
        )
