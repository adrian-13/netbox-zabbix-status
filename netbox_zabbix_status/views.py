from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import View

from dcim.forms import DeviceForm, InterfaceForm
from dcim.models import Device, Site
from ipam.forms import IPAddressForm
from netbox.views import generic
from utilities.views import ViewTab, register_model_view
from virtualization.forms import VirtualMachineForm, VMInterfaceForm
from virtualization.models import VirtualMachine

from .choices import AvailabilityChoices, SeverityChoices
from .filtersets import ZabbixHostFilterSet, ZabbixProblemFilterSet
from .forms import (
    ZabbixHostAssignForm,
    ZabbixHostFilterForm,
    ZabbixProblemFilterForm,
    ZabbixSettingsForm,
)
from .models import ZabbixConfiguration, ZabbixHost, ZabbixProblem
from .sync import run_sync
from .tables import ZabbixHostTable, ZabbixProblemTable
from .zabbix import (
    HISTORY_LIMIT,
    ZabbixConfigError,
    get_config,
    get_host_import_hints,
    get_live_problems,
    get_problem_history,
    get_setting,
    get_web_url,
)

SEVERITY_LABELS = dict(SeverityChoices.CHOICES)

# História problémov na device tabe: rýchle voliteľné rozsahy + vlastný rozsah.
# Filtrované podľa času VZNIKU problému (nie prekrytia s oknom) — jednoduchá,
# jednoznačná sémantika bez drahého overlap dopytu na históriu celého hosta.
HISTORY_RANGE_CHOICES = (
    ('1h', '1 h'),
    ('6h', '6 h'),
    ('24h', '24 h'),
    ('7d', '7 dní'),
    ('30d', '30 dní'),
)
HISTORY_RANGE_DELTAS = {
    '1h': timedelta(hours=1),
    '6h': timedelta(hours=6),
    '24h': timedelta(hours=24),
    '7d': timedelta(days=7),
    '30d': timedelta(days=30),
}
DEFAULT_HISTORY_RANGE = '24h'


def _zabbix_tab_badge(instance):
    """Badge = počet problémov ako string ('0' je truthy, takže tab zostane
    viditeľný aj bez problémov); None pre nespárované objekty tab skryje.
    Viditeľnosť závisí výhradne od existencie spárovaného ZabbixHost —
    matching_enabled tu nehrá žiadnu rolu (ovplyvňuje len sync job a
    agregované/NetBox-korelačné pohľady, napr. dashboard)."""
    host = instance.zabbix_hosts.first()
    if host is None:
        return None
    return str(host.problem_count)


def _zabbix_event_url(web_url, triggerid, eventid):
    """Priamy odkaz na konkrétny problém/event v Zabbixe (tr_events.php) —
    rovnaký formát, aký generujú aj vstavané notifikačné makrá {EVENT.URL}."""
    if not web_url or not triggerid or not eventid:
        return None
    return f'{web_url}/tr_events.php?triggerid={triggerid}&eventid={eventid}'


def _history_row(ev, web_url=None):
    severity = int(ev.get('severity', 0))
    started = datetime.fromtimestamp(int(ev['clock']), tz=dt_timezone.utc)
    r_clock = int(ev.get('r_clock', 0) or 0)
    resolved = r_clock > 0
    return {
        'name': ev.get('name', ''),
        'severity': severity,
        'severity_label': SEVERITY_LABELS.get(severity, str(severity)),
        'severity_color': SeverityChoices.get_color(severity),
        'acknowledged': ev.get('acknowledged') == '1',
        'started': started,
        'ended': datetime.fromtimestamp(r_clock, tz=dt_timezone.utc) if resolved else None,
        'resolved': resolved,
        'tags': ev.get('tags', []),
        'zabbix_url': _zabbix_event_url(web_url, ev.get('objectid'), ev.get('eventid')),
    }


