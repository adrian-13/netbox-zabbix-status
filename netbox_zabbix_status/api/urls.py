from netbox.api.routers import NetBoxRouter

from . import views

router = NetBoxRouter()
router.register('hosts', views.ZabbixHostViewSet)
router.register('problems', views.ZabbixProblemViewSet)

urlpatterns = router.urls
