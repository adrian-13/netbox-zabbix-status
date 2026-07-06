from django.core.management.base import BaseCommand, CommandError

from netbox_zabbix_status.zabbix import ZabbixConfigError, get_client, get_config


class Command(BaseCommand):
    help = 'Overí spojenie na Zabbix API a vypíše verziu a základné počty.'

    def handle(self, *args, **options):
        cfg = get_config()
        try:
            api = get_client()
        except ZabbixConfigError as e:
            raise CommandError(str(e))

        try:
            version = api.api_version()
            host_count = api.host.get(countOutput=True)
            problem_count = api.problem.get(countOutput=True)
        except Exception as e:
            raise CommandError(f'Zabbix API volanie zlyhalo: {e}')

        self.stdout.write(self.style.SUCCESS(f"Zabbix API OK: {cfg['api_url']}"))
        self.stdout.write(f'  verzia API:          {version}')
        self.stdout.write(f'  hostov:              {host_count}')
        self.stdout.write(f'  aktivnych problemov: {problem_count}')