def _build_history_context(request, host):
    """Kontext pre kartu „História problémov" (inc/history_card.html) — zdieľané
    medzi tab-om na Device/VM (ZabbixTabView) a detailom Zabbix hosta
    (ZabbixHostView), aby sa rozsahová logika a fetch nemuseli duplikovať."""
    history_rows, history_error, history_truncated = [], None, False
    range_key = request.GET.get('range', DEFAULT_HISTORY_RANGE)
    custom_from = request.GET.get('from', '')
    custom_till = request.GET.get('till', '')

    if host:
        # "now" sa pre preset rozsahy zaokrúhli na cache_ttl bucket, aby
        # opakované načítanie tej istej stránky trafilo cache (inak by
        # time_till = presná aktuálna sekunda menilo cache kľúč zakaždým)
        cache_ttl = int(get_setting('cache_ttl', 30))
        bucket = max(cache_ttl, 5)
        now_ts = int(timezone.now().timestamp())
        now_ts -= now_ts % bucket

        time_from = time_till = None
        if custom_from or custom_till:
            range_key = 'custom'
            try:
                time_from = (
                    int(datetime.strptime(custom_from, '%Y-%m-%dT%H:%M')
                        .replace(tzinfo=dt_timezone.utc).timestamp())
                    if custom_from else now_ts - int(timedelta(days=7).total_seconds())
                )
                time_till = (
                    int(datetime.strptime(custom_till, '%Y-%m-%dT%H:%M')
                        .replace(tzinfo=dt_timezone.utc).timestamp())
                    if custom_till else now_ts
                )
                if time_from >= time_till:
                    raise ValueError('Od musí byť pred Do')
            except ValueError:
                history_error = 'Neplatný časový rozsah — skontroluj zadané dátumy.'
        else:
            if range_key not in HISTORY_RANGE_DELTAS:
                range_key = DEFAULT_HISTORY_RANGE
            time_till = now_ts
            time_from = now_ts - int(HISTORY_RANGE_DELTAS[range_key].total_seconds())

        if history_error is None:
            try:
                events = get_problem_history(host.zabbix_hostid, time_from, time_till)
            except Exception as e:
                history_error = f'{type(e).__name__}: {e}'
            else:
                history_truncated = len(events) >= HISTORY_LIMIT
                web_url = get_web_url()
                history_rows = [_history_row(ev, web_url) for ev in events]

    history_ranges = [
        {'key': key, 'label': label, 'active': range_key == key}
        for key, label in HISTORY_RANGE_CHOICES
    ]

    return {
        'history_rows': history_rows,
        'history_error': history_error,
        'history_truncated': history_truncated,
        'history_ranges': history_ranges,
        'history_range_key': range_key,
        'history_custom_from': custom_from,
        'history_custom_till': custom_till,
    }


class ZabbixTabView(generic.ObjectView):
    """Tab „Zabbix" — spoločná logika pre Device aj VM, podtrieda dodá
    queryset a base_template."""

    template_name = 'netbox_zabbix_status/host_tab.html'
    base_template = None
    tab = ViewTab(
        label='Zabbix',
        badge=_zabbix_tab_badge,
        hide_if_empty=True,
        permission='netbox_zabbix_status.view_zabbixhost',
    )

    @staticmethod
    def _problem_row(name, severity, acknowledged, started, opdata, tags,
                     suppressed=False, zabbix_url=None):
        return {
            'name': name,
            'severity': severity,
            'severity_label': SEVERITY_LABELS.get(severity, str(severity)),
            'severity_color': SeverityChoices.get_color(severity),
            'acknowledged': acknowledged,
            'suppressed': suppressed,
            'started': started,
            'opdata': opdata,
            'tags': tags,
            'zabbix_url': zabbix_url,
        }

    def get_extra_context(self, request, instance):
        host = instance.zabbix_hosts.first()
        web_url = get_web_url()
        problems = []
        live = None
        live_error = None

        if host:
            try:
                live = get_live_problems(host.zabbix_hostid)
            except Exception as e:
                live_error = f'{type(e).__name__}: {e}'
            if live is not None:
                problems = [
                    self._problem_row(
                        name=p.get('name', ''),
                        severity=int(p.get('severity', 0)),
                        acknowledged=p.get('acknowledged') == '1',
                        started=(
                            datetime.fromtimestamp(int(p['clock']), tz=dt_timezone.utc)
                            if p.get('clock') else None
                        ),
                        opdata=p.get('opdata') or '',
                        tags=p.get('tags', []),
                        suppressed=p.get('suppressed') == '1',
                        zabbix_url=_zabbix_event_url(web_url, p.get('objectid'), p.get('eventid')),
                    )
                    for p in live
                ]
                problems.sort(key=lambda r: (r['severity'], r['started'] or 0), reverse=True)
            else:
                problems = [
                    self._problem_row(
                        name=p.name,
                        severity=p.severity,
                        acknowledged=p.acknowledged,
                        started=p.started,
                        opdata=p.opdata,
                        tags=p.zabbix_tags,
                        suppressed=p.suppressed,
                        zabbix_url=p.get_zabbix_url(),
                    )
                    for p in host.problems.all()
                ]

        history_context = _build_history_context(request, host)

        zabbix_links = {}
        if host and web_url:
            zabbix_links = {
                'problems': f'{web_url}/zabbix.php?action=problem.view&hostids%5B%5D={host.zabbix_hostid}',
                'latest': f'{web_url}/zabbix.php?action=latest.view&hostids%5B%5D={host.zabbix_hostid}',
                'dashboard': f'{web_url}/zabbix.php?action=host.dashboard.view&hostid={host.zabbix_hostid}',
            }

        return {
            'zabbix_host': host,
            'problems': problems,
            'is_live': live is not None,
            'live_error': live_error,
            **history_context,
            'zabbix_links': zabbix_links,
            'base_template': self.base_template,
        }


