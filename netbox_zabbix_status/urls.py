from django.urls import include, path

from utilities.urls import get_model_urls

from . import views  # noqa: F401 — import registruje views (register_model_view)

urlpatterns = [
    path('dashboard/', views.ZabbixDashboardView.as_view(), name='dashboard'),
    path('dashboard/severities/', views.DashboardSeveritiesView.as_view(), name='dashboard_severities'),
    path('settings/', views.ZabbixSettingsView.as_view(), name='settings'),
    # Singleton bez skutočnej "list" stránky — generic Changelog šablóna si ju
    # ale pýta na breadcrumb (get_action_url(model, 'list')), preto alias na to isté
    path('settings/', views.ZabbixSettingsView.as_view(), name='zabbixconfiguration_list'),
    path('settings/<int:pk>/', include(get_model_urls('netbox_zabbix_status', 'zabbixconfiguration'))),
    path('refresh/', views.ZabbixRefreshView.as_view(), name='refresh'),
    path('hosts/', include(get_model_urls('netbox_zabbix_status', 'zabbixhost', detail=False))),
    path('hosts/visible-tags/', views.HostsVisibleTagsView.as_view(), name='hosts_visible_tags'),
    path('hosts/<int:pk>/import/', views.ZabbixHostImportView.as_view(), name='zabbixhost_import'),
    path('hosts/<int:pk>/remove-tags/', views.ZabbixHostRemoveTagsView.as_view(), name='zabbixhost_remove_tags'),
    path('hosts/<int:pk>/', include(get_model_urls('netbox_zabbix_status', 'zabbixhost'))),
    path('problems/', include(get_model_urls('netbox_zabbix_status', 'zabbixproblem', detail=False))),
]
