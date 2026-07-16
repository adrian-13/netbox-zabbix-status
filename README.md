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
- **Hromadné akcie „Vygenerovať tagy" a „Prepárovať" v zozname Zabbix Hostov** —
  výber viac hostov cez checkboxy (teraz prvýkrát dostupné na tomto zozname)
  a spustí buď hromadné vygenerovanie spravovaných Zabbix tagov (rovnaká
  logika ako jednohostové tlačidlo, nespárované vo výbere sa preskočia), alebo
  hromadné prepárovanie — spustí ten istý automatický matcher (meno/IP), akým
  beží periodický sync, okamžite namiesto čakania na najbližší cyklus, len pre
  vybraných hostov. Prepárovanie sa nikdy nedotkne ručne priradených ani už
  platne automaticky spárovaných hostov a rešpektuje 1:1 výhradnosť (dvaja
  vybraní hostia si nikdy neukradnú to isté zariadenie/VM).
- **Oprava: import zo Zabbixu teraz naozaj spáruje vytvorené zariadenie/VM
  s hostom** — `ZabbixHostImportView` predtým vytvorilo Device/VM (aj zápis
  tagov späť do Zabbixu), ale nikdy nenastavilo `ZabbixHost.device`/
  `virtual_machine` na novo vytvorený objekt, takže host zostal v NetBoxe
  „nespárovaný" až do najbližšieho periodického syncu (a aj vtedy len ak ho
  automatické párovanie podľa mena/IP našlo). Teraz sa spárovanie
  (`match_method=Manual`, sync ho už neprepíše) deje priamo v tej istej
  transakcii ako vytvorenie Device/VM — zlyhanie ktoréhokoľvek neskoršieho
  kroku (interface, IP) vráti späť aj spárovanie, nič neostane v
  polovičnom stave.
- **Tlačidlo „Vygenerovať Zabbix tagy" na detaile Zabbix hosta** — znovu
  zapíše spravované tagy (`nbx_siteid`/`nbx_deviceid`/`nbx_rackid` alebo
  `nbx_vmid`) podľa aktuálneho stavu spárovaného Device/VM, rovnakou
  logikou ako pri prvotnom importe. Rieši prípad, keď boli tagy odstránené
  tlačidlom „Odstrániť Zabbix tagy" (alebo priamo v Zabbixe) a treba ich
  bez opakovaného importu obnoviť. Viditeľné len pri spárovanom hostovi.
- **Tlačidlo „Pridať vlastný tag" na detaile Zabbix hosta** — modálne okno
  na zápis ĽUBOVOĽNÉHO tagu (kľúč+hodnota) priamo do Zabbixu, nad rámec
  tých, čo plugin spravuje automaticky. Kľúč zhodný so spravovaným tagom
  (`nbx_siteid` a pod.) je zámerne odmietnutý — tie sa menia výhradne cez
  „Vygenerovať"/„Odstrániť", aby si obe cesty ticho neprepisovali hodnoty.
  Funguje aj na nespárovanom hostovi. Detail hosta teraz zobrazuje aj
  zoznam aktuálnych Zabbix tagov (rovnaké odznaky ako v zozname Hostov).

### v0.5.0
- **Stĺpec „Zabbix" a filter „Spárované so Zabbixom" aj na natívnom zozname
  Virtual Machines** — rovnaká funkcia ako na natívnom zozname Device (v0.4.0):
  ikona (zelený fajka = spárované, klikateľná na Zabbix hosta; šedý krížik =
  nespárované), triediteľná cez vlastnú `Exists()` subquery logiku (nie
  priamy `.order_by()`/`.filter()` na reverse FK — pri VM s viacerými
  ZabbixHost záznamami by to duplikovalo riadky rovnako ako pri Device) a
  filter „Spárované so Zabbixom" vo Filters tabe. Default skrytý stĺpec,
  zapneš cez „Configure Table".
