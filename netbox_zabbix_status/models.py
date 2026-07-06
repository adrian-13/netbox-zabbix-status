from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from netbox.models import NetBoxModel

from .choices import (
    AvailabilityChoices,
    MatchMethodChoices,
    SeverityChoices,
    ZabbixHostStatusChoices,
)


class ZabbixHost(NetBoxModel):
    """Snapshot Zabbix hosta, plnený background sync jobom (read-only voči Zabbixu).

    Väzba na NetBox je cez explicitné nullable FK (device / virtual_machine) namiesto
    GenericForeignKey, aby sa dalo v ORM filtrovať cez device__site, device__tenant atď.
    Nespárovaný host má oba FK NULL.
    """

    zabbix_hostid = models.PositiveBigIntegerField(unique=True)
    name = models.CharField(max_length=200, help_text='Technické meno hosta v Zabbixe')
    visible_name = models.CharField(max_length=200, blank=True)
    device = models.ForeignKey(
        to='dcim.Device',
        on_delete=models.SET_NULL,
        related_name='zabbix_hosts',
        null=True,
        blank=True,
    )
    virtual_machine = models.ForeignKey(
        to='virtualization.VirtualMachine',
        on_delete=models.SET_NULL,
        related_name='zabbix_hosts',
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=ZabbixHostStatusChoices,
        default=ZabbixHostStatusChoices.ENABLED,
    )
    in_maintenance = models.BooleanField(default=False)
    agent_available = models.CharField(
        max_length=10, choices=AvailabilityChoices, default=AvailabilityChoices.UNKNOWN
    )
    snmp_available = models.CharField(
        max_length=10, choices=AvailabilityChoices, default=AvailabilityChoices.UNKNOWN
    )
    ipmi_available = models.CharField(
        max_length=10, choices=AvailabilityChoices, default=AvailabilityChoices.UNKNOWN
    )
    jmx_available = models.CharField(
        max_length=10, choices=AvailabilityChoices, default=AvailabilityChoices.UNKNOWN
    )
    active_available = models.CharField(
        max_length=10, choices=AvailabilityChoices, default=AvailabilityChoices.UNKNOWN,
        help_text='Dostupnosť aktívneho agenta (Zabbix >= 6.2)',
    )
    proxy_name = models.CharField(max_length=200, blank=True)
    host_groups = models.JSONField(default=list, blank=True)
    templates = models.JSONField(default=list, blank=True)
    interfaces = models.JSONField(
        default=list, blank=True,
        help_text='Zabbix interfejsy (typ, ip, dns, port) — zdroj pre IP párovanie',
    )
    match_method = models.CharField(
        max_length=20,
        choices=MatchMethodChoices,
        default=MatchMethodChoices.NONE,
    )
    # Denormalizované pri synce, aby list view nemusel agregovať problémy
    problem_count = models.PositiveIntegerField(default=0)
    max_severity = models.PositiveSmallIntegerField(
        choices=SeverityChoices.CHOICES, null=True, blank=True
    )
    last_synced = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('name',)
        verbose_name = 'Zabbix host'
        verbose_name_plural = 'Zabbix hosts'
        constraints = (
            models.CheckConstraint(
                condition=Q(device__isnull=True) | Q(virtual_machine__isnull=True),
                name='%(app_label)s_%(class)s_single_assignment',
            ),
        )

    def __str__(self):
        return self.visible_name or self.name

    def clean(self):
        super().clean()
        if self.device and self.virtual_machine:
            raise ValidationError(
                'Zabbix host môže byť priradený buď k zariadeniu, alebo k VM, nie k obom.'
            )

    @property
    def assigned_object(self):
        return self.device or self.virtual_machine

    def get_status_color(self):
        return ZabbixHostStatusChoices.colors.get(self.status)

    def get_match_method_color(self):
        return MatchMethodChoices.colors.get(self.match_method)

    def get_max_severity_color(self):
        return SeverityChoices.get_color(self.max_severity)


class ZabbixProblem(NetBoxModel):
    """Aktívny Zabbix problém; pri každom synce sa množina nahrádza celá."""

    host = models.ForeignKey(
        to=ZabbixHost,
        on_delete=models.CASCADE,
        related_name='problems',
    )
    zabbix_eventid = models.PositiveBigIntegerField(unique=True)
    name = models.CharField(max_length=500)
    severity = models.PositiveSmallIntegerField(
        choices=SeverityChoices.CHOICES,
        default=SeverityChoices.NOT_CLASSIFIED,
    )
    acknowledged = models.BooleanField(default=False)
    started = models.DateTimeField(null=True, blank=True)
    opdata = models.CharField(max_length=500, blank=True)
    # 'tags' koliduje s NetBoxModel.tags (TaggableManager), preto zabbix_tags
    zabbix_tags = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ('-severity', '-started')
        verbose_name = 'Zabbix problem'
        verbose_name_plural = 'Zabbix problems'

    def __str__(self):
        return self.name

    def get_severity_color(self):
        return SeverityChoices.get_color(self.severity)
