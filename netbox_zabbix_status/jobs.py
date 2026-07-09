from netbox.jobs import JobRunner, system_job

from .sync import run_sync
from .zabbix import get_config, get_setting


@system_job(interval=int(get_config().get('sync_interval', 5)))
class ZabbixSyncJob(JobRunner):
    """Periodický Zabbix -> NetBox sync. Registruje sa ako system job,
    rqworker ho plánuje automaticky po štarte.

    Interval z @system_job sa použije len pri úplne prvom naplánovaní (pri
    štarte workera) — každé ďalšie opakovanie NetBox plánuje podľa `job.interval`
    uloženého na predchádzajúcom behu (core.jobs.JobRunner.handle). Preto stačí
    tu na konci behu prepísať `self.job.interval` na aktuálnu hodnotu z nastavení
    a zmena sa reťazovo prenesie do všetkých ďalších naplánovaní — bez reštartu.
    """

    class Meta:
        name = 'Zabbix sync'

    def run(self, *args, **kwargs):
        cfg = get_config()
        if not cfg.get('api_url') or not cfg.get('api_token'):
            # Nenakonfigurovaný plugin nie je chyba — job prebehne naprázdno,
            # aby Background Tasks nezaplavili errory.
            self.job.data = {'skipped': 'chýba ZABBIX_API_URL / ZABBIX_API_TOKEN'}
        else:
            self.job.data = run_sync()

        new_interval = int(get_setting('sync_interval', cfg.get('sync_interval', 5)))
        if new_interval != self.job.interval:
            self.job.interval = new_interval
            self.job.save(update_fields=['interval'])
