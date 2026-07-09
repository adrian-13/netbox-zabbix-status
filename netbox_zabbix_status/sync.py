"""Jadro Zabbix -> NetBox synchronizácie.

run_sync() stiahne hostov a aktívne problémy zo Zabbixu, spáruje hostov
s NetBox zariadeniami/VM a uloží snapshot do plugin modelov. Volá ho
periodický system job (jobs.py) aj `manage.py sync_zabbix`.
"""
import logging
import time
from datetime import datetime, timezone as dt_timezone

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from dcim.models import Device, Interface
from ipam.models import IPAddress
from virtualization.models import VirtualMachine, VMInterface

from .choices import AvailabilityChoices, MatchMethodChoices, ZabbixHostStatusChoices
from .matching import HostMatcher, normalize_hostname
from .models import ZabbixHost, ZabbixProblem
from .zabbix import get_client, get_setting

logger = logging.getLogger('netbox.plugins.netbox_zabbix_status')

# Zabbix interface/host availability: 0 unknown, 1 up, 2 down
AVAILABILITY_MAP = {
    '0': AvailabilityChoices.UNKNOWN,
    '1': AvailabilityChoices.UP,
    '2': AvailabilityChoices.DOWN,
}

# Zabbix interface.type -> pole availability na ZabbixHost
INTERFACE_TYPE_FIELDS = {
    '1': 'agent_available',
    '2': 'snmp_available',
    '3': 'ipmi_available',
    '4': 'jmx_available',
}


def fetch_hosts(api):
    return api.host.get(
        output=['hostid', 'host', 'name', 'status', 'maintenance_status',
                'active_available', 'proxyid', 'proxy_groupid', 'monitored_by'],
        selectInterfaces=['type', 'ip', 'dns', 'port', 'useip', 'available'],
        selectParentTemplates=['name'],
        selectHostGroups=['name'],
    )


def fetch_problems(api, min_severity, include_suppressed):
    """Vráti (problems, trigger_hosts). problem.objectid je triggerid,
    mapovanie na hostov ide cez trigger.get."""
    params = dict(
        output=['eventid', 'objectid', 'name', 'severity', 'acknowledged',
                'suppressed', 'clock', 'opdata'],
        selectTags='extend',
        severities=list(range(min_severity, 6)),
        recent=False,
        sortfield='eventid',
    )
    if not include_suppressed:
        # Parita so Zabbix UI: problémy hostov v maintenance sa defaultne skrývajú
        params['suppressed'] = False
    problems = api.problem.get(**params)
    trigger_hosts = {}
    trigger_ids = list({p['objectid'] for p in problems})
    if trigger_ids:
        triggers = api.trigger.get(
            triggerids=trigger_ids,
            output=['triggerid'],
            selectHosts=['hostid'],
        )
        trigger_hosts = {
            t['triggerid']: [h['hostid'] for h in t.get('hosts', [])]
            for t in triggers
        }
    return problems, trigger_hosts


def fetch_proxy_names(api):
    names = {}
    for proxy in api.proxy.get(output=['proxyid', 'name']):
        names[('proxy', proxy['proxyid'])] = proxy['name']
    try:
        for group in api.proxygroup.get(output=['proxy_groupid', 'name']):
            names[('group', group['proxy_groupid'])] = f"{group['name']} (proxy group)"
    except Exception:
        # proxy groups existujú až od Zabbix 7.0
        pass
    return names


def resolve_proxy_name(zabbix_host, proxy_names):
    monitored_by = zabbix_host.get('monitored_by')
    if monitored_by == '1':
        return proxy_names.get(('proxy', zabbix_host.get('proxyid')), '')
    if monitored_by == '2':
        return proxy_names.get(('group', zabbix_host.get('proxy_groupid')), '')
    return ''


def worst_availability(values):
    """Agregácia availability viacerých interfejsov rovnakého typu: down > up > unknown."""
    if '2' in values:
        return AvailabilityChoices.DOWN
    if '1' in values:
        return AvailabilityChoices.UP
    return AvailabilityChoices.UNKNOWN


