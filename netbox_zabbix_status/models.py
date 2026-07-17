from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from netbox.models import NetBoxModel

from .choices import (
    AvailabilityChoices,
    MatchMethodChoices,
    SeverityChoices,
    ZabbixHostStatusChoices,
)


class ZabbixConfiguration(NetBoxModel):
    """Runtime nastavenia pluginu (singleton riadok, editovateľný v UI).

    Hodnoty majú prednosť pred PLUGINS_CONFIG — env premenné slúžia ako
    default, kým sa nastavenia prvýkrát neuložia. Číta ich zabbix.get_setting(),
    takže zmeny platia okamžite, bez reštartu.

    NetBoxModel (nie plain models.Model) je zámerné: dáva zadarmo Changelog
    (kto/kedy zmenil napr. matching_enabled) cez NetBoxove ChangeLoggingMixin —
    bez toho nie je spätne dohľadateľné, kto nastavenie prepol (stalo sa raz,
    že matching_enabled ostalo vypnuté a nedalo sa zistiť prečo)."""

    sync_interval = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        verbose_name='Sync interval (min)',
        help_text='How often data is downloaded from Zabbix. The change takes effect '
                  'from the next run — no restart required (the sync job re-evaluates '
                  'its own interval).',
    )
    matching_enabled = models.BooleanField(
        default=True,
        verbose_name='Matching with NetBox',
        help_text='Disabled = pure Zabbix viewer: sync stops creating new links, '
                  'the dashboard and settings switch to an aggregated view. The '
                  '"Zabbix" panel/tab on already matched devices remains visible.',
    )
    match_by_ip = models.BooleanField(
        default=True,
        verbose_name='Also match by IP',
        help_text='Fallback matching based on an unambiguous IP address match.',
    )
    sync_vms = models.BooleanField(
        default=True,
        verbose_name='Also match virtual machines',
    )
    hostname_strip_domains = models.JSONField(
        default=list, blank=True,
        verbose_name='Stripped domains',
        help_text='Domain suffixes stripped from names during matching.',
    )
    min_severity = models.PositiveSmallIntegerField(
        choices=SeverityChoices.CHOICES,
        default=SeverityChoices.WARNING,
        verbose_name='Minimum severity',
        help_text='Problems with lower severity are neither synced nor displayed. '
                  'Takes effect on the next sync.',
    )
    include_suppressed = models.BooleanField(
        default=False,
        verbose_name='Include suppressed problems',
        help_text='Problems for hosts in a maintenance window. The Zabbix UI hides '
                  'them by default — disabled = same behavior. Takes effect on the next sync.',
    )
    cache_ttl = models.PositiveIntegerField(
        default=30,
        verbose_name='Live data cache (s)',
        help_text='How long live problems from the API are kept in cache for the device tab.',
    )
    dashboard_matched_only = models.BooleanField(
        default=True,
        verbose_name='Dashboard matched hosts only',
        help_text='Disabled = the dashboard shows all hosts from Zabbix.',
    )
    dashboard_severities = models.JSONField(
        default=list, blank=True,
        verbose_name='Severities on dashboard',
        help_text='Which severities to show in the dashboard tiles and panels. '
                  'Empty = all from the minimum severity.',
    )
    dashboard_refresh = models.PositiveIntegerField(
        default=60,
        verbose_name='Dashboard auto-refresh (s)',
        help_text='0 = no automatic refresh.',
    )
    site_id_tag_key = models.CharField(
        max_length=64,
        default='nbx_siteid',
        blank=True,
        verbose_name='Tag for Site ID',
        help_text=(
            'Zabbix host tag key whose value is the NetBox Site ID (e.g. the tag '
            '"nbx_siteid" with value "63" means Site pk=63). Used to prefill the '
            'Site when importing an unmatched host, takes precedence over the '
            'host group-based guess. Empty = disabled.'
        ),
    )
    visible_tag_keys = models.JSONField(
        default=list, blank=True,
        verbose_name='Displayed Zabbix tags',
        help_text=(
            'Which Zabbix tag keys to display in the "Zabbix tags" column on the '
            'Hosts list (set directly there, via the gear icon — not here). '
            'Empty = show all.'
        ),
    )

    class Meta:
        verbose_name = 'Zabbix settings'
        verbose_name_plural = 'Zabbix settings'

    def __str__(self):
        return 'Zabbix settings'

    def get_absolute_url(self):
        return reverse('plugins:netbox_zabbix_status:settings')

    @classmethod
    def get_solo(cls):
        """Vráti (a pri prvom použití založí) singleton riadok, seedovaný
        z aktuálnej PLUGINS_CONFIG konfigurácie."""
        obj = cls.objects.first()
        if obj is None:
            from .zabbix import get_config
            cfg = get_config()
            obj = cls.objects.create(
                sync_interval=int(cfg.get('sync_interval', 5)),
                matching_enabled=bool(cfg.get('matching_enabled', True)),
                match_by_ip=bool(cfg.get('match_by_ip', True)),
                sync_vms=bool(cfg.get('sync_vms', True)),
                hostname_strip_domains=list(cfg.get('hostname_strip_domains', [])),
                min_severity=int(cfg.get('min_severity', 2)),
                include_suppressed=bool(cfg.get('include_suppressed', False)),
                cache_ttl=int(cfg.get('cache_ttl', 30)),
                dashboard_matched_only=bool(cfg.get('dashboard_matched_only', True)),
                dashboard_severities=list(cfg.get('dashboard_severities', [])),
                dashboard_refresh=int(cfg.get('dashboard_refresh', 60)),
                site_id_tag_key=str(cfg.get('site_id_tag_key', 'nbx_siteid')),
                visible_tag_keys=list(cfg.get('visible_tag_keys', [])),
            )
        return obj


