from netbox.jobs import JobRunner, system_job

from .sync import run_sync
from .zabbix import get_config, get_setting

# Bežný beh cez ~277 hostov trvá pár sekúnd — 120s dáva veľkú rezervu, no
# zároveň zaisťuje, že zaseknutý beh (napr. Zabbix API visiace na sieťovom
# probléme) sa SÁM vyrieši do 2 minút namiesto donekonečna blokovania
# CELÉHO budúceho plánovania. Dôvod: core.jobs.JobRunner.handle() naplánuje
# ďalší beh AŽ PO dobehnutí/zlyhaní toho aktuálneho (vo `finally` bloku) —
# beh bez timeoutu, ktorý sa zasekne, teda znamená ŽIADNY ďalší sync navždy
# (presne toto sa raz stalo — 9 hodín bez syncu, treba bolo ručne zmazať job).
# Bez explicitného job_timeout by platil NetBoxov globálny RQ_DEFAULT_TIMEOUT
# (default 300s) — funguje, ale ticho a mimo našej kontroly, zmenil by sa aj
# nezávisle od tohto pluginu. Overené priamo (dočasný test job cez rqworker):
# RQ job_timeout naozaj preruší visiaci beh (JobTimeoutException), NetBox ho
# korektne zaloguje ako ERRORED a AJ TAK naplánuje ďalší beh podľa intervalu.
SYNC_JOB_TIMEOUT = 120


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

    @classmethod
    def enqueue(cls, *args, **kwargs):
        # Platí pre PRVÉ naplánovanie (worker štart, cez enqueue_once) aj pre
        # každé ďalšie (JobRunner.handle() vo finally bloku volá cls.enqueue(),
        # takže táto classmethoda sa uplatní na celý reťazec opakovaní).
        kwargs.setdefault('job_timeout', SYNC_JOB_TIMEOUT)
        return super().enqueue(*args, **kwargs)

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