- **Zápis NetBox identifikátorov späť do Zabbixu pri importe (Device aj VM)** —
  po vytvorení zariadenia alebo virtuálneho stroja cez import (tlačidlo „+")
  sa do Zabbix hosta zapíšu tagy s ID zodpovedajúceho NetBox objektu:
  `nbx_siteid` (oba typy, rovnaký konfigurovateľný kľúč ako pri čítaní —
  `ZabbixConfiguration.site_id_tag_key`), `nbx_deviceid`+`nbx_rackid`
  (len Device), `nbx_vmid` (len VM). Existujúci tag sa prepíše, chýbajúci sa
  pridá; ostatné tagy hosta (napr. `class`, `vendor`) ostávajú nedotknuté.
  `nbx_rackid` sa vynechá, ak zariadenie nemá priradený rack; pre VM sa
  nezapisuje vôbec (rack ako koncept na VM neexistuje). JEDINÉ miesto v
  pluginu, ktoré do Zabbixu zapisuje — inde je plugin výhradne read-only.
  Zlyhanie zápisu (napr. sieť, oprávnenia) nezablokuje ani nevráti už
  vytvorený objekt v NetBoxe, len sa zobrazí varovanie.
- **Tlačidlo „Odstrániť Zabbix tagy" na detaile Zabbix hosta** — inverzná
  operácia k vyššie, cez NetBox modálne okno (nie JS `confirm()`): zoznam
  checkboxov s tagmi hosta, ktoré plugin vie zapisovať (`nbx_siteid`/
  `nbx_deviceid`/`nbx_rackid`/`nbx_vmid`, aj keby ich reálne nastavila iná integrácia),
  všetky defaultne zaškrtnuté — odškrtnutím vyberieš, ktoré ostanú. Zoznam
  sa načíta live priamo zo Zabbix API (nie zo starého DB snapshotu), takže
  aj tagy zapísané tesne predtým tým istým importom sa hneď ponúknu na
  odstránenie. Tlačidlo aj modál sa vôbec nezobrazia, ak host nemá žiadny
  takýto tag alebo používateľ nemá oprávnenie „Edit". Odstránia sa len
  vybrané tagy (aj pri neúplnom výbere), ostatné tagy hosta (`class`,
  `vendor`, ...) ostávajú nedotknuté; odoslanie bez výberu nič nezmení.
  Server-side vždy prefiltruje odoslané kľúče len na spravovanú množinu —
  aj pri ručne upravenom POST sa nedá odstrániť nič mimo nej.

### v0.4.0
- **Stĺpec „Zabbix" v natívnom NetBox zozname Device** — ikona (zelený fajka
  = spárované, klikateľná na príslušný Zabbix host v NetBoxe; šedý krížik =
  nespárované), bez textu kvôli úspore miesta. Pridané
  cez `utilities.tables.register_table_column()` (oficiálne NetBox API na
  rozšírenie core tabuliek pluginmi), nie prepisovaním `dcim.tables.DeviceTable`.
  Default skrytý (mimo nášho pluginu je, čo NetBox zobrazuje defaultne na
  vlastnej core tabuľke) — zapneš cez „Configure Table" na zozname Device.
  Dá sa aj triediť (kliknutím na hlavičku) a filtrovať (nové pole „Spárované
  so Zabbixom" v „Filters" tabe zoznamu Device) — obe cez bezpečný `Exists()`
  korelovaný subquery, nie priamy join na reverse FK vzťah (ten by pri
  zariadení s viacerými ZabbixHost záznamami — v tomto prostredí sa to reálne
  stáva — duplikoval riadky zariadenia vo výsledku). NetBox nemá oficiálne
  API na pridanie filtra do core FilterSetu (na rozdiel od stĺpcov), preto
  ide o priame rozšírenie `dcim.filtersets.DeviceFilterSet`/
  `dcim.forms.filtersets.DeviceFilterForm` z pluginu.
