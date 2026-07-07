# netbox-zabbix-status

Read-only NetBox plugin: zobrazuje stav Zabbix monitoringu (hosty, dostupnosť,
aktívne problémy) pri zariadeniach a VM v NetBoxe a spája ho s NetBox metadátami
(site / tenant / rola). Do Zabbixu nikdy nezapisuje — stačí API token s právami
len na čítanie.

Návrh a plný rozsah: pozri `ZABBIX-PLUGIN-SPEC.md` v repe netbox-docker.

## Stav

- [x] M1 — skeleton: PluginConfig, modely (`ZabbixHost`, `ZabbixProblem`),
  API klient wrapper (`zabbix_utils`), `manage.py zabbix_check`
- [x] M2 — sync job + párovanie host ↔ Device/VM (`manage.py sync_zabbix`,
  system job „Zabbix sync" každých `sync_interval` minút)
- [x] M3 — panel + tab „Zabbix" na Device/VM (live problémy s Redis cache,
  fallback na DB snapshot pri nedostupnom API)
- [x] M4 — list views (Hosty, Problémy) s filtrami podľa site/tenant/roly,
  menu „Zabbix", dashboard widget, read-only REST API
  (`/api/plugins/zabbix-status/hosts/`, `/problems/`), global search
- [ ] M5 — konzistenčné pohľady + ručné párovanie

## Konfigurácia

V `PLUGINS_CONFIG["netbox_zabbix_status"]` (netbox-docker: `configuration/plugins.py`,
hodnoty cez env v `env/netbox.env`):

| Kľúč | Default | Význam |
|---|---|---|
| `api_url` | `""` | URL Zabbix API, napr. `https://zabbix.firma.sk` |
| `api_token` | `""` | Zabbix API token (read-only používateľ) |
| `web_url` | `""` | URL Zabbix UI pre deep-linky (default = `api_url`) |
| `verify_ssl` | `True` | Overovať TLS certifikát |
| `sync_interval` | `5` | Interval background syncu (minúty) |
| `cache_ttl` | `30` | TTL live cache pre device tab (sekundy) |
| `min_severity` | `2` | Minimálna severita problémov (0–5, 2 = Warning) |
| `hostname_strip_domains` | `[]` | Doménové suffixy odrezané pri párovaní mien |
| `match_by_ip` | `True` | Fallback párovanie podľa IP |
| `sync_vms` | `True` | Párovať aj na virtualization.VirtualMachine |

## Overenie spojenia

```
docker compose exec netbox ./manage.py zabbix_check
```

## Vývoj

Repo je bind-mountnuté do kontajnerov cez `docker-compose.override.yml`
v netbox-docker (editable install) — zmeny kódu sa prejavia po reštarte
kontajnera, bez rebuildu image. Rebuild treba len pri zmene závislostí.
