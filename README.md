# netbox-zabbix-status

Read-only NetBox plugin: zobrazuje stav Zabbix monitoringu (hosty, dostupnosť,
aktívne problémy) pri zariadeniach a VM v NetBoxe a spája ho s NetBox metadátami
(site / tenant / rola). Do Zabbixu nikdy nezapisuje — stačí API token s právami
len na čítanie.

[![NetBox](https://img.shields.io/badge/NetBox-4.6%2B-blue)](https://github.com/netbox-community/netbox)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Návrh a plný rozsah: pozri `ZABBIX-PLUGIN-SPEC.md` v repe netbox-docker.

## Stav

- [x] M1 — skeleton: PluginConfig, modely (`ZabbixHost`, `ZabbixProblem`),
  API klient wrapper (`zabbix_utils`), `manage.py zabbix_check`
- [x] M2 — sync job + párovanie host ↔ Device/VM (`manage.py sync_zabbix`,
  system job „Zabbix sync" každých `sync_interval` minút)
- [x] M3 — panel + tab „Zabbix" na Device/VM (live problémy s Redis cache,
  fallback na DB snapshot pri nedostupnom API) + história problémov
  (rýchle rozsahy 1h/6h/24h/7d/30d aj vlastný rozsah, priamo zo Zabbix API,
  nič sa neukladá do NetBox DB)
- [x] M4 — list views (Hosty, Problémy) s filtrami podľa site/tenant/roly,
  menu „Zabbix", dashboard widget, read-only REST API
  (`/api/plugins/zabbix-status/hosts/`, `/problems/`), global search
- [x] M5 — ručné párovanie (edit hosta → match_method=manual); nespárovaných
  hostov nájdeš filtrom `is_matched=false` v zozname Hosty (samostatné
  konzistenčné pohľady boli po zvážení odstránené — pozri Changelog)

- [x] Dashboard (menu Zabbix → Dashboard) — dlaždice problémov podľa severity,
  štatistiky dostupnosti spárovaných hostov, panely najhorších hostov
  a aktívnych problémov; auto-refresh 60 s

**v1 kompletná.** Kandidáti na v2: návrhy importu zo Zabbix inventory,
webhook receiver (problém → Journal), GraphQL.

## Konfigurácia

**Nastavenia správania sa editujú graficky v UI: menu Zabbix → Nastavenia**
(sync interval, párovanie, min. severita, cache, dashboard). Uložené hodnoty sa
držia v DB (model `ZabbixConfiguration`), majú prednosť pred PLUGINS_CONFIG a
**platia okamžite bez reštartu** — vrátane intervalu syncu: sync job si po
každom behu sám prehodnotí vlastný `Job.interval` podľa aktuálneho nastavenia
(`core.jobs.JobRunner.handle` naplánuje ďalší beh podľa tejto hodnoty, nie podľa
toho, čo bolo nastavené pri štarte workera) — najviac o jeden starý cyklus
meškania, kým sa zmena prejaví. Env/PLUGINS_CONFIG hodnoty nižšie slúžia len
ako seed default, kým sa nastavenia prvýkrát neuložia.

**Pripojenie (API URL, token) zámerne zostáva len v env**, mimo UI aj DB —
token je secret a v tomto repe (aj v netbox-docker) sa secrets riešia cez
gitignorované env súbory, nie cez databázu editovateľnú z UI; miešať API URL
do DB a token do env by rozdelilo konfiguráciu pripojenia na dve miesta bez
reálneho prínosu. Jediné, čo teda naozaj vyžaduje reštart kontajnerov
(`docker compose up -d` / `restart`), je zmena tejto skupiny:

| Kľúč | Default | Význam |
|---|---|---|
| `api_url` | `""` | URL Zabbix API, napr. `https://zabbix.firma.sk` |
| `api_token` | `""` | Zabbix API token (read-only používateľ) |
| `web_url` | `""` | URL Zabbix UI pre deep-linky (default = `api_url`) |
| `verify_ssl` | `True` | Overovať TLS certifikát |

Nastavuje sa v `PLUGINS_CONFIG["netbox_zabbix_status"]` (netbox-docker:
`configuration/plugins.py`, hodnoty cez env v `env/zabbix.env`).

Zvyšok je editovateľný v UI (Zabbix → Nastavenia), tieto kľúče slúžia len
ako seed default pred prvým uložením:

| Kľúč | Default | Význam |
|---|---|---|
| `sync_interval` | `5` | Interval background syncu (minúty) |
| `cache_ttl` | `30` | TTL live cache pre device tab (sekundy) |
| `min_severity` | `2` | Minimálna severita problémov (0–5, 2 = Warning) |
| `include_suppressed` | `False` | Zahrnúť problémy hostov v maintenance okne (Zabbix UI ich defaultne skrýva — `False` = rovnaká parita) |
| `hostname_strip_domains` | `[]` | Doménové suffixy odrezané pri párovaní mien |
| `match_by_ip` | `True` | Fallback párovanie podľa IP |
| `sync_vms` | `True` | Párovať aj na virtualization.VirtualMachine |
| `matching_enabled` | `True` | `False` = čistý Zabbix viewer: žiadne párovanie s NetBoxom — skryje panel/tab na zariadeniach, konzistenčné pohľady aj NetBox stĺpce v zoznamoch; existujúce väzby v DB zostávajú (prepnutie späť je bezstratové) |
| `dashboard_matched_only` | `True` | Dashboard zobrazuje len spárované hosty; `False` = všetky |
| `dashboard_severities` | `[]` | Severity zobrazované v dlaždiciach a paneloch dashboardu; prázdne = všetky od `min_severity` |
| `dashboard_refresh` | `60` | Auto-refresh dashboardu v sekundách (`0` = vypnutý) |

## Overenie spojenia

```
docker compose exec netbox ./manage.py zabbix_check
```

## Vývoj

Repo je bind-mountnuté do kontajnerov cez `docker-compose.override.yml`
v netbox-docker (editable install) — zmeny kódu sa prejavia po reštarte
kontajnera, bez rebuildu image. Rebuild treba len pri zmene závislostí.

## Changelog

### Unreleased
- **Zjednodušenie menu** — odstránená sekcia „Konzistencia" (Nepokryté zariadenia /
  Nepokryté VM / Nespárované hosty) aj jej pohľady; nespárovaných hostov nájdeš
  filtrom `is_matched=false` priamo v zozname Hosty (má aj akciu úpravy priradenia).
- Výber severít na dashboarde sa už edituje len na jednom mieste (gear dropdown
  na dashboarde) — odstránený z formulára Nastavení, kde predtým hrozilo tiché
  prepísanie výberu pri uložení iného nastavenia.
- **Nastavenia reagujú na „čistý Zabbix viewer" režim** — keď je `matching_enabled`
  vypnuté, formulár skryje `match_by_ip`/`sync_vms`/odrezávané domény aj
  „Dashboard len spárované hosty" (nemajú v tomto režime žiadny efekt) a vysvetlí
  prečo; ich uložené hodnoty zostávajú v DB nedotknuté, kým sa párovanie znova nezapne.
- **Interval syncu editovateľný v UI** — nový model field `sync_interval`
  (predtým len `PLUGINS_CONFIG`/env, vyžadovalo reštart); sync job si po každom
  behu sám prehodnotí `Job.interval` podľa aktuálneho nastavenia, takže zmena
  platí od najbližšieho cyklu bez reštartu kontajnerov. Pripojenie (API URL,
  token) ostáva zámerne len v env.

### v0.2.0
- **Sync a párovanie** — background job (`sync_interval` minút) ťahá hostov a problémy
  zo Zabbixu a páruje ich na Device/VM podľa uloženého ID, normalizovaného mena alebo
  jednoznačnej IP; ručné priradenia sync nikdy neprepíše.
- **Integrácia na Device/VM** — stavový panel a tab „Zabbix" s live problémami
  (cachované) a históriou problémov (1h/6h/24h/7d/30d/vlastný rozsah) priamo zo
  Zabbix API — história sa v NetBoxe neukladá.
- **Dashboard** — dlaždice podľa severity, štatistiky dostupnosti hostov, panely
  najhorších hostov a aktívnych problémov, okamžité tlačidlo „Obnoviť zo Zabbixu".
- **Zoznamy, API, konzistencia** — filtrovateľné zoznamy hostov/problémov
  (site/tenant/rola), read-only REST API, pohľady na nepokryté zariadenia/VM
  a nespárované hosty s ručným priradením.
- **Grafické nastavenia** — celé správanie (párovanie, severity, suppressed
  problémy, rozsah dashboardu) sa mení v UI (Zabbix → Nastavenia) a platí
  okamžite, bez reštartu.
