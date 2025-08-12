"""
GTK+ UI for old model (pomodouroboros.pommodel).

Hopefully we can replace this with the new model (pomodouroboros.model) in not
too long, but it's just too complex and unfinished to start with; hopefully
some contributors will come along and help out once a linux version exists!
"""

from dataclasses import dataclass
from datetime import date as Date
from typing import Any
from pathlib import Path

from fritter.boundaries import PhysicalScheduler, ScheduledCall
from fritter.drivers.twisted import TwistedTimeDriver
from fritter.repeat import repeatedly
from fritter.repeat.rules.seconds import EverySecond
from fritter.scheduler import schedulerFromDriver

from ..pommodel import Break, Day, IntentionResponse, Interval, Pomodoro
from ..storage import DayLoader
from .platspec import Gio, GObject, Gtk
from .gobj_utils import gSimpleProp


@dataclass
class LinuxPomObserver:
    def breakStarting(self, startingBreak: Break) -> None:
        """
        A break is starting.
        """

    def pomodoroStarting(self, day: Day, startingPomodoro: Pomodoro) -> None:
        """
        A pomodoro is starting; time to express an intention.
        """

    def elapsedWithNoIntention(self, pomodoro: Pomodoro) -> None:
        """
        A pomodoro completed, but no intention was specified.
        """

    def tooLongToEvaluate(self, pomodoro: Pomodoro) -> None:
        """
        A pomodoro is no longer eligible to be evaluated
        """

    def progressUpdate(
        self,
        interval: Interval,
        percentageElapsed: float,
        canSetIntention: IntentionResponse,
    ) -> None:
        """
        Some time has elapsed on the given interval, and it's now
        percentageElapsed% done.  canSetIntention tells you the likely outcome
        of setting the intention.
        """

    def dayOver(self) -> None:
        """
        The day is over, so there will be no more intervals.
        """

class PomItemModel(GObject.Object):
    __gtype_name__ = "PomItemModel"

    number = gSimpleProp("number", int)
    description = gSimpleProp("description", str)
    start = gSimpleProp("start", str)
    end = gSimpleProp("end", str)
    success = gSimpleProp("success", str)


def main(reactor: Any) -> None:
    dayLoader = DayLoader()
    day = dayLoader.loadOrCreateDay(Date.today())
    scheduler: PhysicalScheduler = schedulerFromDriver(
        TwistedTimeDriver(reactor)
    )
    builder = Gtk.Builder.new()
    builder.add_from_file(str(Path(__file__).parent / "linuxlegacypom.ui"))
    def makeBar(app: Gtk.Application) -> None:
        bar = MultiBar.create(app)
    linuxPomObserver = LinuxPomObserver()
    def updateUI(steps: int, scheduled: ScheduledCall)->None:
        day.advanceToTime(reactor.seconds(), linuxPomObserver)
    repeatedly(scheduler, updateUI, EverySecond(5))
