from django import forms

from dcim.models import DeviceRole, Site
from netbox.forms import NetBoxModelFilterSetForm
from tenancy.models import Tenant
from utilities.forms.fields import DynamicModelMultipleChoiceField
from utilities.forms.rendering import FieldSet

from .choices import MatchMethodChoices, SeverityChoices, ZabbixHostStatusChoices
from .models import ZabbixHost, ZabbixProblem

BOOLEAN_CHOICES = (
    ('', '---------'),
    ('true', 'Áno'),
    ('false', 'Nie'),
)


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