@register_model_view(Device, name='zabbix', path='zabbix')
class DeviceZabbixTabView(ZabbixTabView):
    queryset = Device.objects.all()
    base_template = 'dcim/device/base.html'


@register_model_view(VirtualMachine, name='zabbix', path='zabbix')
class VirtualMachineZabbixTabView(ZabbixTabView):
    queryset = VirtualMachine.objects.all()
    base_template = 'virtualization/virtualmachine/base.html'


#
# Zoznamy a detail (M4) — synced dáta sú read-only, preto len export akcia
#

@register_model_view(ZabbixHost, 'list', path='', detail=False)
class ZabbixHostListView(generic.ObjectListView):
    queryset = ZabbixHost.objects.prefetch_related(
        'device__site', 'virtual_machine__site', 'tags'
    )
    table = ZabbixHostTable
    filterset = ZabbixHostFilterSet
    filterset_form = ZabbixHostFilterForm
    actions = {'export': {'view'}}


@register_model_view(ZabbixHost)
class ZabbixHostView(generic.ObjectView):
    queryset = ZabbixHost.objects.prefetch_related(
        'device__site', 'virtual_machine__site', 'problems'
    )

    def get_extra_context(self, request, instance):
        # instance JE priamo Zabbix host (na rozdiel od ZabbixTabView, kde sa
        # host hľadá cez Device/VM) — zdieľaná funkcia s tab-om na Device/VM.
        return _build_history_context(request, instance)


@register_model_view(ZabbixProblem, 'list', path='', detail=False)
class ZabbixProblemListView(generic.ObjectListView):
    queryset = ZabbixProblem.objects.prefetch_related(
        'host__device__site', 'host__virtual_machine__site'
    )
    table = ZabbixProblemTable
    filterset = ZabbixProblemFilterSet
    filterset_form = ZabbixProblemFilterForm
    actions = {'export': {'view'}}
    template_name = 'netbox_zabbix_status/zabbixproblem_list.html'


