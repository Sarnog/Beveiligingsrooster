"""De klok van de app: altijd in de tijdzone Europe/Amsterdam (of TZ uit de omgeving).

We gebruiken zoneinfo met het pakket 'tzdata', zodat de juiste tijd (inclusief
zomer- en wintertijd) ook klopt als het besturingssysteem zelf geen
tijdzonebestanden heeft, zoals in een kale container.
"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


def tijdzone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TZ") or "Europe/Amsterdam")


def nu() -> datetime:
    """Huidige lokale tijd, zonder tijdzone-info en zonder microseconden."""
    return datetime.now(tijdzone()).replace(tzinfo=None, microsecond=0)


def vandaag() -> date:
    return nu().date()
