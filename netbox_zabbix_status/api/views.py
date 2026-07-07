from netbox.api.viewsets import NetBoxReadOnlyModelViewSet

from ..filtersets import ZabbixHostFilterSet, ZabbixProblemFilterSet
from ..models import ZabbixHost, ZabbixProblem
from .serializers import ZabbixHostSerializer, ZabbixProblemSerializer


class ZabbixHostViewSet(NetBoxReadOnlyModelViewSet):
    queryset = ZabbixHost.objects.prefetch_related('device', 'virtual_machine', 'tags')
    serializer_class = ZabbixHostSerializer
    filterset_class = ZabbixHostFilterSet


class ZabbixProblemViewSet(NetBoxReadOnlyModelViewSet):
    queryset = ZabbixProblem.objects.prefetch_related(
        'host__device', 'host__virtual_machine', 'tags'
    )
    serializer_class = ZabbixProblemSerializer
    filterset_class = ZabbixProblemFilterSet
