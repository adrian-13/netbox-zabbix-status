# netbox-zabbix-status

Read-only NetBox plugin: zobrazuje stav Zabbix monitoringu (hosty, dostupnosť,
aktívne problémy) pri zariadeniach a VM v NetBoxe a spája ho s NetBox metadátami
(site / tenant / rola). Do Zabbixu nikdy nezapisuje — stačí API token s právami
len na čítanie.

[![NetBox](https://img.shields.io/badge/NetBox-4.6%2B-blue)](https://github.com/netbox-community/netbox)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Návrh a plný rozsah: pozri `ZABBIX-PLUGIN-SPEC.md` v repe netbox-docker.

## Požiadavky

| Závislosť | Verzia |
|---|---|
| NetBox | 4.6 alebo novší |
| Python | 3.10 alebo novší |
| zabbix_utils | ≥ 2.0 |
| Redis + RQ worker | Štandardná NetBox požiadavka (`netbox-worker`/`netbox-rq` služba) |

> **Dôležité:** RQ worker musí bežať — periodický sync („Zabbix sync" system job)
> aj tlačidlo „Obnoviť zo Zabbixu" bez neho nikdy neprebehnú.

## Inštalácia

### Do netbox-docker (spôsob použitý v tomto nasadení)

Repo sa pridáva ako sibling adresár vedľa `netbox-docker` a napojí sa cez
`docker-compose.override.yml` (rovnaký vzor ako pri iných lokálnych pluginoch):

```bash
# 1. Naklonuj plugin ako sibling repo vedľa netbox-docker
cd ..
git clone https://github.com/adrian-13/netbox-zabbix-status.git netbox-plugin-zabbix-status
cd netbox-docker
```

V `docker-compose.override.yml` pridaj (alebo rozšír existujúce `netbox`/
`netbox-worker` služby o) build a bind-mount:

```yaml
services:
  netbox:
    image: netbox-zabbix-status:dev
    pull_policy: never
    build:
      context: ../netbox-plugin-zabbix-status
      dockerfile: Dockerfile
      args:
        # Priamo na oficiálny image — ak reťazíš viac lokálnych pluginov,
        # nastav sem miesto toho výsledný image predchádzajúceho pluginu
        NETBOX_IMAGE: netboxcommunity/netbox:v4.6-5.0.1
    env_file:
      - path: env/zabbix.env
        required: false
    volumes:
      - ../netbox-plugin-zabbix-status:/opt/netbox-plugin-zabbix-status
  netbox-worker:
    image: netbox-zabbix-status:dev
    pull_policy: never
    env_file:
      - path: env/zabbix.env
        required: false
    volumes:
      - ../netbox-plugin-zabbix-status:/opt/netbox-plugin-zabbix-status
```

V `configuration/plugins.py`:

```python
from os import environ

PLUGINS = ["netbox_zabbix_status"]

PLUGINS_CONFIG = {
    "netbox_zabbix_status": {
        "api_url": environ.get("ZABBIX_API_URL", ""),
        "api_token": environ.get("ZABBIX_API_TOKEN", ""),
        "web_url": environ.get("ZABBIX_WEB_URL", ""),  # deep-linky; default = api_url
        "verify_ssl": environ.get("ZABBIX_VERIFY_SSL", "true").lower() == "true",
    },
}
```

Vytvor `env/zabbix.env` (drž ho mimo gitu — obsahuje secret) s read-only API
tokenom zo Zabbixu (*Users → API tokens*):

```
ZABBIX_API_URL=https://zabbix.example.com
ZABBIX_API_TOKEN=<read-only API token>
ZABBIX_WEB_URL=
ZABBIX_VERIFY_SSL=true
```

Postav image a nahoď kontajnery — migrácie aplikuje entrypoint automaticky:

```bash
docker compose build netbox
docker compose up -d
```

### Iná NetBox inštalácia (mimo Docker)

```bash
source /opt/netbox/venv/bin/activate
pip install git+https://github.com/adrian-13/netbox-zabbix-status.git@v0.3.0
```

V `configuration.py`:

```python
PLUGINS = ["netbox_zabbix_status"]

PLUGINS_CONFIG = {
    "netbox_zabbix_status": {
        "api_url": "https://zabbix.example.com",
        "api_token": "<read-only API token>",
    },
}
```

```bash
cd /opt/netbox/netbox
python manage.py migrate
python manage.py collectstatic --no-input
sudo systemctl restart netbox netbox-rq
```

### Overenie inštalácie

```bash
# Migrácie — všetkých 5 (rastie s verziou) musí byť [X]
docker compose exec netbox ./manage.py showmigrations netbox_zabbix_status

# Spojenie na Zabbix API — vypíše verziu, počet hostov a problémov
docker compose exec netbox ./manage.py zabbix_check
```

V NetBox navigácii by sa mala objaviť položka **Zabbix** (Dashboard, Hosty,
Problémy, Nastavenia) a po prvom synce panel + tab „Zabbix" na spárovaných
zariadeniach/VM. Všetky nastavenia správania (párovanie, severity, interval
syncu…) sa potom dolaďujú graficky v **Zabbix → Nastavenia** — pozri sekciu
[Konfigurácia](#konfigurácia) nižšie.

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
  konzistenčné pohľady boli po zvážení odstránené — pozri Changelog); tí istí
  nespárovaní hostia majú aj ikonu rýchleho importu do predvyplneného
  formulára Add Device/VM (pozri Changelog)

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
| `matching_enabled` | `True` | `False` = čistý Zabbix viewer: sync prestane vytvárať nové väzby, dashboard prepne na pohľad na všetky hosty (bez štatistiky spárovania), Nastavenia skryjú párovacie pod-voľby a v zoznamoch Hosty/Problémy sa zmenia default stĺpce (po reštarte); panel/tab „Zabbix" na Device/VM sa naďalej riadi len tým, či objekt má spárovaný ZabbixHost — týmto prepínačom sa neskrýva; existujúce väzby v DB zostávajú (prepnutie späť je bezstratové) |
| `dashboard_matched_only` | `True` | Dashboard zobrazuje len spárované hosty; `False` = všetky |
| `dashboard_severities` | `[]` | Severity zobrazované v dlaždiciach a paneloch dashboardu; prázdne = všetky od `min_severity` |
| `dashboard_refresh` | `60` | Auto-refresh dashboardu v sekundách (`0` = vypnutý) |

## Vývoj

Pozri vyššie sekciu **Inštalácia → Do netbox-docker** pre kompletný recept.
Repo je bind-mountnuté do kontajnerov cez `docker-compose.override.yml`
v netbox-docker (editable install) — zmeny kódu sa prejavia po reštarte
kontajnera, bez rebuildu image. Rebuild treba len pri zmene závislostí
(`pyproject.toml`).

## Changelog

### Unreleased
- **Changelog pre nastavenia pluginu** — `ZabbixConfiguration` je teraz `NetBoxModel`
  (predtým plain model bez auditu); uloženie v Zabbix → Nastavenia vytvára
  `ObjectChange` záznam (kto/kedy/z akej hodnoty na akú), dostupný cez nové
  tlačidlo „Changelog" na stránke nastavení.
- **Oprava: panel/tab „Zabbix" na Device/VM už nezávisí od `matching_enabled`** —
  vypnutie „Párovanie s NetBoxom" predtým skrylo panel aj tab aj na zariadeniach,
  ktoré už mali platnú väzbu na ZabbixHost (automatickú aj ručnú). Viditeľnosť je
  teraz daná výhradne existenciou spárovaného hosta pre daný objekt;
  `matching_enabled` naďalej ovplyvňuje len sync job (nové automatické väzby) a
  agregované pohľady (dashboard, sub-voľby v Nastaveniach).
- **História problémov aj na detaile Zabbix hosta** (Zabbix → Hosty → detail) —
  rovnaká karta ako na Device/VM tabe (rýchle rozsahy 1h/6h/24h/7d/30d + vlastný
  UTC rozsah), teraz zdieľaná cez `inc/history_card.html`, aby obe miesta
  nemohli vizuálne rozísť.
- **Priamy odkaz na problém v Zabbixe** — ikona pri každom probléme (tab
  zariadenia, história, detail hosta, dashboard, zoznam Problémy) otvorí presne
  ten problém priamo v Zabbixe (`tr_events.php`, rovnaký formát ako makro
  `{EVENT.URL}`). Vyžaduje `zabbix_triggerid` na `ZabbixProblem` (migrácia 0007,
  doplní sa pri najbližšom synce).
- **Priamy odkaz na hosta v Zabbixe aj v zozname Hosty** — rovnaká ikona otvorí
  dashboard hosta priamo v Zabbixe (`ZabbixHost.get_zabbix_url()`).
- **Import nespárovaného hosta ako nové zariadenie/VM** — nová ikona pri
  nespárovaných hostoch v zozname Hosty (viditeľná len bez existujúcej väzby
  a s oprávnením na pridanie Device alebo VM) vedie na stránku so súhrnom
  Zabbix hosta a dvomi tlačidlami „Vytvoriť ako zariadenie" / „Vytvoriť ako
  virtuálny stroj". Oba odkazujú na stock NetBox formuláre Add Device / Add
  VM, predvyplnené cez query string (meno, comments so súhrnom zo Zabbixu
  vrátane interfejsov, prípadne odhadnutá Site podľa zhody host group ↔ meno
  Site). Nič sa nezapisuje automaticky — typ zariadenia/rolu (a ostatné
  povinné polia) človek doplní a formulár uloží sám, rovnaká „human confirms"
  filozofia ako pri ručnom párovaní.

### v0.3.0
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
