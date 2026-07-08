from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Count, Max, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import View

from dcim.models import Device
from netbox.views import generic
from utilities.views import ViewTab, register_model_view
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
    Pri vypnutom párovaní sa tab neukazuje vôbec."""
    if not get_setting('matching_enabled', True):
        return None
    host = instance.zabbix_hosts.first()
    if host is None:
        return None
    return str(host.problem_count)


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
                     suppressed=False):
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
        }

    @staticmethod
    def _history_row(ev):
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
        }

    def get_extra_context(self, request, instance):
        host = instance.zabbix_hosts.first()
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
                    )
                    for p in host.problems.all()
                ]

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
                    history_rows = [self._history_row(ev) for ev in events]

        history_ranges = [
            {'key': key, 'label': label, 'active': range_key == key}
            for key, label in HISTORY_RANGE_CHOICES
        ]

        zabbix_links = {}
        web_url = get_web_url()
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
            'history_rows': history_rows,
            'history_error': history_error,
            'history_truncated': history_truncated,
            'history_ranges': history_ranges,
            'history_range_key': range_key,
            'history_custom_from': custom_from,
            'history_custom_till': custom_till,
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
            'sync_interval': cfg.get('sync_interval', 5),
        })


#
# Ručné párovanie (M5)
#

@register_model_view(ZabbixHost, 'edit')
class ZabbixHostEditView(generic.ObjectEditView):
    """Edit = len ručné priradenie hosta k zariadeniu/VM (match_method=manual)."""
    queryset = ZabbixHost.objects.all()
    form = ZabbixHostAssignForm
