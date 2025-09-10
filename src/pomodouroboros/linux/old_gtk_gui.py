"""
GTK+ UI for old model (pomodouroboros.pommodel).

Hopefully we can replace this with the new model (pomodouroboros.model) in not
too long, but it's just too complex and unfinished to start with; hopefully
some contributors will come along and help out once a linux version exists!
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path
from typing import Any

from fritter.boundaries import PhysicalScheduler, ScheduledCall
from fritter.drivers.twisted import TwistedTimeDriver
from fritter.repeat import repeatedly
from fritter.repeat.rules.seconds import EverySecond
from fritter.scheduler import schedulerFromDriver
from twisted.internet.defer import Deferred

from ..common import animatePct
from ..pomcommon import poms2Dicts
from ..pommodel import Break, Day, IntentionResponse, Interval, Pomodoro, IntentionResponse
from ..storage import DayLoader
from .gobj_utils import gSimpleProp, bindLabelColumns
from .gtk_progress_bar import MultiBar
from .platspec import Gio, GObject, Gtk


@dataclass
class LinuxPomObserver:
    multiBar: MultiBar
    loader: DayLoader
    day: Day
    store: Gio.ListStore
    reactor: Any
    lastIntentionResponse: IntentionResponse | None = None

    def breakStarting(self, startingBreak: Break) -> None:
        """
        A break is starting.
        """
        self.multiBar.setStyle("break")

    def refreshData(self) -> None:
        self.store.remove_all()
        day = self.day
        now = self.reactor.seconds()
        onlyPoms = [
            each
            for each in day.elapsedIntervals + day.pendingIntervals
            if isinstance(each, Pomodoro)
        ]
        for row in poms2Dicts(day, now, onlyPoms):
            model = PomItemModel(
                number=row["index"],
                description=row["description"],
                start=row["startTime"],
                end=row["endTime"],
                success=row["success"],
                editable=row["canChange"],
            )
            pom = row["pom"]
            assert isinstance(pom, Pomodoro)
            self.bindDescriptionEdit(model, pom)
            self.store.append(model)

    def bindDescriptionEdit(self, model: PomItemModel, pom: Pomodoro) -> None:
        def change(item: PomItemModel, pspec: object) -> None:
            print("change notify", item, pspec)
            result = self.day.expressIntention(
                self.reactor.seconds(), model.description, pom
            )
            print(f"setting intention for {pom}: {result}")
            self.loader.saveDay(self.day)
        # TODO: keep track of old description so we can change it back if this wasn't allowed
        model.connect("notify::description", change)

    def pomodoroStarting(self, day: Day, startingPomodoro: Pomodoro) -> None:
        """
        A pomodoro is starting; time to express an intention.
        """
        self.multiBar.show()
        self.multiBar.setStyle("active")
        self.refreshData()

    def elapsedWithNoIntention(self, pomodoro: Pomodoro) -> None:
        """
        A pomodoro completed, but no intention was specified.
        """
        # TODO: GTK notification
        print("elapsed with no intention set")

    def tooLongToEvaluate(self, pomodoro: Pomodoro) -> None:
        """
        A pomodoro is no longer eligible to be evaluated
        """
        # TODO: GTK notification
        print("too long to evaluate")

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

        if self.lastIntentionResponse != canSetIntention:
            self.lastIntentionResponse = canSetIntention
            match canSetIntention:
                case IntentionResponse.CanBeSet:
                    self.multiBar.setStyle("grace")
                case IntentionResponse.AlreadySet:
                    self.multiBar.setStyle("active")
                case IntentionResponse.OnBreak:
                    self.multiBar.setStyle("break")
                case IntentionResponse.TooLate:
                    self.multiBar.setStyle("prompt")

        async def _() -> None:
            await animatePct(
                self.multiBar,
                self.reactor,
                percentageElapsed,
                self.multiBar.percentage(),
                # TODO: better place for magic numbers
                1.0,
                0.15,
                0.3,
            )

        Deferred.fromCoroutine(_())
        self.multiBar.setPercentage(percentageElapsed)
        # self.refreshData()

    def dayOver(self) -> None:
        """
        The day is over, so there will be no more intervals.
        """
        self.multiBar.hide()


class PomItemModel(GObject.Object):
    __gtype_name__ = "PomItemModel"

    number = gSimpleProp("number", str)
    description = gSimpleProp("description", str)
    start = gSimpleProp("start", str)
    end = gSimpleProp("end", str)
    success = gSimpleProp("success", str)
    editable = gSimpleProp("editable", bool, False)

    def canEditProperty(self, name: str) -> bool:
        return self.editable and name == "description"


def wireUpList(builder: Gtk.Builder) -> None:

    columnsToBind = {}
    for eachColName in ["number", "description", "start", "end", "success"]:
        itemFactory = builder.get_object(f"{eachColName}-item-factory")
        assert isinstance(itemFactory, Gtk.SignalListItemFactory)
        columnsToBind[eachColName] = itemFactory
    bindLabelColumns(columnsToBind)


async def main(reactor: Any, app: Gtk.Application) -> None:
    dayLoader = DayLoader()
    day = dayLoader.loadOrCreateDay(Date.today())
    scheduler: PhysicalScheduler = schedulerFromDriver(
        TwistedTimeDriver(reactor)
    )
    builder = Gtk.Builder.new()
    builder.add_from_file(str(Path(__file__).parent / "linuxlegacypom.ui"))
    store = builder.get_object("the-list-store")
    assert isinstance(store, Gio.ListStore)
    wireUpList(builder)

    def bootApp(app: Gtk.Application) -> None:
        bar = MultiBar.create(app)
        linuxPomObserver = LinuxPomObserver(
            bar, dayLoader, day, store, reactor
        )

        bonus = builder.get_object("my-bonus-button")
        assert isinstance(bonus, Gtk.Button), f"{bonus}"

        def clickBonus(button: Gtk.Button) -> None:
            print("clicked bonus")
            from datetime import datetime
            from dateutil.tz import tzlocal

            day.bonusPomodoro(datetime.now(tzlocal()))
            linuxPomObserver.refreshData()

        bonus.connect("clicked", clickBonus)

        def updateUI(steps: int, scheduled: ScheduledCall) -> None:
            # TODO: refactor with
            # pomodouroboros.macos.old_mac_gui.DayManager.update to consider
            # day boundaries
            day.advanceToTime(reactor.seconds(), linuxPomObserver)

        repeatedly(scheduler, updateUI, EverySecond(5))
        linuxPomObserver.refreshData()

    loaded: object = builder.get_object("my-window")
    assert isinstance(loaded, Gtk.Window)
    loaded.present()

    app.connect("activate", bootApp)
    await Deferred()


if __name__ == "__main__":
    from twisted.internet.gireactor import install

    greactor = install()
    app = Gtk.Application(application_id="im.glyph.and.this.is.Pomodouroboros")
    greactor.registerGApplication(app)
    greactor.callWhenRunning(
        lambda: Deferred.fromCoroutine(main(greactor, app))
    )
    greactor.run()
