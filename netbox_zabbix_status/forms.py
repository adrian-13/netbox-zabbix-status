from django import forms

from dcim.models import Device, DeviceRole, Site
from netbox.forms import NetBoxModelFilterSetForm, NetBoxModelForm
from tenancy.models import Tenant
from utilities.forms.fields import DynamicModelChoiceField, DynamicModelMultipleChoiceField
from utilities.forms.rendering import FieldSet
from virtualization.models import VirtualMachine

from .choices import MatchMethodChoices, SeverityChoices, ZabbixHostStatusChoices
from .models import ZabbixConfiguration, ZabbixHost, ZabbixProblem

BOOLEAN_CHOICES = (
    ('', '---------'),
    ('true', 'Áno'),
    ('false', 'Nie'),
)


class ZabbixSettingsForm(forms.ModelForm):
    """Editácia runtime nastavení pluginu (singleton ZabbixConfiguration)."""

    strip_domains = forms.CharField(
        required=False,
        label='Odrezávané domény',
        help_text='Čiarkou oddelené doménové suffixy odrezávané pri párovaní mien, '
                  'napr. „kinet.sk, firma.local".',
    )

    class Meta:
        model = ZabbixConfiguration
        fields = (
            'matching_enabled', 'match_by_ip', 'sync_vms', 'min_severity',
            'cache_ttl', 'dashboard_matched_only', 'dashboard_refresh',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['strip_domains'].initial = ', '.join(
                self.instance.hostname_strip_domains
            )

    def save(self, *args, **kwargs):
        raw = self.cleaned_data.get('strip_domains', '')
        self.instance.hostname_strip_domains = [
            d.strip().strip('.') for d in raw.split(',') if d.strip()
        ]
        return super().save(*args, **kwargs)


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