class ZabbixDashboardView(LoginRequiredMixin, View):
    """Prehľadový dashboard v štýle Zabbixu: dlaždice problémov podľa severity,
    rýchle štatistiky spárovaných hostov a panely najhorších hostov a problémov.
    Číta výhradne z DB snapshotu — rýchle aj pri výpadku Zabbixu."""

    def get(self, request):
        matching_enabled = bool(get_setting('matching_enabled', True))
        matched_only = matching_enabled and bool(get_setting('dashboard_matched_only', True))

        matched = ZabbixHost.objects.filter(
            Q(device__isnull=False) | Q(virtual_machine__isnull=False)
        )
        if matched_only:
            hosts = matched
            scope_note = 'zobrazené sú len spárované hosty'
        else:
            hosts = ZabbixHost.objects.all()
            scope_note = 'zobrazené sú všetky hosty zo Zabbixu'

        # Severity na dashboarde: výber z nastavení; prázdny = automaticky
        # všetky od minimálnej severity (dlaždice pod ňou by boli vždy 0)
        selected = sorted({int(s) for s in (get_setting('dashboard_severities', []) or [])})
        if not selected:
            selected = list(range(int(get_setting('min_severity', 2)), 6))
        problems = ZabbixProblem.objects.filter(host__in=hosts, severity__in=selected)

        severity_counts = dict(
            problems.values_list('severity').annotate(n=Count('pk'))
        )
        problems_url = reverse('plugins:netbox_zabbix_status:zabbixproblem_list')
        hosts_url = reverse('plugins:netbox_zabbix_status:zabbixhost_list')
        scope_qs = '?is_matched=true&' if matched_only else '?'

        severity_tiles = [
            {
                'label': label,
                'color': SeverityChoices.get_color(severity),
                'count': severity_counts.get(severity, 0),
                'url': f'{problems_url}?severity={severity}',
            }
            for severity, label in reversed(SeverityChoices.CHOICES)
            if severity in selected
        ]
        # Pre gear dropdown: všetky severity, zaškrtnuté = aktuálne efektívny výber
        severity_options = [
            {
                'value': severity,
                'label': label,
                'color': SeverityChoices.get_color(severity),
                'checked': severity in selected,
            }
            for severity, label in reversed(SeverityChoices.CHOICES)
        ]

        stats = []
        if matching_enabled:
            stats.append({'label': 'Spárované hosty', 'value': matched.count(),
                          'icon': 'mdi-server', 'url': f'{hosts_url}?is_matched=true'})
        else:
            stats.append({'label': 'Hosty', 'value': hosts.count(),
                          'icon': 'mdi-server', 'url': hosts_url})
        stats += [
            {'label': 'S problémami', 'value': hosts.filter(problem_count__gt=0).count(),
             'icon': 'mdi-alert-circle-outline', 'url': f'{hosts_url}{scope_qs}has_problems=true'},
            {'label': 'Agent down',
             'value': hosts.filter(agent_available=AvailabilityChoices.DOWN).count(),
             'icon': 'mdi-lan-disconnect', 'url': f'{hosts_url}{scope_qs}agent_available=down'},
            {'label': 'SNMP down',
             'value': hosts.filter(snmp_available=AvailabilityChoices.DOWN).count(),
             'icon': 'mdi-access-point-off', 'url': f'{hosts_url}{scope_qs}snmp_available=down'},
            {'label': 'Maintenance', 'value': hosts.filter(in_maintenance=True).count(),
             'icon': 'mdi-wrench', 'url': f'{hosts_url}{scope_qs}in_maintenance=true'},
        ]
        if matching_enabled:
            stats.append({'label': 'Nespárované',
                          'value': ZabbixHost.objects.filter(
                              device__isnull=True, virtual_machine__isnull=True).count(),
                          'icon': 'mdi-link-off',
                          'url': f'{hosts_url}?is_matched=false'})
        else:
            stats.append({'label': 'Vypnuté',
                          'value': hosts.filter(status='disabled').count(),
                          'icon': 'mdi-power-plug-off',
                          'url': f'{hosts_url}{scope_qs}status=disabled'})

        # Panel hostov počíta z filtrovaných problémov (nie z denormalizovaných
        # polí), aby sedel s výberom severít
        top_hosts = list(
            hosts.annotate(
                filtered_count=Count('problems', filter=Q(problems__severity__in=selected)),
                filtered_max=Max('problems__severity', filter=Q(problems__severity__in=selected)),
            )
            .filter(filtered_count__gt=0)
            .order_by('-filtered_max', '-filtered_count', 'name')
            .prefetch_related('device__site', 'virtual_machine__site')[:12]
        )
        for h in top_hosts:
            h.problem_count = h.filtered_count
            h.max_severity = h.filtered_max

        recent_problems = problems.order_by('-severity', '-started').prefetch_related(
            'host__device', 'host__virtual_machine'
        )[:15]

        last_synced = ZabbixHost.objects.order_by('-last_synced').values_list(
            'last_synced', flat=True
        ).first()
        sync_interval = int(get_config().get('sync_interval', 5))
        sync_stale = bool(
            last_synced
            and timezone.now() - last_synced > timedelta(minutes=2 * sync_interval)
        )

        return render(request, 'netbox_zabbix_status/dashboard.html', {
            'severity_tiles': severity_tiles,
            'severity_options': severity_options,
            'problems_total': sum(severity_counts.values()),
            'stats': stats,
            'top_hosts': top_hosts,
            'recent_problems': recent_problems,
            'problems_url': problems_url,
            'hosts_url': hosts_url,
            'hosts_scope_qs': scope_qs,
            'scope_note': scope_note,
            'refresh': max(0, int(get_setting('dashboard_refresh', 60))),
            'last_synced': last_synced,
            'sync_stale': sync_stale,
            'web_url': get_web_url(),
        })


