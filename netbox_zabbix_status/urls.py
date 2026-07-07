from django.urls import include, path

from utilities.urls import get_model_urls

from . import views  # noqa: F401 — import registruje views (register_model_view)

urlpatterns = [
    path('hosts/', include(get_model_urls('netbox_zabbix_status', 'zabbixhost', detail=False))),
    path('hosts/<int:pk>/', include(get_model_urls('netbox_zabbix_status', 'zabbixhost'))),
    path('problems/', include(get_model_urls('netbox_zabbix_status', 'zabbixproblem', detail=False))),
]
