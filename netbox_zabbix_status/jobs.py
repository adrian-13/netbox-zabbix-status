from netbox.jobs import JobRunner, system_job

from .sync import run_sync
from .zabbix import get_config


@system_job(interval=int(get_config().get('sync_interval', 5)))
class ZabbixSyncJob(JobRunner):
    """Periodický Zabbix -> NetBox sync. Registruje sa ako system job,
    rqworker ho plánuje automaticky po štarte."""

    class Meta:
        name = 'Zabbix sync'

    def run(self, *args, **kwargs):
        cfg = get_config()
        if not cfg.get('api_url') or not cfg.get('api_token'):
            # Nenakonfigurovaný plugin nie je chyba — job prebehne naprázdno,
            # aby Background Tasks nezaplavili errory.
            self.job.data = {'skipped': 'chýba ZABBIX_API_URL / ZABBIX_API_TOKEN'}
            return
        self.job.data = run_sync()
