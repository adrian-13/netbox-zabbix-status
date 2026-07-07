from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import View

from dcim.choices import DeviceStatusChoices
from dcim.filtersets import DeviceFilterSet
from dcim.forms import DeviceFilterForm
from dcim.models import Device
from dcim.tables import DeviceTable
from netbox.views import generic
from utilities.views import ViewTab, register_model_view
from virtualization.choices import VirtualMachineStatusChoices
from virtualization.filtersets import VirtualMachineFilterSet
from virtualization.forms import VirtualMachineFilterForm
from virtualization.models import VirtualMachine
from virtualization.tables import VirtualMachineTable

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
    ZabbixConfigError,
    get_config,
    get_live_problems,
    get_setting,
    get_web_url,
)

SEVERITY_LABELS = dict(SeverityChoices.CHOICES)


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
        problems = ZabbixProblem.objects.filter(host__in=hosts)

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
                          'url': reverse('plugins:netbox_zabbix_status:unmatched_hosts')})
        else:
            stats.append({'label': 'Vypnuté',
                          'value': hosts.filter(status='disabled').count(),
                          'icon': 'mdi-power-plug-off',
                          'url': f'{hosts_url}{scope_qs}status=disabled'})

        top_hosts = hosts.filter(problem_count__gt=0).order_by(
            '-max_severity', '-problem_count', 'name'
        ).prefetch_related('device__site', 'virtual_machine__site')[:12]

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
# Ručné párovanie a konzistenčné pohľady (M5)
#

@register_model_view(ZabbixHost, 'edit')
class ZabbixHostEditView(generic.ObjectEditView):
    """Edit = len ručné priradenie hosta k zariadeniu/VM (match_method=manual)."""
    queryset = ZabbixHost.objects.all()
    form = ZabbixHostAssignForm


class UnmatchedHostsView(ZabbixHostListView):
    """Zabbix hosty bez väzby na NetBox — kandidáti na ručné priradenie."""
    queryset = ZabbixHost.objects.filter(
        device__isnull=True, virtual_machine__isnull=True
    ).prefetch_related('tags')
    template_name = 'netbox_zabbix_status/unmatched_hosts.html'


class UnmonitoredDevicesView(generic.ObjectListView):
    """Aktívne zariadenia bez Zabbix hosta — diera v monitoringu."""
    queryset = Device.objects.filter(
        status=DeviceStatusChoices.STATUS_ACTIVE,
        zabbix_hosts__isnull=True,
    ).prefetch_related('site', 'rack', 'role', 'device_type', 'primary_ip4', 'primary_ip6')
    table = DeviceTable
    filterset = DeviceFilterSet
    filterset_form = DeviceFilterForm
    template_name = 'netbox_zabbix_status/unmonitored_devices.html'
    actions = {'export': {'view'}}


class UnmonitoredVMsView(generic.ObjectListView):
    """Aktívne VM bez Zabbix hosta."""
    queryset = VirtualMachine.objects.filter(
        status=VirtualMachineStatusChoices.STATUS_ACTIVE,
        zabbix_hosts__isnull=True,
    ).prefetch_related('site', 'cluster', 'role', 'primary_ip4', 'primary_ip6')
    table = VirtualMachineTable
    filterset = VirtualMachineFilterSet
    filterset_form = VirtualMachineFilterForm
    template_name = 'netbox_zabbix_status/unmonitored_vms.html'
    actions = {'export': {'view'}}
