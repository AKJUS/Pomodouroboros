from dataclasses import dataclass, field
from datetime import date as Date
from os import environ
from os.path import expanduser
from pickle import dumps, loads
from typing import Callable, Dict

from twisted.python.filepath import FilePath

from .pommodel import Day

TEST_MODE = bool(
    environ.get("TEST_MODE")
    or environ.get("ARGVZERO", "").endswith("/TestPomodouroboros")
)

defaultBaseLocation = FilePath(expanduser("~/.local/share/pomodouroboros"))
if TEST_MODE:
    defaultBaseLocation = defaultBaseLocation.child("testing")

def testingDay(date: Date) -> Day:
    return Day.forTesting()

@dataclass
class DayLoader:
    baseLocation: FilePath = defaultBaseLocation
    cache: Dict[Date, Day] = field(default_factory=dict)
    newDay: Callable[[Date], Day] = field(
        default=testingDay if TEST_MODE else Day.new
    )

    def pathForDate(self, date: Date) -> FilePath:
        childPath: FilePath = self.baseLocation.child(
            date.isoformat() + ".pomday"
        )
        return childPath

    def saveDay(self, day: Day) -> None:
        """
        Save the given C{day} object.
        """
        if not self.baseLocation.isdir():
            self.baseLocation.makedirs(True)
        self.pathForDate(day.startTime.date()).setContent(dumps(day))

    def loadOrCreateDay(self, date: Date) -> Day:
        """
        Load or create a day.
        """
        if date in self.cache:
            return self.cache[date]

        dayPath = self.pathForDate(date)
        loadedOrCreated = None
        if (not TEST_MODE) and dayPath.isfile():
            loadedOrCreated = loads(dayPath.getContent())
        if loadedOrCreated is None:
            loadedOrCreated = self.newDay(date)
        self.cache[date] = loadedOrCreated
        return loadedOrCreated