class DashboardSeveritiesView(PermissionRequiredMixin, View):
    """Rýchle uloženie výberu severít z gear dropdownu na dashboarde.
    Zapisuje to isté nastavenie ako stránka Nastavenia (dashboard_severities)."""

    permission_required = 'netbox_zabbix_status.change_zabbixconfiguration'

    def post(self, request):
        try:
            severities = sorted({
                int(v) for v in request.POST.getlist('severities') if 0 <= int(v) <= 5
            })
        except ValueError:
            severities = []
        config = ZabbixConfiguration.get_solo()
        config.dashboard_severities = severities
        config.save()
        if severities:
            messages.success(request, 'Výber severít na dashboarde uložený.')
        else:
            messages.success(
                request, 'Výber severít zrušený — zobrazujú sa všetky od minimálnej severity.'
            )
        return redirect('plugins:netbox_zabbix_status:dashboard')


class ZabbixRefreshView(LoginRequiredMixin, View):
    """Tlačidlo „Obnoviť zo Zabbixu": synchrónne spustí run_sync() (čerstvé dáta
    hneď, nie až pri ďalšom naplánovanom behu) a vráti sa na pôvodnú stránku."""

    def post(self, request):
        try:
            stats = run_sync()
        except ZabbixConfigError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Obnovenie zo Zabbixu zlyhalo: {e}')
        else:
            messages.success(
                request,
                f"Obnovené zo Zabbixu: {stats['hosts_total']} hostov, "
                f"{stats['problems_total']} problémov ({stats['duration_s']} s).",
            )
        return_url = request.POST.get('return_url', '')
        if not return_url.startswith('/'):
            return_url = reverse('plugins:netbox_zabbix_status:dashboard')
        return redirect(return_url)


class ZabbixSettingsView(PermissionRequiredMixin, View):
    """Grafická editácia runtime nastavení pluginu (Zabbix → Nastavenia).
    Uložené hodnoty platia okamžite — číta ich get_setting() za behu."""

    permission_required = 'netbox_zabbix_status.change_zabbixconfiguration'

    def get(self, request):
        form = ZabbixSettingsForm(instance=ZabbixConfiguration.get_solo())
        return self._render(request, form)

    def post(self, request):
        form = ZabbixSettingsForm(request.POST, instance=ZabbixConfiguration.get_solo())
        if form.is_valid():
            form.save()
            messages.success(request, 'Zabbix nastavenia uložené — platia okamžite.')
            return redirect('plugins:netbox_zabbix_status:settings')
        return self._render(request, form)

    def _render(self, request, form):
        cfg = get_config()
        return render(request, 'netbox_zabbix_status/settings.html', {
            'form': form,
            'api_url': cfg.get('api_url', ''),
            'config_pk': form.instance.pk,
        })


#
# Ručné párovanie (M5)
#

@register_model_view(ZabbixHost, 'edit')
class ZabbixHostEditView(generic.ObjectEditView):
    """Edit = len ručné priradenie hosta k zariadeniu/VM (match_method=manual)."""
    queryset = ZabbixHost.objects.all()
    form = ZabbixHostAssignForm


