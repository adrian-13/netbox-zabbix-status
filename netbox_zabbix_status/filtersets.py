import django_filters
from django.db.models import Q

from dcim.models import Device, DeviceRole, Site
from netbox.filtersets import NetBoxModelFilterSet
from tenancy.models import Tenant
from virtualization.models import VirtualMachine

from .choices import (
    AvailabilityChoices,
    MatchMethodChoices,
    SeverityChoices,
    ZabbixHostStatusChoices,
)
from .models import ZabbixHost, ZabbixProblem


class ZabbixHostFilterSet(NetBoxModelFilterSet):
    status = django_filters.MultipleChoiceFilter(choices=ZabbixHostStatusChoices)
    match_method = django_filters.MultipleChoiceFilter(choices=MatchMethodChoices)
    agent_available = django_filters.MultipleChoiceFilter(choices=AvailabilityChoices)
    snmp_available = django_filters.MultipleChoiceFilter(choices=AvailabilityChoices)
    is_matched = django_filters.BooleanFilter(method='filter_is_matched', label='Spárované')
    has_problems = django_filters.BooleanFilter(method='filter_has_problems', label='Má problémy')
    max_severity = django_filters.MultipleChoiceFilter(choices=SeverityChoices.CHOICES)
    device_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Device.objects.all(), label='Zariadenie (ID)'
    )
    virtual_machine_id = django_filters.ModelMultipleChoiceFilter(
        queryset=VirtualMachine.objects.all(), label='VM (ID)'
    )
    site_id = django_filters.ModelMultipleChoiceFilter(
        method='filter_site', queryset=Site.objects.all(), label='Site (ID)'
    )
    tenant_id = django_filters.ModelMultipleChoiceFilter(
        method='filter_tenant', queryset=Tenant.objects.all(), label='Tenant (ID)'
    )
    role_id = django_filters.ModelMultipleChoiceFilter(
        method='filter_role', queryset=DeviceRole.objects.all(), label='Rola (ID)'
    )

    class Meta:
        model = ZabbixHost
        fields = ('id', 'zabbix_hostid', 'in_maintenance', 'proxy_name')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value)
            | Q(visible_name__icontains=value)
            | Q(proxy_name__icontains=value)
        )

    def filter_is_matched(self, queryset, name, value):
        condition = Q(device__isnull=True) & Q(virtual_machine__isnull=True)
        return queryset.exclude(condition) if value else queryset.filter(condition)

    def filter_has_problems(self, queryset, name, value):
        return queryset.filter(problem_count__gt=0) if value else queryset.filter(problem_count=0)

    def filter_site(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(device__site__in=value) | Q(virtual_machine__site__in=value)
        )

    def filter_tenant(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(device__tenant__in=value) | Q(virtual_machine__tenant__in=value)
        )

    def filter_role(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(device__role__in=value) | Q(virtual_machine__role__in=value)
        )


class ZabbixProblemFilterSet(NetBoxModelFilterSet):
    severity = django_filters.MultipleChoiceFilter(choices=SeverityChoices.CHOICES)
    acknowledged = django_filters.BooleanFilter()
    suppressed = django_filters.BooleanFilter()
    host_id = django_filters.ModelMultipleChoiceFilter(
        queryset=ZabbixHost.objects.all(), label='Zabbix host (ID)'
    )
    device_id = django_filters.ModelMultipleChoiceFilter(
        field_name='host__device', queryset=Device.objects.all(), label='Zariadenie (ID)'
    )
    virtual_machine_id = django_filters.ModelMultipleChoiceFilter(
        field_name='host__virtual_machine', queryset=VirtualMachine.objects.all(), label='VM (ID)'
    )
    site_id = django_filters.ModelMultipleChoiceFilter(
        method='filter_site', queryset=Site.objects.all(), label='Site (ID)'
    )
    tenant_id = django_filters.ModelMultipleChoiceFilter(
        method='filter_tenant', queryset=Tenant.objects.all(), label='Tenant (ID)'
    )
    role_id = django_filters.ModelMultipleChoiceFilter(
        method='filter_role', queryset=DeviceRole.objects.all(), label='Rola (ID)'
    )

    class Meta:
        model = ZabbixProblem
        fields = ('id', 'zabbix_eventid')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(opdata__icontains=value)
        )

    def filter_site(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(host__device__site__in=value) | Q(host__virtual_machine__site__in=value)
        )

    def filter_tenant(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(host__device__tenant__in=value) | Q(host__virtual_machine__tenant__in=value)
        )

    def filter_role(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(host__device__role__in=value) | Q(host__virtual_machine__role__in=value)
        )
