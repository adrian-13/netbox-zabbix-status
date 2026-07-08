from django.db.models import Count
from django.template.loader import render_to_string
from django.urls import reverse

from extras.dashboard.utils import register_widget
from extras.dashboard.widgets import DashboardWidget

from .choices import SeverityChoices
from .models import ZabbixHost, ZabbixProblem


@register_widget
class ZabbixProblemsWidget(DashboardWidget):
    default_title = 'Zabbix problémy'
    description = 'Aktívne Zabbix problémy podľa severity'

    def render(self, request):
        counts = dict(
            ZabbixProblem.objects.values_list('severity').annotate(n=Count('pk'))
        )
        problems_url = reverse('plugins:netbox_zabbix_status:zabbixproblem_list')
        rows = [
            {
                'label': label,
                'color': SeverityChoices.get_color(severity),
                'count': counts[severity],
                'url': f'{problems_url}?severity={severity}',
            }
            for severity, label in reversed(SeverityChoices.CHOICES)
            if counts.get(severity)
        ]
        unmatched = ZabbixHost.objects.filter(
            device__isnull=True, virtual_machine__isnull=True
        ).count()
        hosts_url = reverse('plugins:netbox_zabbix_status:zabbixhost_list')
        return render_to_string('netbox_zabbix_status/widgets/problems.html', {
            'rows': rows,
            'total': sum(counts.values()),
            'problems_url': problems_url,
            'unmatched': unmatched,
            'unmatched_url': f'{hosts_url}?is_matched=false',
        })
