from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo

from AppKit import (
    NSNib,
    NSObject,
    NSWindow,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
)
from objc import IBOutlet
from twisted.internet.task import Clock
from twisted.python.filepath import FilePath
from twisted.trial.unittest import TestCase

from pomodouroboros.macos.progress_hud import ProgressController
from pomodouroboros.pommodel import Day
from pomodouroboros.storage import DayLoader

from ..hudmulti import HUDMultipleProgress
from ..old_mac_gui import MacPomObserver
from ..progress_hud import PieTimer


class DayProgressionTests(TestCase):
    def test_pom_observer(self) -> None:
        clock = Clock()
        zone = ZoneInfo("US/Pacific")
        beforeWork = datetime(
            2025,
            1,
            10,
            6,
            tzinfo=zone,
        )
        clock.advance(beforeWork.timestamp())
        daysPath = FilePath(self.mktemp())
        daysPath.createDirectory()

        def newDay(date: Date) -> Day:
            day = Day.new(date, timezone=zone)
            # clip out the middle to produce a gap
            del day.pendingIntervals[2:-2]
            return day

        dayLoader = DayLoader(daysPath, newDay=newDay)
        day = dayLoader.loadOrCreateDay(beforeWork.date())
        observer = MacPomObserver(
            progressController=ProgressController(),
            refreshList=lambda: None,
            clock=clock,
            dayLoader=dayLoader,
        )
        afterFirst = beforeWork + timedelta(hours=3, minutes=5)
        now = afterFirst.timestamp()
        clock.advance(now - clock.seconds())
        day.advanceToTime(clock.seconds(), observer)
        self.assertEqual(observer.progressController.shouldBeVisible, True)
        between = beforeWork + timedelta(hours=4)
        now = between.timestamp()
        clock.advance(now - clock.seconds())
        day.advanceToTime(clock.seconds(), observer)
        self.assertEqual(observer.progressController.shouldBeVisible, False)

