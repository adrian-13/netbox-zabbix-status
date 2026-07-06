# Builds a NetBox image with the Zabbix Status plugin installed.
# Used by netbox-docker's docker-compose.override.yml (build context = this repo).
#
# NETBOX_IMAGE defaults to the snmp-sync dev image so the resulting image contains
# BOTH plugins (image chain: netboxcommunity/netbox -> netbox-snmp-sync:dev -> this).
# The plugin is installed editable so that bind-mounting this source directory over
# /opt/netbox-plugin-zabbix-status makes local code edits take effect on the next
# container/process restart, without rebuilding the image.
ARG NETBOX_IMAGE=netbox-snmp-sync:dev
FROM ${NETBOX_IMAGE}

COPY . /opt/netbox-plugin-zabbix-status
# The NetBox image ships a uv-managed venv at /opt/netbox/venv (no pip inside it),
# so install the plugin with uv targeting that interpreter.
RUN /usr/local/bin/uv pip install --no-cache \
    --python /opt/netbox/venv/bin/python \
    --editable /opt/netbox-plugin-zabbix-status
