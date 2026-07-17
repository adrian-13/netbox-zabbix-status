import django_filters
from django.db.models import Exists, OuterRef, Q

from dcim.filtersets import DeviceFilterSet
from dcim.models import Device, DeviceRole, Site
from netbox.filtersets import NetBoxModelFilterSet
from tenancy.models import Tenant
from virtualization.filtersets import VirtualMachineFilterSet
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
    is_matched = django_filters.BooleanFilter(method='filter_is_matched', label='Matched')
    has_problems = django_filters.BooleanFilter(method='filter_has_problems', label='Has problems')
    max_severity = django_filters.MultipleChoiceFilter(choices=SeverityChoices.CHOICES)
    device_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Device.objects.all(), label='Device (ID)'
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
        method='filter_role', queryset=DeviceRole.objects.all(), label='Role (ID)'
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
        field_name='host__device', queryset=Device.objects.all(), label='Device (ID)'
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
        method='filter_role', queryset=DeviceRole.objects.all(), label='Role (ID)'
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


def _filter_device_zabbix_matched(queryset, name, value):
    """Rovnaká `Exists()` logika ako `_order_zabbix_status` v tables.py
    (korelovaný subquery, nie join — bezpečné aj pri zariadení s viacerými
    ZabbixHost záznamami, žiadne duplicitné riadky vo výsledku)."""
    condition = Exists(ZabbixHost.objects.filter(device=OuterRef('pk')))
    return queryset.filter(condition) if value else queryset.exclude(condition)


# Filter „Spárované so Zabbixom" na natívnej dcim.DeviceFilterSet — párovací
# stĺpec „Zabbix" v tables.py potrebuje aj filter, nie len zobrazenie/triedenie.
# NetBox NEMÁ oficiálne API na pridanie filtra do core FilterSetu (na rozdiel
# od register_table_column() pre stĺpce) — jediný funkčný spôsob je priamo
# doplniť DeviceFilterSet.declared_filters. DÔLEŽITÉ: NIE `base_filters` —
# NetBoxov vlastný BaseFilterSet.__init__() (netbox/filtersets.py) prepisuje
# `self.base_filters = self.__class__.get_filters()` pri KAŽDEJ inštancii
# (kvôli inému, staršiemu bugfixu #9231), čím by zahodil čokoľvek pridané do
# `base_filters` po definícii triedy. `get_filters()` ale číta z
# `declared_filters` (nastavené raz metaclassom pri definícii triedy, mutáciou
# toho istého dict objektu to prežije) — overené priamo (base_filters:
# mutácia sa strácala, declared_filters: fungovalo cez skutočný HTTP request).
# Zodpovedajúce pole vo FilterForme je vo .forms (rovnaké meno 'zabbix_matched').
DeviceFilterSet.declared_filters['zabbix_matched'] = django_filters.BooleanFilter(
    method=_filter_device_zabbix_matched,
    label='Matched with Zabbix',
)


def _filter_vm_zabbix_matched(queryset, name, value):
    """Rovnaká `Exists()` logika ako `_filter_device_zabbix_matched`
    vyššie, len na `virtual_machine` FK namiesto `device`."""
    condition = Exists(ZabbixHost.objects.filter(virtual_machine=OuterRef('pk')))
    return queryset.filter(condition) if value else queryset.exclude(condition)


# Rovnaký vzor ako DeviceFilterSet vyššie — natívny VirtualMachineFilterSet
# dostáva identický filter „zabbix_matched". Zodpovedajúce pole vo FilterForme
# je v .forms (rovnaké meno 'zabbix_matched').
VirtualMachineFilterSet.declared_filters['zabbix_matched'] = django_filters.BooleanFilter(
    method=_filter_vm_zabbix_matched,
    label='Matched with Zabbix',
)