- **Oprava: zaseknutý sync job sa teraz sám vyrieši** — periodický „Zabbix sync"
  naplánuje ďalší beh AŽ PO dobehnutí/zlyhaní toho aktuálneho
  (`core.jobs.JobRunner.handle`) — ak sa beh niekedy zasekne (napr. visiace
  Zabbix API pri sieťovom probléme) bez časového limitu, žiadny ďalší sync sa
  už nikdy nenaplánuje (presne toto sa stalo — 9 hodín bez syncu, treba bolo
  ručne zmazať job a spustiť ručné obnovenie). `ZabbixSyncJob` má teraz
  explicitný `job_timeout=120s` (predtým platil len tichý NetBoxov globálny
  default 300s, mimo kontroly pluginu) — zaseknutý beh sa zabije do 2 minút
  a ďalší sync sa aj tak korektne naplánuje. Overené priamo cez rqworker
  (dočasný test job), že RQ timeout skutočne preruší visiaci beh a
  naplánovanie pokračuje ďalej. Existujúce upozornenie na dashboarde
  („Dáta môžu byť neaktuálne") zostáva ako druhá poistka pre prípad zlyhania
  mimo jedného behu (napr. pád workera).
- **Oprava: sync už nezapĺňa globálny NetBox Changelog** — `ZabbixHost`/
  `ZabbixProblem` sú `NetBoxModel`, takže každé prepísanie počas syncu
  (`last_synced`, `problem_count`, availability...) sa logovalo ako
  `ObjectChange`. Periodický sync job to nespôsoboval (beží mimo request
  kontextu, NetBox tam logovanie automaticky vynecháva), ale ručné tlačidlo
  „Obnoviť zo Zabbixu" áno — bežalo v request kontexte, takže každé kliknutie
  vytvorilo jeden záznam na hosta. V tejto inštalácii tak za 2 dni vzniklo
  7402 z celkových 15542 (~48 %) všetkých `ObjectChange` záznamov v NetBoxe.
  `sync.run_sync()` teraz počas zápisu dočasne vypne request kontext, presne
  ako pri periodickom jobe — dáta sa aktualizujú rovnako, len sa nezaznamenajú
  do auditu. `ZabbixConfiguration`'s Changelog (nižšie) tým nie je dotknutý.
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
  dashboard hosta priamo v Zabbixe (`ZabbixHost.get_zabbix_url()`). V zozname
  Hosty sedí „Otvoriť v Zabbixe" (holá ikona) v akčnej bunke hneď vedľa import
  „+" tlačidla (cez `ActionsColumn.extra_buttons`), nie ako samostatný stĺpec;
  v zozname Problémy zostáva ako vlastný stĺpec (holá ikona, tam nie je „+").
- **Import nespárovaného hosta ako nové zariadenie/VM** — nová ikona pri
  nespárovaných hostoch v zozname Hosty (viditeľná len bez existujúcej väzby
  a s oprávnením na pridanie Device alebo VM) vedie na stránku s dvomi
  kombinovanými formulármi „Vytvoriť ako zariadenie" / „Vytvoriť ako
  virtuálny stroj" — každý postavený zo stock NetBox formulárov (DeviceForm/
  VirtualMachineForm + InterfaceForm/VMInterfaceForm + IPAddressForm),
  predvyplnené menom, comments so súhrnom zo Zabbixu a prípadne odhadnutou
  Site. Jedno kliknutie na Uložiť vytvorí v jednej transakcii zariadenie/VM
  **aj** loopback rozhranie (`type=virtual`) so SNMP IP adresou zo Zabbixu,
  nastavenou rovno ako primárna IP (`IPAddressForm.primary_for_parent`) —
  vymazanie IP adresy pred odoslaním vytvorí len samotné zariadenie/VM bez
  rozhrania. Typ zariadenia/rolu (a ostatné povinné polia) človek doplní
  a formulár uloží sám — nič sa nezapisuje automaticky, rovnaká „human
  confirms" filozofia ako pri ručnom párovaní. Keď má používateľ oprávnenie
  na oba typy, formuláre „Zariadenie"/„VM" sa zobrazujú v taboch (nie pod
  sebou), aby dva dlhé formuláre nebolo treba prescrollovať. Súhrn Zabbix
  hosta (atribúty + interfejsy) je nad formulármi ako kompaktný pás na celú
  šírku, nie vo vedľajšom stĺpci — ten pri dlhom formulári zanechával veľkú
  prázdnu plochu. Polia formulára Zariadenie sú zoskupené do rovnakých
  sekcií ako natívna NetBox stránka Add Device (Hardvér, Umiestnenie, Správa,
  Virtualizácia, Nájomník, Virtuálne šasi, Vlastník, ...) — `DeviceForm` totiž
  na rozdiel od `VirtualMachineForm` nemá vlastné `fieldsets`, natívna stránka
  si skupiny skladá ručne v šablóne, takže bez tejto úpravy sa všetky polia
  zobrazovali ako jeden plochý zoznam. Formulár má aj rovnakú šírku ako
  natívne Add Device/Add VM stránky (trieda `object-edit`, max. 800px), nie
  na celú šírku stránky. Pole Latitude/Longitude v zariadení sa predvyplní
  GPS súradnicami z Zabbix host inventory (`location_lat`/`location_lon`),
  ak ich host má vyplnené — číta sa priamo zo Zabbix API pri otvorení
  stránky (nepretrváva sa v DB, rovnako ako história problémov), zaokrúhlené
  na 6 desatinných miest podľa limitu `Device.latitude`/`longitude`. Ikona
  „+" je plnofarebné tlačidlo (`btn btn-primary`), rovnaký vzor ako natívne
  Edit/Delete tlačidlá — automaticky teda použije aj NetBoxovu vlastnú teal
  farbu (tmavý aj svetlý režim) — a sedí hneď vedľa tlačidla Edit v akčnom
  stĺpci (cez `ActionsColumn.extra_buttons`, rovnako ako VLANGROUP_BUTTONS
  v NetBox core), nie ako samostatný stĺpec. Pole Site sa navyše
  vie predvyplniť aj priamo z explicitného Zabbix host tagu (default kľúč
  `nbx_siteid`, konfigurovateľné v Zabbix → Nastavenia → „Import zo Zabbixu"),
  ktorého hodnota je priamo NetBox Site ID — napr. tag `nbx_siteid=63` znamená
  Site pk 63. Má prednosť pred starším odhadom podľa mena host group
  (`_guess_site()`, ktorý v tomto prostredí prakticky nikdy netrafí, keďže
  Zabbix host groups sú organizačné kategórie a NetBox Site mená fyzické
  adresy) — tag je totiž explicitný krížový odkaz nastavený človekom, nie
  odhad. Prázdny kľúč tagu vypína funkciu úplne (padá späť na pôvodné
  správanie). Tag sa číta z `ZabbixHost.zabbix_tags` (pozri nižšie — synced
  pri pravidelnom syncu, rovnako ako host groups/šablóny), nie live dopytom;
  GPS zostáva jediná vec, ktorá sa pri otvorení importnej stránky ťahá live
  (`zabbix.get_host_inventory()`).
- **Zabbix tagy ako stĺpec v zozname Hosty** — host-level tagy (`selectTags`
  na `host.get`, napr. `nbx_siteid: 63`) sa teraz synchronizujú do nového
  poľa `ZabbixHost.zabbix_tags` (rovnakým mechanizmom ako host groups a
  šablóny — pri pravidelnom syncu, nie live), zobrazené ako odznaky v novom
  stĺpci „Zabbix tagy" (default zapnutý). Umožňuje napr. skontrolovať, či má
  host nastavený `nbx_siteid` tag pre import (vyššie), bez nutnosti chodiť
  do Zabbixu. Dostupné aj cez REST API (`ZabbixHostSerializer`).
- **Výber zobrazovaných Zabbix tagov** — pri hostoch s viacerými tagmi (`class`,
  `vendor`, `olt`, ...) stĺpec „Zabbix tagy" rýchlo zaberie veľa miesta. Ikona
  vedľa „Configure Table" (nie v hlavičke stĺpca — tá je v scrollovacom
  kontajneri, dropdown by sa mohol orezať; ani vedľa Export v hornej lište —
  odtrhnuté od tabuľky) otvorí dropdown so zoznamom všetkých reálne
  použitých tag kľúčov (dynamicky, nie pevný zoznam), zaškrtneš len tie, čo
  chceš vidieť. Prázdny výber = zobraziť všetky (default). Filtruje len
  zobrazenie (`ZabbixHost.display_tags`) — surové `zabbix_tags` ostávajú
  netknuté. Nastavenie (`ZabbixConfiguration.visible_tag_keys`) sa needituje
  na stránke Nastavenia, len cez tento dropdown (rovnaká filozofia ako
  `dashboard_severities`).

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
