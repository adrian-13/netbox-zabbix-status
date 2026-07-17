# netbox-zabbix-status

Read-only NetBox plugin: displays Zabbix monitoring status (hosts, availability,
active problems) on devices and VMs in NetBox and ties it to NetBox metadata
(site / tenant / role). Never writes to Zabbix — a read-only API token is enough.

[![NetBox](https://img.shields.io/badge/NetBox-4.6%2B-blue)](https://github.com/netbox-community/netbox)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Design and full scope: see `ZABBIX-PLUGIN-SPEC.md` in the netbox-docker repo.

## Requirements

| Dependency | Version |
|---|---|
| NetBox | 4.6 or newer |
| Python | 3.10 or newer |
| zabbix_utils | ≥ 2.0 |
| Redis + RQ worker | Standard NetBox requirement (`netbox-worker`/`netbox-rq` service) |

> **Important:** the RQ worker must be running — neither the periodic sync
> ("Zabbix sync" system job) nor the "Refresh from Zabbix" button will ever
> run without it.

## Installation

### Into netbox-docker (the approach used in this deployment)

The repo is added as a sibling directory next to `netbox-docker` and wired in
via `docker-compose.override.yml` (the same pattern used for other local
plugins):

```bash
# 1. Clone the plugin as a sibling repo next to netbox-docker
cd ..
git clone https://github.com/adrian-13/netbox-zabbix-status.git netbox-plugin-zabbix-status
cd netbox-docker
```

In `docker-compose.override.yml`, add (or extend the existing `netbox`/
`netbox-worker` services with) a build and bind-mount:

```yaml
services:
  netbox:
    image: netbox-zabbix-status:dev
    pull_policy: never
    build:
      context: ../netbox-plugin-zabbix-status
      dockerfile: Dockerfile
      args:
        # Points directly at the official image — if you're chaining multiple
        # local plugins, set this to the resulting image of the previous
        # plugin instead
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

In `configuration/plugins.py`:

```python
from os import environ

PLUGINS = ["netbox_zabbix_status"]

PLUGINS_CONFIG = {
    "netbox_zabbix_status": {
        "api_url": environ.get("ZABBIX_API_URL", ""),
        "api_token": environ.get("ZABBIX_API_TOKEN", ""),
        "web_url": environ.get("ZABBIX_WEB_URL", ""),  # deep links; defaults to api_url
        "verify_ssl": environ.get("ZABBIX_VERIFY_SSL", "true").lower() == "true",
    },
}
```

Create `env/zabbix.env` (keep it out of git — it contains a secret) with a
read-only API token from Zabbix (*Users → API tokens*):

```
ZABBIX_API_URL=https://zabbix.example.com
ZABBIX_API_TOKEN=<read-only API token>
ZABBIX_WEB_URL=
ZABBIX_VERIFY_SSL=true
```

Build the image and bring up the containers — migrations are applied
automatically by the entrypoint:

```bash
docker compose build netbox
docker compose up -d
```

### Other NetBox installation (non-Docker)

```bash
source /opt/netbox/venv/bin/activate
pip install git+https://github.com/adrian-13/netbox-zabbix-status.git@v0.3.0
```

In `configuration.py`:

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

### Verifying the installation

```bash
# Migrations — all 5 (grows with version) must show [X]
docker compose exec netbox ./manage.py showmigrations netbox_zabbix_status

# Connection to the Zabbix API — prints version, host count, and problem count
docker compose exec netbox ./manage.py zabbix_check
```

A **Zabbix** entry (Dashboard, Hosts, Problems, Settings) should appear in the
NetBox navigation, and after the first sync a panel and "Zabbix" tab should
appear on matched devices/VMs. All behavior settings (matching, severity,
sync interval…) can then be fine-tuned graphically under **Zabbix → Settings**
— see the [Configuration](#configuration) section below.

## Status

- [x] M1 — skeleton: PluginConfig, models (`ZabbixHost`, `ZabbixProblem`),
  API client wrapper (`zabbix_utils`), `manage.py zabbix_check`
- [x] M2 — sync job + host ↔ Device/VM matching (`manage.py sync_zabbix`,
  "Zabbix sync" system job every `sync_interval` minutes)
- [x] M3 — "Zabbix" panel and tab on Device/VM (live problems with Redis
  cache, falls back to a DB snapshot when the API is unavailable) + problem
  history (quick ranges 1h/6h/24h/7d/30d plus a custom range, straight from
  the Zabbix API, nothing is stored in the NetBox DB)
- [x] M4 — list views (Hosts, Problems) with filters by site/tenant/role,
  "Zabbix" menu, dashboard widget, read-only REST API
  (`/api/plugins/zabbix-status/hosts/`, `/problems/`), global search
- [x] M5 — manual matching (edit host → match_method=manual); unmatched
  hosts can be found via the `is_matched=false` filter in the Hosts list
  (separate consistency views were removed after reconsideration — see
  Changelog); those same unmatched hosts also have a quick-import icon
  leading to a pre-filled Add Device/VM form (see Changelog)

- [x] Dashboard (menu Zabbix → Dashboard) — problem tiles by severity,
  availability statistics for matched hosts, panels of worst hosts and
  active problems; auto-refresh every 60 s

**v1 complete.** Candidates for v2: proposed imports from Zabbix inventory,
webhook receiver (problem → Journal), GraphQL.

## Configuration

**Behavior settings are edited graphically in the UI: menu Zabbix → Settings**
(sync interval, matching, minimum severity, cache, dashboard). Saved values
are kept in the DB (`ZabbixConfiguration` model), take precedence over
PLUGINS_CONFIG, and **apply immediately without a restart** — including the
sync interval: after every run, the sync job re-evaluates its own
`Job.interval` based on the current setting (`core.jobs.JobRunner.handle`
schedules the next run based on this value, not on what was set when the
worker started) — at most one stale cycle of delay before the change takes
effect. The env/PLUGINS_CONFIG values below only serve as a seed default
until the settings are saved for the first time.

**The connection (API URL, token) intentionally stays in env only**, outside
both the UI and the DB — the token is a secret, and in this repo (as in
netbox-docker) secrets are handled via gitignored env files, not via a
database editable from the UI; splitting the API URL into the DB and the
token into env would split the connection configuration across two places
with no real benefit. The only thing that actually requires a container
restart (`docker compose up -d` / `restart`) is a change to this group:

| Key | Default | Meaning |
|---|---|---|
| `api_url` | `""` | Zabbix API URL, e.g. `https://zabbix.company.com` |
| `api_token` | `""` | Zabbix API token (read-only user) |
| `web_url` | `""` | Zabbix UI URL for deep links (defaults to `api_url`) |
| `verify_ssl` | `True` | Verify TLS certificate |

Set in `PLUGINS_CONFIG["netbox_zabbix_status"]` (netbox-docker:
`configuration/plugins.py`, values via env in `env/zabbix.env`).

The rest is editable in the UI (Zabbix → Settings); these keys only serve as
a seed default before the first save:

| Key | Default | Meaning |
|---|---|---|
| `sync_interval` | `5` | Background sync interval (minutes) |
| `cache_ttl` | `30` | Live cache TTL for the device tab (seconds) |
| `min_severity` | `2` | Minimum problem severity (0–5, 2 = Warning) |
| `include_suppressed` | `False` | Include problems for hosts in a maintenance window (the Zabbix UI hides these by default — `False` = same parity) |
| `hostname_strip_domains` | `[]` | Domain suffixes stripped when matching names |
| `match_by_ip` | `True` | Fallback matching by IP |
| `sync_vms` | `True` | Also match against virtualization.VirtualMachine |
| `matching_enabled` | `True` | `False` = pure Zabbix viewer: sync stops creating new links, the dashboard switches to a view of all hosts (without matching statistics), Settings hides the matching sub-options, and the default columns change in the Hosts/Problems lists (after a restart); the "Zabbix" panel/tab on Device/VM continues to be governed solely by whether the object has a matched ZabbixHost — this toggle does not hide it; existing links in the DB are preserved (toggling back is lossless) |
| `dashboard_matched_only` | `True` | Dashboard shows only matched hosts; `False` = all |
| `dashboard_severities` | `[]` | Severities shown in the dashboard tiles and panels; empty = all from `min_severity` up |
| `dashboard_refresh` | `60` | Dashboard auto-refresh in seconds (`0` = disabled) |

## Development

See the **Installation → Into netbox-docker** section above for the full
recipe. The repo is bind-mounted into the containers via
`docker-compose.override.yml` in netbox-docker (editable install) — code
changes take effect after a container restart, without an image rebuild. A
rebuild is only needed when dependencies change (`pyproject.toml`).

## Changelog

### Unreleased
- **Plugin UI fully translated to English** — every user-facing string
  (form labels and help text, flash messages, table column headers, menu
  items, dashboard widget, management command output, and all templates)
  is now in English instead of Slovak, matching the convention of most
  NetBox community plugins. Python `#` comments and `"""docstrings"""`
  intentionally stay in Slovak (developer-facing notes for this plugin's
  author, not part of the UI). This README is now written in English too.

### v0.6.0
- **1:1 matching — a single device/VM can no longer be matched to two Zabbix
  hosts at once** — DB constraint (a Device/VM may be the target of at most
  one `ZabbixHost` record), a one-time resolution of existing duplicates
  (accumulated historically when devices were renamed — sync never
  re-verified an automatic match once it had first found it), and a fix to
  both the matcher and manual matching so that a new duplicate can never
  arise again. Manually assigning a device/VM that already has another
  Zabbix host now returns a clear error in the form instead of crashing.
- **Bulk actions "Generate tags" and "Rematch" in the Zabbix Hosts list** —
  select multiple hosts via checkboxes (now available on this list for the
  first time) and trigger either a bulk generation of managed Zabbix tags
  (same logic as the single-host button, unmatched hosts in the selection
  are skipped), or bulk rematching — runs the same automatic matcher
  (name/IP) that the periodic sync uses, immediately instead of waiting for
  the next cycle, but only for the selected hosts. Rematching never touches
  manually assigned hosts or hosts already validly auto-matched, and
  respects 1:1 exclusivity (two selected hosts can never steal the same
  device/VM from each other).
- **Fix: importing from Zabbix now actually matches the created device/VM
  to the host** — `ZabbixHostImportView` previously created the Device/VM
  (and wrote tags back to Zabbix), but never set `ZabbixHost.device`/
  `virtual_machine` to the newly created object, so the host remained
  "unmatched" in NetBox until the next periodic sync (and even then only if
  automatic name/IP matching found it). The matching
  (`match_method=Manual`, sync will no longer overwrite it) now happens in
  the very same transaction as the Device/VM creation — a failure in any
  later step (interface, IP) rolls back the matching too, nothing is left
  in a half-done state.
- **"Generate Zabbix tags" button on the Zabbix host detail page** — writes
  the managed tags (`nbx_siteid`/`nbx_deviceid`/`nbx_rackid` or `nbx_vmid`)
  back based on the current state of the matched Device/VM, using the same
  logic as the initial import. Handles the case where tags were removed via
  the "Remove Zabbix tags" button (or directly in Zabbix) and need to be
  restored without repeating the import. Visible only for a matched host.
- **"Add custom tag" button on the Zabbix host detail page** — a modal for
  writing ANY tag (key+value) directly to Zabbix, beyond the ones the
  plugin manages automatically. A key matching a managed tag
  (`nbx_siteid` etc.) is intentionally rejected — those are only changed via
  "Generate"/"Remove", so the two paths don't silently overwrite each
  other's values. Also works on an unmatched host. The host detail page now
  also shows a list of the current Zabbix tags (same badges as in the Hosts
  list).

### v0.5.0
- **"Zabbix" column and "Matched with Zabbix" filter on the native Virtual
  Machines list too** — same feature as on the native Device list (v0.4.0):
  an icon (green checkmark = matched, clickable through to the Zabbix host;
  gray cross = unmatched), sortable via a custom `Exists()` subquery (not a
  direct `.order_by()`/`.filter()` on the reverse FK — with a VM that has
  multiple ZabbixHost records this would duplicate rows just like on
  Device), and a "Matched with Zabbix" filter in the Filters tab. Hidden by
  default column, enable it via "Configure Table".
- **Writing NetBox identifiers back to Zabbix on import (both Device and
  VM)** — after creating a device or virtual machine via import (the "+"
  button), tags are written onto the Zabbix host with the ID of the
  corresponding NetBox object: `nbx_siteid` (both types, same configurable
  key used for reading — `ZabbixConfiguration.site_id_tag_key`),
  `nbx_deviceid`+`nbx_rackid` (Device only), `nbx_vmid` (VM only). An
  existing tag is overwritten, a missing one is added; other tags on the
  host (e.g. `class`, `vendor`) are left untouched. `nbx_rackid` is omitted
  if the device has no assigned rack; for VMs it is never written at all
  (rack isn't a concept that applies to VMs). This is the ONLY place in the
  plugin that writes to Zabbix — everywhere else the plugin is strictly
  read-only. A write failure (e.g. network, permissions) does not block or
  roll back the object already created in NetBox, it just shows a warning.
- **"Remove Zabbix tags" button on the Zabbix host detail page** — the
  inverse operation of the above, via a NetBox modal (not a JS `confirm()`):
  a list of checkboxes with the host's tags that the plugin knows how to
  write (`nbx_siteid`/`nbx_deviceid`/`nbx_rackid`/`nbx_vmid`, even if they
  were actually set by another integration), all checked by default —
  uncheck to choose which ones stay. The list is loaded live directly from
  the Zabbix API (not from an old DB snapshot), so even tags written just
  moments earlier by the same import are immediately offered for removal.
  The button and modal don't appear at all if the host has none of these
  tags or the user lacks "Edit" permission. Only the selected tags are
  removed (even with a partial selection), other tags on the host (`class`,
  `vendor`, ...) are left untouched; submitting with nothing selected
  changes nothing. The server side always filters the submitted keys down
  to the managed set — even with a manually crafted POST, nothing outside
  that set can be removed.

### v0.4.0
- **"Zabbix" column in the native NetBox Device list** — an icon (green
  checkmark = matched, clickable through to the corresponding Zabbix host in
  NetBox; gray cross = unmatched), no text to save space. Added via
  `utilities.tables.register_table_column()` (the official NetBox API for
  plugins to extend core tables), not by overriding `dcim.tables.DeviceTable`.
  Hidden by default (outside our plugin's control is what NetBox shows by
  default on its own core table) — enable it via "Configure Table" on the
  Device list. Also sortable (click the header) and filterable (a new
  "Matched with Zabbix" field in the "Filters" tab of the Device list) —
  both via a safe correlated `Exists()` subquery, not a direct join on the
  reverse FK relationship (which would duplicate device rows in the result
  for a device with multiple ZabbixHost records — this actually happens in
  this environment). NetBox has no official API for adding a filter to a
  core FilterSet (unlike columns), so this is a direct extension of
  `dcim.filtersets.DeviceFilterSet`/`dcim.forms.filtersets.DeviceFilterForm`
  from the plugin.
- **Fix: a stuck sync job now resolves itself** — the periodic "Zabbix sync"
  schedules its next run only AFTER the current one finishes/fails
  (`core.jobs.JobRunner.handle`) — if a run ever got stuck (e.g. a hanging
  Zabbix API during a network issue) without a time limit, no further sync
  would ever be scheduled again (this is exactly what happened — 9 hours
  without a sync, the job had to be manually deleted and a manual refresh
  run). `ZabbixSyncJob` now has an explicit `job_timeout=120s` (previously
  only NetBox's silent global default of 300s applied, outside the plugin's
  control) — a stuck run is killed within 2 minutes and the next sync is
  correctly scheduled regardless. Verified directly via rqworker (a
  temporary test job) that the RQ timeout actually interrupts a hanging run
  and scheduling continues. The existing dashboard warning ("Data may be
  stale") remains as a second safety net for failures outside a single run
  (e.g. a worker crash).
- **Fix: sync no longer floods the global NetBox Changelog** —
  `ZabbixHost`/`ZabbixProblem` are `NetBoxModel`, so every overwrite during
  sync (`last_synced`, `problem_count`, availability...) was logged as an
  `ObjectChange`. The periodic sync job didn't cause this (it runs outside
  the request context, where NetBox automatically skips logging), but the
  manual "Refresh from Zabbix" button did — it ran inside the request
  context, so every click created one record per host. In this installation
  this produced 7402 out of 15542 total (~48%) of all `ObjectChange` records
  in NetBox over 2 days. `sync.run_sync()` now temporarily disables the
  request context during writes, exactly as the periodic job does — data
  updates the same way, it just isn't recorded to the audit log. The
  `ZabbixConfiguration` Changelog (below) is not affected by this.
- **Changelog for plugin settings** — `ZabbixConfiguration` is now a
  `NetBoxModel` (previously a plain model without auditing); saving under
  Zabbix → Settings creates an `ObjectChange` record (who/when/from which
  value to which), available via a new "Changelog" button on the settings
  page.
- **Fix: the "Zabbix" panel/tab on Device/VM no longer depends on
  `matching_enabled`** — disabling "Match with NetBox" previously hid both
  the panel and the tab even on devices that already had a valid link to a
  ZabbixHost (whether automatic or manual). Visibility is now determined
  solely by the existence of a matched host for the given object;
  `matching_enabled` continues to affect only the sync job (new automatic
  links) and aggregate views (dashboard, sub-options in Settings).
- **Problem history on the Zabbix host detail page too** (Zabbix → Hosts →
  detail) — the same card as on the Device/VM tab (quick ranges
  1h/6h/24h/7d/30d + custom UTC range), now shared via
  `inc/history_card.html`, so the two places can't visually drift apart.
- **Direct link to the problem in Zabbix** — an icon next to every problem
  (device tab, history, host detail, dashboard, Problems list) opens that
  exact problem directly in Zabbix (`tr_events.php`, the same format as the
  `{EVENT.URL}` macro). Requires `zabbix_triggerid` on `ZabbixProblem`
  (migration 0007, populated on the next sync).
- **Direct link to the host in Zabbix, also in the Hosts list** — the same
  icon opens the host's dashboard directly in Zabbix
  (`ZabbixHost.get_zabbix_url()`). In the Hosts list, "Open in Zabbix" (a
  bare icon) sits in the action cell right next to the import "+" button
  (via `ActionsColumn.extra_buttons`), not as its own column; in the
  Problems list it remains its own column (a bare icon, there's no "+"
  there).
- **Importing an unmatched host as a new device/VM** — a new icon next to
  unmatched hosts in the Hosts list (visible only without an existing link
  and with permission to add a Device or VM) leads to a page with two
  combined forms, "Create as device" / "Create as virtual machine" — each
  built from stock NetBox forms (DeviceForm/VirtualMachineForm +
  InterfaceForm/VMInterfaceForm + IPAddressForm), pre-filled with the name,
  comments summarizing the Zabbix data, and a possibly guessed Site. A
  single click on Save creates the device/VM **and** a loopback interface
  (`type=virtual`) with the SNMP IP address from Zabbix in one transaction,
  set directly as the primary IP (`IPAddressForm.primary_for_parent`) —
  clearing the IP address before submitting creates only the device/VM
  itself, without an interface. The device type/role (and other required
  fields) are filled in by a human and the form is saved by them — nothing
  is written automatically, the same "human confirms" philosophy as with
  manual matching. When the user has permission for both types, the
  "Device"/"VM" forms are shown in tabs (not stacked), so two long forms
  don't need to be scrolled through. The Zabbix host summary (attributes +
  interfaces) sits above the forms as a compact full-width strip, not in a
  side column — which left a large empty area next to a long form. The
  Device form's fields are grouped into the same sections as the native
  NetBox Add Device page (Hardware, Location, Management, Virtualization,
  Tenancy, Virtual Chassis, Owner, ...) — unlike `VirtualMachineForm`,
  `DeviceForm` has no `fieldsets` of its own, the native page assembles the
  groups manually in the template, so without this adjustment all fields
  displayed as one flat list. The form also has the same width as the
  native Add Device/Add VM pages (`object-edit` class, max 800px), not full
  page width. The Latitude/Longitude fields on the device are pre-filled
  with GPS coordinates from the Zabbix host inventory (`location_lat`/
  `location_lon`) if the host has them set — read directly from the Zabbix
  API when the page is opened (not persisted in the DB, same as problem
  history), rounded to 6 decimal places per the `Device.latitude`/
  `longitude` limit. The "+" icon is a solid-color button (`btn
  btn-primary`), the same pattern as the native Edit/Delete buttons — so it
  automatically picks up NetBox's own teal color (both dark and light mode)
  — and sits right next to the Edit button in the action column (via
  `ActionsColumn.extra_buttons`, the same way as VLANGROUP_BUTTONS in
  NetBox core), not as its own column. The Site field can additionally be
  pre-filled directly from an explicit Zabbix host tag (default key
  `nbx_siteid`, configurable under Zabbix → Settings → "Import from
  Zabbix"), whose value is directly a NetBox Site ID — e.g. the tag
  `nbx_siteid=63` means Site pk 63. This takes precedence over the older
  guess based on the host group name (`_guess_site()`, which in this
  environment practically never hits, since Zabbix host groups are
  organizational categories while NetBox Site names are physical addresses)
  — the tag is an explicit cross-reference set by a human, not a guess. An
  empty tag key disables the feature entirely (falls back to the original
  behavior). The tag is read from `ZabbixHost.zabbix_tags` (see below —
  synced during the regular sync, same as host groups/templates), not via a
  live query; GPS remains the only thing that is fetched live
  (`zabbix.get_host_inventory()`) when the import page is opened.
- **Zabbix tags as a column in the Hosts list** — host-level tags
  (`selectTags` on `host.get`, e.g. `nbx_siteid: 63`) are now synced into a
  new `ZabbixHost.zabbix_tags` field (via the same mechanism as host groups
  and templates — during the regular sync, not live), shown as badges in a
  new "Zabbix tags" column (enabled by default). This lets you, for
  example, check whether a host has an `nbx_siteid` tag set for import
  (above) without having to go into Zabbix. Also available via the REST API
  (`ZabbixHostSerializer`).
- **Choosing which Zabbix tags are shown** — for hosts with many tags
  (`class`, `vendor`, `olt`, ...) the "Zabbix tags" column quickly takes up
  a lot of space. An icon next to "Configure Table" (not in the column
  header — that's inside the scrolling container, where the dropdown could
  get clipped; nor next to Export in the top bar — too disconnected from
  the table) opens a dropdown listing all tag keys actually in use
  (dynamically, not a fixed list); check just the ones you want to see. An
  empty selection = show all (default). This filters only the display
  (`ZabbixHost.display_tags`) — the raw `zabbix_tags` stays untouched. The
  setting (`ZabbixConfiguration.visible_tag_keys`) isn't edited on the
  Settings page, only via this dropdown (the same philosophy as
  `dashboard_severities`).

### v0.3.0
- **Simplified menu** — removed the "Consistency" section (Uncovered
  Devices / Uncovered VMs / Unmatched Hosts) and its views; unmatched hosts
  can be found via the `is_matched=false` filter directly in the Hosts list
  (which also has a matching-edit action).
- The dashboard severity selection is now edited in only one place (the
  gear dropdown on the dashboard) — removed from the Settings form, where
  it previously risked being silently overwritten when another setting was
  saved.
- **Settings now react to "pure Zabbix viewer" mode** — when
  `matching_enabled` is disabled, the form hides `match_by_ip`/`sync_vms`/
  stripped domains and "Dashboard shows only matched hosts" (they have no
  effect in this mode) and explains why; their saved values remain
  untouched in the DB until matching is turned back on.
- **Sync interval editable in the UI** — new `sync_interval` model field
  (previously only `PLUGINS_CONFIG`/env, requiring a restart); after every
  run the sync job re-evaluates its own `Job.interval` based on the current
  setting, so the change takes effect from the next cycle without
  restarting the containers. The connection (API URL, token) intentionally
  remains env-only.

### v0.2.0
- **Sync and matching** — a background job (every `sync_interval` minutes)
  pulls hosts and problems from Zabbix and matches them to Device/VM by
  stored ID, normalized name, or unambiguous IP; manual assignments are
  never overwritten by sync.
- **Device/VM integration** — a status panel and "Zabbix" tab with live
  problems (cached) and problem history (1h/6h/24h/7d/30d/custom range)
  straight from the Zabbix API — history is not stored in NetBox.
- **Dashboard** — tiles by severity, host availability statistics, panels
  of the worst hosts and active problems, an instant "Refresh from Zabbix"
  button.
- **Lists, API, consistency** — filterable host/problem lists
  (site/tenant/role), read-only REST API, views of uncovered devices/VMs
  and unmatched hosts with manual assignment.
- **Graphical settings** — all behavior (matching, severities, suppressed
  problems, dashboard range) is changed in the UI (Zabbix → Settings) and
  takes effect immediately, without a restart.
