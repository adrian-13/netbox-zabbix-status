from utilities.choices import ChoiceSet


class ZabbixHostStatusChoices(ChoiceSet):
    """Zabbix host.status (0 = monitored, 1 = unmonitored)."""

    ENABLED = 'enabled'
    DISABLED = 'disabled'

    CHOICES = [
        (ENABLED, 'Enabled', 'green'),
        (DISABLED, 'Disabled', 'red'),
    ]


class AvailabilityChoices(ChoiceSet):
    """Per-interface availability (Zabbix >= 6.0: interface.available 0/1/2)."""

    UNKNOWN = 'unknown'
    UP = 'up'
    DOWN = 'down'

    CHOICES = [
        (UNKNOWN, 'Unknown', 'gray'),
        (UP, 'Up', 'green'),
        (DOWN, 'Down', 'red'),
    ]


class MatchMethodChoices(ChoiceSet):
    """Ako vznikla väzba ZabbixHost -> Device/VM. MANUAL sync nikdy neprepisuje."""

    NAME = 'name'
    IP = 'ip'
    MANUAL = 'manual'
    NONE = 'none'

    CHOICES = [
        (NAME, 'Name', 'green'),
        (IP, 'IP address', 'teal'),
        (MANUAL, 'Manual', 'blue'),
        (NONE, 'Unmatched', 'gray'),
    ]


class SeverityChoices:
    """Zabbix problem severity (0-5). Integer hodnoty, preto nie ChoiceSet."""

    NOT_CLASSIFIED = 0
    INFORMATION = 1
    WARNING = 2
    AVERAGE = 3
    HIGH = 4
    DISASTER = 5

    CHOICES = (
        (NOT_CLASSIFIED, 'Not classified'),
        (INFORMATION, 'Information'),
        (WARNING, 'Warning'),
        (AVERAGE, 'Average'),
        (HIGH, 'High'),
        (DISASTER, 'Disaster'),
    )

    COLORS = {
        NOT_CLASSIFIED: 'gray',
        INFORMATION: 'cyan',
        WARNING: 'teal',
        AVERAGE: 'yellow',
        HIGH: 'orange',
        DISASTER: 'red',
    }

    @classmethod
    def get_color(cls, severity):
        return cls.COLORS.get(severity, 'gray')