def build_matcher():
    """Postaví HostMatcher z aktuálneho obsahu NetBox DB."""
    strip_domains = get_setting('hostname_strip_domains', []) or []
    sync_vms = bool(get_setting('sync_vms', True))

    device_names = {}
    for pk, name in Device.objects.exclude(name=None).exclude(name='').values_list('pk', 'name'):
        device_names.setdefault(normalize_hostname(name, strip_domains), []).append(pk)

    vm_names = {}
    if sync_vms:
        for pk, name in VirtualMachine.objects.values_list('pk', 'name'):
            vm_names.setdefault(normalize_hostname(name, strip_domains), []).append(pk)

    primary_ips = {}
    for pk, ip4, ip6 in Device.objects.values_list('pk', 'primary_ip4__address', 'primary_ip6__address'):
        for addr in (ip4, ip6):
            if addr:
                primary_ips.setdefault(str(addr.ip), []).append(('device', pk))
    if sync_vms:
        for pk, ip4, ip6 in VirtualMachine.objects.values_list('pk', 'primary_ip4__address', 'primary_ip6__address'):
            for addr in (ip4, ip6):
                if addr:
                    primary_ips.setdefault(str(addr.ip), []).append(('vm', pk))

    any_ips = {}
    iface_ct = ContentType.objects.get_for_model(Interface)
    iface_to_device = dict(Interface.objects.values_list('pk', 'device_id'))
    for addr, obj_id in IPAddress.objects.filter(
        assigned_object_type=iface_ct
    ).values_list('address', 'assigned_object_id'):
        device_id = iface_to_device.get(obj_id)
        if device_id:
            any_ips.setdefault(str(addr.ip), []).append(('device', device_id))
    if sync_vms:
        vm_iface_ct = ContentType.objects.get_for_model(VMInterface)
        vm_iface_to_vm = dict(VMInterface.objects.values_list('pk', 'virtual_machine_id'))
        for addr, obj_id in IPAddress.objects.filter(
            assigned_object_type=vm_iface_ct
        ).values_list('address', 'assigned_object_id'):
            vm_id = vm_iface_to_vm.get(obj_id)
            if vm_id:
                any_ips.setdefault(str(addr.ip), []).append(('vm', vm_id))

    return HostMatcher(
        device_names=device_names,
        vm_names=vm_names,
        primary_ips=primary_ips,
        any_ips=any_ips,
        strip_domains=strip_domains,
        match_by_ip=bool(get_setting('match_by_ip', True)),
    )


