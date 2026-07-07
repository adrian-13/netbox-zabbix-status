from django import forms

from dcim.models import Device, DeviceRole, Site
from netbox.forms import NetBoxModelFilterSetForm, NetBoxModelForm
from tenancy.models import Tenant
from utilities.forms.fields import DynamicModelChoiceField, DynamicModelMultipleChoiceField
from utilities.forms.rendering import FieldSet
from virtualization.models import VirtualMachine

from .choices import MatchMethodChoices, SeverityChoices, ZabbixHostStatusChoices
from .models import ZabbixHost, ZabbixProblem

BOOLEAN_CHOICES = (
    ('', '---------'),
    ('true', 'Áno'),
    ('false', 'Nie'),
)


class ZabbixHostAssignForm(NetBoxModelForm):
    """Ručné priradenie Zabbix hosta k zariadeniu alebo VM.

    Uloženie nastaví match_method=manual (sync ho už neprepíše); vyčistenie
    oboch polí nastaví none, takže ďalší sync skúsi automatické párovanie.
    """

    device = DynamicModelChoiceField(
        queryset=Device.objects.all(), required=False, label='Zariadenie'
    )
    virtual_machine = DynamicModelChoiceField(
        queryset=VirtualMachine.objects.all(), required=False, label='Virtuálny stroj'
    )

    fieldsets = (
        FieldSet('device', 'virtual_machine', name='Priradenie'),
    )

    class Meta:
        model = ZabbixHost
        fields = ('device', 'virtual_machine')

    def save(self, *args, **kwargs):
        self.instance.match_method = (
            MatchMethodChoices.MANUAL
            if self.instance.device or self.instance.virtual_machine
            else MatchMethodChoices.NONE
        )
        return super().save(*args, **kwargs)


class ZabbixHostFilterForm(NetBoxModelFilterSetForm):
    model = ZabbixHost
    fieldsets = (
        FieldSet('q', 'filter_id'),
        FieldSet('status', 'match_method', 'is_matched', 'has_problems', 'max_severity', name='Zabbix'),
        FieldSet('site_id', 'tenant_id', 'role_id', name='NetBox'),
    )

    status = forms.MultipleChoiceField(choices=ZabbixHostStatusChoices, required=False, label='Stav')
    match_method = forms.MultipleChoiceField(choices=MatchMethodChoices, required=False, label='Párovanie')
    is_matched = forms.ChoiceField(choices=BOOLEAN_CHOICES, required=False, label='Spárované')
    has_problems = forms.ChoiceField(choices=BOOLEAN_CHOICES, required=False, label='Má problémy')
    max_severity = forms.MultipleChoiceField(
        choices=SeverityChoices.CHOICES, required=False, label='Max. severita'
    )
    site_id = DynamicModelMultipleChoiceField(
        queryset=Site.objects.all(), required=False, label='Site'
    )
    tenant_id = DynamicModelMultipleChoiceField(
        queryset=Tenant.objects.all(), required=False, label='Tenant'
    )
    role_id = DynamicModelMultipleChoiceField(
        queryset=DeviceRole.objects.all(), required=False, label='Rola'
    )


class ZabbixProblemFilterForm(NetBoxModelFilterSetForm):
    model = ZabbixProblem
    fieldsets = (
        FieldSet('q', 'filter_id'),
        FieldSet('severity', 'acknowledged', name='Zabbix'),
        FieldSet('site_id', 'tenant_id', 'role_id', name='NetBox'),
    )

    severity = forms.MultipleChoiceField(
        choices=SeverityChoices.CHOICES, required=False, label='Severita'
    )
    acknowledged = forms.ChoiceField(choices=BOOLEAN_CHOICES, required=False, label='Acknowledged')
    site_id = DynamicModelMultipleChoiceField(
        queryset=Site.objects.all(), required=False, label='Site'
    )
    tenant_id = DynamicModelMultipleChoiceField(
        queryset=Tenant.objects.all(), required=False, label='Tenant'
    )
    role_id = DynamicModelMultipleChoiceField(
        queryset=DeviceRole.objects.all(), required=False, label='Rola'
    )
