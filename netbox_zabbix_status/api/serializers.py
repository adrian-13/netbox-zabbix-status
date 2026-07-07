from dcim.api.serializers import DeviceSerializer
from netbox.api.serializers import NetBoxModelSerializer
from virtualization.api.serializers import VirtualMachineSerializer

from ..models import ZabbixHost, ZabbixProblem


class ZabbixHostSerializer(NetBoxModelSerializer):
    device = DeviceSerializer(nested=True, read_only=True, allow_null=True)
    virtual_machine = VirtualMachineSerializer(nested=True, read_only=True, allow_null=True)

    class Meta:
        model = ZabbixHost
        fields = (
            'id', 'url', 'display', 'zabbix_hostid', 'name', 'visible_name',
            'device', 'virtual_machine', 'status', 'in_maintenance',
            'agent_available', 'snmp_available', 'ipmi_available', 'jmx_available',
            'active_available', 'proxy_name', 'host_groups', 'templates',
            'interfaces', 'match_method', 'problem_count', 'max_severity',
            'last_synced', 'tags', 'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'zabbix_hostid', 'name', 'visible_name')


class ZabbixProblemSerializer(NetBoxModelSerializer):
    host = ZabbixHostSerializer(nested=True, read_only=True)

    class Meta:
        model = ZabbixProblem
        fields = (
            'id', 'url', 'display', 'zabbix_eventid', 'host', 'name', 'severity',
            'acknowledged', 'suppressed', 'started', 'opdata', 'zabbix_tags',
            'tags', 'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'zabbix_eventid', 'name', 'severity')
