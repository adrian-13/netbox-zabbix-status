from django.db import migrations, models
from django.db.models import Count, Q


def resolve_duplicate_pairings(apps, schema_editor):
    """Existujúce duplicity (viac ZabbixHost záznamov na to isté Device/VM,
    nazbierané pred zavedením 1:1 constraintu nižšie) treba vyriešiť PRED
    pridaním UniqueConstraint, inak by migrácia zlyhala na existujúcich
    dátach. Priorita: manual > ip > name (človek > živý IP signál > menová
    zhoda), pri zhode priority vyhráva nižšie pk (staršia/pôvodnejšia
    väzba). Prehratí sa NEZMAŽÚ, len sa odpárujú (device/virtual_machine ->
    NULL, match_method -> none) — plne reverzibilné cez ručné párovanie."""
    ZabbixHost = apps.get_model('netbox_zabbix_status', 'ZabbixHost')
    priority = {'manual': 0, 'ip': 1, 'name': 2, 'none': 3}

    for field in ('device_id', 'virtual_machine_id'):
        duplicated = (
            ZabbixHost.objects.exclude(**{field: None})
            .values(field)
            .annotate(n=Count('pk'))
            .filter(n__gt=1)
        )
        for row in duplicated:
            target = row[field]
            hosts = list(ZabbixHost.objects.filter(**{field: target}))
            hosts.sort(key=lambda h: (priority.get(h.match_method, 9), h.pk))
            for loser in hosts[1:]:
                loser.device_id = None
                loser.virtual_machine_id = None
                loser.match_method = 'none'
                loser.save(update_fields=['device_id', 'virtual_machine_id', 'match_method'])


class Migration(migrations.Migration):

    dependencies = [
        ('netbox_zabbix_status', '0010_zabbixconfiguration_visible_tag_keys'),
    ]

    operations = [
        migrations.RunPython(resolve_duplicate_pairings, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='zabbixhost',
            constraint=models.UniqueConstraint(
                condition=Q(device__isnull=False),
                fields=('device',),
                name='netbox_zabbix_status_zabbixhost_unique_device',
            ),
        ),
        migrations.AddConstraint(
            model_name='zabbixhost',
            constraint=models.UniqueConstraint(
                condition=Q(virtual_machine__isnull=False),
                fields=('virtual_machine',),
                name='netbox_zabbix_status_zabbixhost_unique_virtual_machine',
            ),
        ),
    ]