def run_sync():
    """Stiahne stav zo Zabbixu a zapíše ho do plugin modelov. Vráti štatistiky."""
    started = time.monotonic()
    api = get_client()

    zabbix_hosts = fetch_hosts(api)
    problems, trigger_hosts = fetch_problems(
        api,
        int(get_setting('min_severity', 2)),
        bool(get_setting('include_suppressed', False)),
    )
    proxy_names = fetch_proxy_names(api)

    # matching_enabled=False -> čistý Zabbix viewer: väzby sa nevytvárajú ani
    # nemenia (existujúce zostávajú v DB nedotknuté, prepnutie späť je bezstratové)
    matching_enabled = bool(get_setting('matching_enabled', True))
    matcher = build_matcher() if matching_enabled else None
    now = timezone.now()
    stats = {
        'matching_enabled': matching_enabled,
        'hosts_total': len(zabbix_hosts),
        'matched_name': 0,
        'matched_ip': 0,
        'matched_manual': 0,
        'matched_kept': 0,
        'unmatched': 0,
        'hosts_deleted': 0,
        'problems_total': len(problems),
        'problems_unassigned': 0,
    }

    with transaction.atomic():
        existing = {h.zabbix_hostid: h for h in ZabbixHost.objects.all()}
        host_objs = {}  # zabbix hostid (str) -> ZabbixHost

        for zh in zabbix_hosts:
            hostid = int(zh['hostid'])
            obj = existing.get(hostid) or ZabbixHost(zabbix_hostid=hostid)

            obj.name = zh.get('host', '')[:200]
            obj.visible_name = zh.get('name', '')[:200]
            obj.status = (
                ZabbixHostStatusChoices.ENABLED if zh.get('status') == '0'
                else ZabbixHostStatusChoices.DISABLED
            )
            obj.in_maintenance = zh.get('maintenance_status') == '1'
            obj.active_available = AVAILABILITY_MAP.get(
                zh.get('active_available'), AvailabilityChoices.UNKNOWN
            )

            per_type = {field: [] for field in INTERFACE_TYPE_FIELDS.values()}
            interfaces = []
            for iface in zh.get('interfaces', []):
                field = INTERFACE_TYPE_FIELDS.get(iface.get('type'))
                if field:
                    per_type[field].append(iface.get('available', '0'))
                interfaces.append({
                    k: iface.get(k) for k in ('type', 'ip', 'dns', 'port', 'useip')
                })
            for field, values in per_type.items():
                setattr(obj, field, worst_availability(values))
            obj.interfaces = interfaces

            obj.host_groups = sorted(g['name'] for g in zh.get('hostgroups', []))
            obj.templates = sorted(t['name'] for t in zh.get('parentTemplates', []))
            obj.proxy_name = resolve_proxy_name(zh, proxy_names)[:200]

            # Väzba: manuálnu nikdy neprepisuj; existujúcu automatickú s platným
            # cieľom nechaj (stabilita pri premenovaní); inak skús spárovať.
            has_target = bool(obj.device_id or obj.virtual_machine_id)
            if matcher is None:
                pass
            elif obj.match_method == MatchMethodChoices.MANUAL and has_target:
                stats['matched_manual'] += 1
            elif obj.pk and has_target and obj.match_method in (
                MatchMethodChoices.NAME, MatchMethodChoices.IP
            ):
                stats['matched_kept'] += 1
            else:
                kind, pk, method = matcher.match(zh)
                obj.device_id = pk if kind == 'device' else None
                obj.virtual_machine_id = pk if kind == 'vm' else None
                obj.match_method = method
                if method == MatchMethodChoices.NAME:
                    stats['matched_name'] += 1
                elif method == MatchMethodChoices.IP:
                    stats['matched_ip'] += 1
                else:
                    stats['unmatched'] += 1

            obj.last_synced = now
            obj.save()
            host_objs[zh['hostid']] = obj

        deleted, _ = ZabbixHost.objects.exclude(
            zabbix_hostid__in=[int(zh['hostid']) for zh in zabbix_hosts]
        ).delete()
        stats['hosts_deleted'] = deleted

        # Problémy: upsert podľa eventid, zaniknuté zmazať
        existing_problems = {p.zabbix_eventid: p for p in ZabbixProblem.objects.all()}
        seen_events = set()
        for p in problems:
            host_obj = next(
                (host_objs[h] for h in trigger_hosts.get(p['objectid'], []) if h in host_objs),
                None,
            )
            if host_obj is None:
                stats['problems_unassigned'] += 1
                continue
            eventid = int(p['eventid'])
            seen_events.add(eventid)
            obj = existing_problems.get(eventid) or ZabbixProblem(zabbix_eventid=eventid)
            obj.host = host_obj
            obj.zabbix_triggerid = int(p['objectid']) if p.get('objectid') else None
            obj.name = p.get('name', '')[:500]
            obj.severity = int(p.get('severity', 0))
            obj.acknowledged = p.get('acknowledged') == '1'
            obj.suppressed = p.get('suppressed') == '1'
            obj.started = (
                datetime.fromtimestamp(int(p['clock']), tz=dt_timezone.utc)
                if p.get('clock') else None
            )
            obj.opdata = (p.get('opdata') or '')[:500]
            obj.zabbix_tags = p.get('tags', [])
            obj.save()
        ZabbixProblem.objects.exclude(zabbix_eventid__in=seen_events).delete()

        # Denormalizované počty pre list views
        ZabbixHost.objects.update(problem_count=0, max_severity=None)
        for row in ZabbixProblem.objects.values('host').annotate(
            n=Count('pk'), mx=Max('severity')
        ):
            ZabbixHost.objects.filter(pk=row['host']).update(
                problem_count=row['n'], max_severity=row['mx']
            )

    stats['duration_s'] = round(time.monotonic() - started, 1)
    logger.info('Zabbix sync: %s', stats)
    return stats