class ZabbixHost(NetBoxModel):
    """Snapshot Zabbix hosta, plnený background sync jobom (read-only voči Zabbixu).

    Väzba na NetBox je cez explicitné nullable FK (device / virtual_machine) namiesto
    GenericForeignKey, aby sa dalo v ORM filtrovať cez device__site, device__tenant atď.
    Nespárovaný host má oba FK NULL.
    """

    zabbix_hostid = models.PositiveBigIntegerField(unique=True)
    name = models.CharField(max_length=200, help_text='Technical name of the host in Zabbix')
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
        help_text='Availability of the active agent (Zabbix >= 6.2)',
    )
    proxy_name = models.CharField(max_length=200, blank=True)
    host_groups = models.JSONField(default=list, blank=True)
    templates = models.JSONField(default=list, blank=True)
    zabbix_tags = models.JSONField(
        default=list, blank=True,
        help_text='Zabbix host tags (key/value) — source e.g. for nbx_siteid during import.',
    )
    interfaces = models.JSONField(
        default=list, blank=True,
        help_text='Zabbix interfaces (type, ip, dns, port) — source for IP matching',
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
            # 1:1 párovanie — jedno Device/VM smie byť cieľom NAJVIAC jedného
            # ZabbixHost záznamu naraz (opačný smer, teda jeden ZabbixHost ->
            # najviac jedno Device/VM, je už daný obyčajným FK). Podmienené
            # (nie plain unique), lebo NULL/NULL (nespárované hosty) sú úplne
            # bežné a nesmú medzi sebou kolidovať.
            models.UniqueConstraint(
                fields=['device'],
                condition=Q(device__isnull=False),
                name='%(app_label)s_%(class)s_unique_device',
            ),
            models.UniqueConstraint(
                fields=['virtual_machine'],
                condition=Q(virtual_machine__isnull=False),
                name='%(app_label)s_%(class)s_unique_virtual_machine',
            ),
        )

    def __str__(self):
        return self.visible_name or self.name

    def clean(self):
        super().clean()
        if self.device and self.virtual_machine:
            raise ValidationError(
                'A Zabbix host can be assigned to either a device or a VM, not both.'
            )

    def get_absolute_url(self):
        return reverse('plugins:netbox_zabbix_status:zabbixhost', args=[self.pk])

    def get_zabbix_url(self):
        """Priamy odkaz na dashboard tohto hosta v Zabbixe (rovnaký cieľ ako
        tlačidlo „Dashboard" na detaile hosta a v paneli na Device/VM stránke)."""
        from .zabbix import get_web_url
        web_url = get_web_url()
        if not web_url:
            return None
        return f'{web_url}/zabbix.php?action=host.dashboard.view&hostid={self.zabbix_hostid}'

    @property
    def assigned_object(self):
        return self.device or self.virtual_machine

    @property
    def site(self):
        obj = self.assigned_object
        return getattr(obj, 'site', None) if obj else None

    @property
    def display_tags(self):
        """Zabbix tagy filtrované podľa ZabbixConfiguration.visible_tag_keys
        (nastaviteľné cez gear dropdown v controls zoznamu Hostov) — prázdny
        whitelist znamená zobraziť všetky tagy (pôvodné správanie)."""
        from .zabbix import get_setting
        visible = get_setting('visible_tag_keys', []) or []
        if not visible:
            return self.zabbix_tags
        return [t for t in self.zabbix_tags if t.get('tag') in visible]

    def get_status_color(self):
        return ZabbixHostStatusChoices.colors.get(self.status)

    def get_match_method_color(self):
        return MatchMethodChoices.colors.get(self.match_method)

    def get_max_severity_color(self):
        return SeverityChoices.get_color(self.max_severity)

    def get_agent_available_color(self):
        return AvailabilityChoices.colors.get(self.agent_available)

    def get_snmp_available_color(self):
        return AvailabilityChoices.colors.get(self.snmp_available)

    def get_ipmi_available_color(self):
        return AvailabilityChoices.colors.get(self.ipmi_available)

    def get_jmx_available_color(self):
        return AvailabilityChoices.colors.get(self.jmx_available)

    def get_active_available_color(self):
        return AvailabilityChoices.colors.get(self.active_available)


