import django_tables2 as tables

from netbox.tables import NetBoxTable, columns

from .models import ZabbixHost, ZabbixProblem
from .zabbix import get_setting

# Číta sa pri štarte (definícia tabuliek) — zmena nastavenia v UI sa na default
# stĺpcoch prejaví po reštarte; používateľ si stĺpce vie prepnúť aj sám.
_MATCHING_ENABLED = get_setting('matching_enabled', True)

if _MATCHING_ENABLED:
    _HOST_DEFAULT_COLUMNS = (
        'name', 'device', 'virtual_machine', 'status', 'match_method',
        'problem_count', 'max_severity', 'last_synced', 'zabbix_tags', 'zabbix_link',
    )
    # 'host' (meno zo Zabbixu) je v defaulte — device/VM/site sú prázdne
    # pri problémoch na nespárovaných hostoch a riadok by nemal identifikáciu
    _PROBLEM_DEFAULT_COLUMNS = (
        'severity', 'name', 'host', 'device', 'site',
        'acknowledged', 'started', 'zabbix_link',
    )
else:
    # Čistý Zabbix viewer — NetBox stĺpce sú default skryté (dajú sa zapnúť ručne)
    _HOST_DEFAULT_COLUMNS = (
        'name', 'visible_name', 'status', 'agent_available', 'snmp_available',
        'problem_count', 'max_severity', 'last_synced', 'zabbix_tags', 'zabbix_link',
    )
    _PROBLEM_DEFAULT_COLUMNS = (
        'severity', 'name', 'host', 'acknowledged', 'started', 'opdata', 'zabbix_link',
    )

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

ZABBIX_LINK = """
{% if record.get_zabbix_url %}
  <a href="{{ record.get_zabbix_url }}" target="_blank" title="Otvoriť v Zabbixe">
    <i class="mdi mdi-open-in-new"></i>
  </a>
{% endif %}
"""

IMPORT_LINK = """
{% if not record.assigned_object %}
  {% if perms.dcim.add_device or perms.virtualization.add_virtualmachine %}
    <a class="btn btn-sm btn-primary"
       href="{% url 'plugins:netbox_zabbix_status:zabbixhost_import' pk=record.pk %}"
       aria-label="Importovať do NetBoxu ako zariadenie alebo VM"
       title="Importovať do NetBoxu ako zariadenie alebo VM">
      <i class="mdi mdi-plus"></i>
    </a>
  {% endif %}
{% endif %}
"""

ZABBIX_TAGS = """
{% load helpers %}
{% for t in value %}
  <span class="badge text-bg-secondary me-1">{{ t.tag }}{% if t.value %}: {{ t.value }}{% endif %}</span>
{% empty %}
  {{ ''|placeholder }}
{% endfor %}
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
    zabbix_tags = tables.TemplateColumn(
        template_code=ZABBIX_TAGS, verbose_name='Zabbix tagy', orderable=False
    )
    zabbix_link = tables.TemplateColumn(
        template_code=ZABBIX_LINK, verbose_name='', orderable=False
    )
    # Edit = ručné priradenie k zariadeniu/VM; ostatné dáta sú synced (read-only).
    # Import „+" ide ako extra_buttons hneď vedľa edit tlačidla (nie samostatný
    # stĺpec) — rovnaký vzor ako VLANGROUP_BUTTONS v NetBox core.
    actions = columns.ActionsColumn(actions=('edit',), extra_buttons=IMPORT_LINK)

    class Meta(NetBoxTable.Meta):
        model = ZabbixHost
        fields = (
            'pk', 'id', 'name', 'visible_name', 'zabbix_hostid', 'device',
            'virtual_machine', 'site', 'status', 'match_method',
            'agent_available', 'snmp_available', 'ipmi_available', 'jmx_available',
            'active_available', 'in_maintenance', 'proxy_name', 'problem_count',
            'max_severity', 'last_synced', 'tags', 'zabbix_tags', 'zabbix_link',
        )
        default_columns = _HOST_DEFAULT_COLUMNS


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
    suppressed = columns.BooleanColumn(verbose_name='Suppressed')
    started = columns.DateTimeColumn(verbose_name='Od')
    opdata = tables.Column(verbose_name='Operational data')
    zabbix_link = tables.TemplateColumn(
        template_code=ZABBIX_LINK, verbose_name='', orderable=False
    )
    actions = columns.ActionsColumn(actions=())

    class Meta(NetBoxTable.Meta):
        model = ZabbixProblem
        fields = (
            'pk', 'id', 'severity', 'name', 'host', 'device', 'virtual_machine',
            'site', 'acknowledged', 'suppressed', 'started', 'opdata', 'zabbix_link',
        )
        default_columns = _PROBLEM_DEFAULT_COLUMNS