#
# Import nespárovaného hosta ako nové zariadenie/VM (M6)
#

IFACE_TYPE_LABELS = {'1': 'Agent', '2': 'SNMP', '3': 'IPMI', '4': 'JMX'}


def _format_interface(iface):
    """Rovnaké typové mapovanie a ip/dns-podľa-useip pravidlo, aké používajú
    host_tab.html a zabbixhost.html — len ako jeden riadok textu pre comments."""
    type_label = IFACE_TYPE_LABELS.get(iface.get('type'), iface.get('type') or '')
    address = iface.get('ip') if iface.get('useip') == '1' else iface.get('dns')
    return f"{type_label}: {address}:{iface.get('port', '')}"


def _best_interface_ip(interfaces):
    """Prvý Zabbix interfejs s reálnou IP adresou (useip='1' a neprázdna ip) —
    kandidát na loopback IP pri importe. None, ak žiadny taký nie je (vtedy sa
    pri importe nevytvára rozhranie/IP, len samotné zariadenie/VM)."""
    for iface in interfaces:
        if iface.get('useip') == '1' and iface.get('ip'):
            return iface['ip']
    return None


def _round_coord(value):
    """Zabbix inventory GPS súradnice majú bežne viac než 6 desatinných miest
    (napr. '48.7782926184094') — NetBoxove Device.latitude/longitude majú
    decimal_places=6, odoslanie neorezanej hodnoty by pri uložení spadlo na
    validácii. Vráti None pri neplatnej/prázdnej hodnote."""
    try:
        return str(Decimal(value).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError):
        return None


def _guess_site(host_groups):
    """Odhad Site podľa mena Zabbix host group — vráti pk len ak presne jedna
    Site zodpovedá (case-insensitive) naprieč všetkými group menami, inak None
    (žiadny, ani nejednoznačný odhad; pole ostáva na ručné doplnenie)."""
    matched_pks = set()
    for group in host_groups:
        if not group:
            continue
        matched_pks.update(Site.objects.filter(name__iexact=group).values_list('pk', flat=True))
    if len(matched_pks) == 1:
        return matched_pks.pop()
    return None


def _site_from_tag(tags, tag_key):
    """Site pk z explicitného Zabbix host tagu (napr. nbx_siteid=63) — na
    rozdiel od _guess_site() nejde o odhad, je to priamy krížový odkaz
    nastavený človekom, preto má prednosť. None ak tag chýba, hodnota nie je
    celé číslo v rozsahu platného pk, alebo taká Site v NetBoxe neexistuje."""
    if not tag_key:
        return None
    for t in tags:
        if t.get('tag') != tag_key:
            continue
        try:
            site_pk = int(t.get('value', ''))
            # int() má neobmedzenú presnosť — hodnota mimo rozsahu stĺpca
            # (Site.id je BigAutoField/bigint, napr. omylom vložený timestamp)
            # by inak spadla na DB dotaze. 0 je platné pk (BigAutoField ho
            # nevylučuje), preto dolná hranica <= 0, nie < 0.
            if not (0 <= site_pk <= 9_223_372_036_854_775_807):
                continue
            if Site.objects.filter(pk=site_pk).exists():
                return site_pk
        except (TypeError, ValueError):
            continue
    return None