class ZabbixProblem(NetBoxModel):
    """Aktívny Zabbix problém; pri každom synce sa množina nahrádza celá."""

    host = models.ForeignKey(
        to=ZabbixHost,
        on_delete=models.CASCADE,
        related_name='problems',
    )
    zabbix_eventid = models.PositiveBigIntegerField(unique=True)
    zabbix_triggerid = models.PositiveBigIntegerField(
        null=True, blank=True,
        help_text='Trigger ID in Zabbix — together with eventid forms a direct link '
                  'to the problem (tr_events.php). Empty for records predating this '
                  'field, filled in on the next sync.',
    )
    name = models.CharField(max_length=500)
    severity = models.PositiveSmallIntegerField(
        choices=SeverityChoices.CHOICES,
        default=SeverityChoices.NOT_CLASSIFIED,
    )
    acknowledged = models.BooleanField(default=False)
    suppressed = models.BooleanField(
        default=False,
        help_text='Problem for a host in a maintenance window (suppressed by Zabbix)',
    )
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

    def get_absolute_url(self):
        # Problémy nemajú detail view — odkazuje sa na zoznam
        return reverse('plugins:netbox_zabbix_status:zabbixproblem_list')

    def get_severity_color(self):
        return SeverityChoices.get_color(self.severity)

    def get_zabbix_url(self):
        """Priamy odkaz na tento konkrétny problém v Zabbixe (tr_events.php —
        rovnaký formát, aký generujú aj vstavané notifikačné makrá {EVENT.URL}).
        None, ak chýba web_url alebo triggerid (staršie záznamy pred synce)."""
        from .zabbix import get_web_url
        web_url = get_web_url()
        if not web_url or not self.zabbix_triggerid:
            return None
        return f'{web_url}/tr_events.php?triggerid={self.zabbix_triggerid}&eventid={self.zabbix_eventid}'
