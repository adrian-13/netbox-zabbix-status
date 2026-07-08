from django.urls import include, path

from utilities.urls import get_model_urls

from . import views  # noqa: F401 — import registruje views (register_model_view)

urlpatterns = [
    path('dashboard/', views.ZabbixDashboardView.as_view(), name='dashboard'),
    path('dashboard/severities/', views.DashboardSeveritiesView.as_view(), name='dashboard_severities'),
    path('settings/', views.ZabbixSettingsView.as_view(), name='settings'),
    path('refresh/', views.ZabbixRefreshView.as_view(), name='refresh'),
    path('hosts/', include(get_model_urls('netbox_zabbix_status', 'zabbixhost', detail=False))),
    path('hosts/<int:pk>/', include(get_model_urls('netbox_zabbix_status', 'zabbixhost'))),
    path('problems/', include(get_model_urls('netbox_zabbix_status', 'zabbixproblem', detail=False))),
    # Konzistenčné pohľady
    path('unmatched-hosts/', views.UnmatchedHostsView.as_view(), name='unmatched_hosts'),
    path('unmonitored-devices/', views.UnmonitoredDevicesView.as_view(), name='unmonitored_devices'),
    path('unmonitored-vms/', views.UnmonitoredVMsView.as_view(), name='unmonitored_vms'),
]