class ZabbixHostImportView(LoginRequiredMixin, View):
    """Vstupný bod pre ručný import nespárovaného Zabbix hosta do NetBoxu.

    Zabbix dáta samy o sebe nevedia spoľahlivo povedať, či ide o fyzické
    zariadenie alebo virtuálny stroj, preto sa nič nezapisuje automaticky —
    stránka ukáže dva kombinované formuláre (Zariadenie+Loopback rozhranie+IP,
    VM+VM rozhranie+IP), každý predvyplnený z Zabbix dát (meno, comments,
    prípadne odhadnutá Site, IP zo SNMP interfejsu). Človek vyberie jeden,
    doplní povinné polia (device_type/rola…) a uloží — všetky tri objekty sa
    vytvoria v jednej transakcii. Rozhranie+IP sa vytvoria len ak má polička
    IP adresy pri odoslaní neprázdnu hodnotu (dá sa jednoducho vynechať
    vymazaním poľa). Rovnaká „human confirms" filozofia ako pri ručnom
    párovaní — nič sa nezapisuje bez výslovného kliknutia na Uložiť."""

    def get(self, request, pk):
        host = get_object_or_404(ZabbixHost, pk=pk)
        if host.assigned_object:
            messages.info(request, 'Tento host je už spárovaný.')
            return redirect(host.get_absolute_url())
        return render(request, 'netbox_zabbix_status/host_import.html', self._context(request, host))

    def post(self, request, pk):
        host = get_object_or_404(ZabbixHost, pk=pk)
        if host.assigned_object:
            messages.info(request, 'Tento host je už spárovaný.')
            return redirect(host.get_absolute_url())

        kind = request.POST.get('kind')
        if kind == 'device' and not request.user.has_perm('dcim.add_device'):
            kind = None
        if kind == 'vm' and not request.user.has_perm('virtualization.add_virtualmachine'):
            kind = None
        if kind not in ('device', 'vm'):
            messages.error(request, 'Neplatná alebo neoprávnená požiadavka.')
            return redirect(request.path)

        save = self._save_device if kind == 'device' else self._save_vm
        ok, obj, iface, ip_obj, forms = save(request)

        if not ok:
            context = self._context(request, host)
            context.update(forms)
            return render(request, 'netbox_zabbix_status/host_import.html', context)

        if iface:
            messages.success(
                request,
                f'Vytvorené: „{obj}", rozhranie „{iface}"'
                + (f', IP „{ip_obj}"' if ip_obj else '') + '.'
            )
        else:
            messages.success(request, f'Vytvorené: „{obj}".')
        return redirect(obj.get_absolute_url())

    # -- zdieľané pomocné metódy --------------------------------------------

    @staticmethod
    def _build_comments(host):
        visible = host.visible_name or host.name
        host_groups_str = ', '.join(g for g in host.host_groups if g) or '—'
        templates_str = ', '.join(t for t in host.templates if t) or '—'
        proxy_str = host.proxy_name or '—'
        interfaces_str = ', '.join(_format_interface(i) for i in host.interfaces) or '—'
        last_synced_str = host.last_synced if host.last_synced else '—'
        return (
            f'Importované zo Zabbix hosta "{visible}" (host ID {host.zabbix_hostid}).\n'
            f'Host groups: {host_groups_str}\n'
            f'Šablóny: {templates_str}\n'
            f'Proxy: {proxy_str}\n'
            f'Interfejsy: {interfaces_str}\n'
            f'Posledný sync zo Zabbixu: {last_synced_str}'
        )

    def _context(self, request, host):
        """Nezáväzné (GET) formuláre pre oba typy, predvyplnené zo Zabbix dát —
        použité aj na znovu-vykreslenie po neúspešnej validácii (vtedy sa
        prepíšu tie za _save_device/_save_vm vo `forms` dicte)."""
        comments = self._build_comments(host)
        ip = _best_interface_ip(host.interfaces)
        visible = host.visible_name or host.name

        try:
            hints = get_host_import_hints(host.zabbix_hostid)
        except Exception:
            hints = {'inventory': {}, 'tags': []}

        # is not None (nie "or") — Site pk 0 by bol falsy a "or" by ho zahodil
        # v prospech odhadu, hoci tag má vždy prednosť
        site_pk = _site_from_tag(hints['tags'], get_setting('site_id_tag_key', 'nbx_siteid'))
        if site_pk is None:
            site_pk = _guess_site(host.host_groups)

        common = {'name': visible, 'comments': comments, 'status': 'active'}
        if site_pk is not None:
            common['site'] = site_pk
        ip_initial = {'address': f'{ip}/32', 'status': 'active', 'primary_for_parent': True} if ip else {}

        # GPS súradnice (ak má host vyplnené Zabbix inventory) — len pre Device,
        # VirtualMachineForm nemá latitude/longitude (fyzická poloha nedáva pre VM zmysel)
        device_initial = dict(common)
        lat = _round_coord(hints['inventory'].get('location_lat'))
        if lat is not None:
            device_initial['latitude'] = lat
        lon = _round_coord(hints['inventory'].get('location_lon'))
        if lon is not None:
            device_initial['longitude'] = lon

        return {
            'host': host,
            'has_ip': bool(ip),
            'can_add_device': request.user.has_perm('dcim.add_device'),
            'can_add_vm': request.user.has_perm('virtualization.add_virtualmachine'),
            'device_form': DeviceForm(initial=device_initial, prefix='device'),
            'iface_form': InterfaceForm(
                initial={'name': 'Loopback0', 'type': 'virtual', 'enabled': True}, prefix='iface'
            ),
            'ip_form': IPAddressForm(initial=ip_initial, prefix='ip'),
            'vm_form': VirtualMachineForm(initial=common, prefix='vm'),
            'vmiface_form': VMInterfaceForm(initial={'name': 'Loopback0', 'enabled': True}, prefix='vmiface'),
            'vmip_form': IPAddressForm(initial=ip_initial, prefix='vmip'),
        }

    def _save_device(self, request):
        """Vytvorí Device, a ak formulár IP adresy obsahuje neprázdnu hodnotu,
        aj Interface (type=virtual) + IPAddress (assigned_object=ten interface,
        primary_for_parent podľa checkboxu) — všetko v jednej transakcii.
        Vracia (ok, device_alebo_None, iface_alebo_None, ip_alebo_None,
        {kontextove_kluce_s_bound_formularmi_na_znovu-vykreslenie})."""
        with transaction.atomic():
            device_form = DeviceForm(data=request.POST, prefix='device')
            if not device_form.is_valid():
                transaction.set_rollback(True)
                return False, None, None, None, {'device_form': device_form}
            device = device_form.save()

            ip_value = request.POST.get('ip-address', '').strip()
            if not ip_value:
                return True, device, None, None, {}

            iface_data = request.POST.copy()
            iface_data['iface-device'] = device.pk
            iface_form = InterfaceForm(data=iface_data, prefix='iface')
            if not iface_form.is_valid():
                transaction.set_rollback(True)
                return False, None, None, None, {'device_form': device_form, 'iface_form': iface_form}
            iface = iface_form.save()

            ip_data = request.POST.copy()
            ip_data['ip-interface'] = iface.pk
            ip_form = IPAddressForm(data=ip_data, prefix='ip')
            if not ip_form.is_valid():
                transaction.set_rollback(True)
                return False, None, None, None, {
                    'device_form': device_form, 'iface_form': iface_form, 'ip_form': ip_form,
                }
            ip_obj = ip_form.save()

            return True, device, iface, ip_obj, {}

    def _save_vm(self, request):
        """Rovnaké ako _save_device, len pre VirtualMachine/VMInterface —
        VMInterfaceForm nemá pole 'type' (VM rozhrania ho v NetBoxe nemajú)."""
        with transaction.atomic():
            vm_form = VirtualMachineForm(data=request.POST, prefix='vm')
            if not vm_form.is_valid():
                transaction.set_rollback(True)
                return False, None, None, None, {'vm_form': vm_form}
            vm = vm_form.save()

            ip_value = request.POST.get('vmip-address', '').strip()
            if not ip_value:
                return True, vm, None, None, {}

            iface_data = request.POST.copy()
            iface_data['vmiface-virtual_machine'] = vm.pk
            vmiface_form = VMInterfaceForm(data=iface_data, prefix='vmiface')
            if not vmiface_form.is_valid():
                transaction.set_rollback(True)
                return False, None, None, None, {'vm_form': vm_form, 'vmiface_form': vmiface_form}
            vmiface = vmiface_form.save()

            ip_data = request.POST.copy()
            ip_data['vmip-vminterface'] = vmiface.pk
            vmip_form = IPAddressForm(data=ip_data, prefix='vmip')
            if not vmip_form.is_valid():
                transaction.set_rollback(True)
                return False, None, None, None, {
                    'vm_form': vm_form, 'vmiface_form': vmiface_form, 'vmip_form': vmip_form,
                }
            ip_obj = vmip_form.save()

            return True, vm, vmiface, ip_obj, {}
