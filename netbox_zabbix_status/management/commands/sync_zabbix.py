from django.core.management.base import BaseCommand, CommandError

from netbox_zabbix_status.sync import run_sync
from netbox_zabbix_status.zabbix import ZabbixConfigError


class Command(BaseCommand):
    help = 'Runs Zabbix -> NetBox synchronization synchronously (outside the job queue).'

    def handle(self, *args, **options):
        try:
            stats = run_sync()
        except ZabbixConfigError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS('Sync OK'))
        width = max(len(k) for k in stats)
        for key, value in stats.items():
            self.stdout.write(f'  {key:<{width}}  {value}')
