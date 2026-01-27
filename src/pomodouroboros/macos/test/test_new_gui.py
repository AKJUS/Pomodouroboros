from typing import Callable
from unittest import TestCase
from zoneinfo import ZoneInfo

from AppKit import NSNib
from fritter.boundaries import Scheduler
from fritter.drivers.memory import MemoryDriver
from fritter.scheduler import schedulerFromDriver
from objc import IBOutlet
from twisted.internet.task import Clock

from ...macos.mac_gui import MacUserInterface
from ...model.boundaries import UIEventListener, EvaluationResult
from ...model.nexus import Nexus
from ...model.sessions import SessionManager
from ...model.observables import IgnoreChanges
from ...model.intervals import Pomodoro

TZ = ZoneInfo("US/Pacific")


class IntentionEditorTests(TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        sched: Scheduler[float, Callable[[], None], int] = schedulerFromDriver(
            driver := MemoryDriver()
        )

        def uiFactory(nexus: Nexus) -> UIEventListener:
            macUI = MacUserInterface.build(nexus, self.clock)
            self.testViewCollection = macUI.testViewCollection
            self.macUI = macUI
            return macUI

        self.nexus = Nexus(
            sched,
            driver,
            uiFactory,
            0,
            _sessionManager=SessionManager.new(IgnoreChanges, sched, TZ),
        )

    def test_ok(self) -> None:
        # datetime.datetime(2026, 1, 27, 11, 2, 38, 449683, tzinfo=zoneinfo.ZoneInfo(key='US/Pacific'))
        self.clock.advance(1769540558.449683)
        active = self.nexus.addIntention("active")
        completed = self.nexus.addIntention("completed")
        abandoned = self.nexus.addIntention("abandoned")
        self.nexus.startPomodoro(completed)
        from datetime import datetime

        pom = self.nexus.currentInterval
        assert isinstance(pom, Pomodoro)
        self.nexus.evaluatePomodoro(
            pom, EvaluationResult.achieved, 1769540558.449683
        )
        abandoned.abandoned = True

        # should not be necessary because in principle the UI should be
        # reactive here, but we're missing several UI events we would normally
        # get, such as abandonSelectedIntention_ being called.  TODO: move the
        # logic for calling refilter into an observer that can notice the
        # abandoned attribute being set directly (Intention is already,
        # necessarily @observable) rather than having view code do explicit
        # bookkeeeping
        self.macUI.intentionDataSource.refilter()
        # Initially, both should be False and we should have a single row
        # displayed.
        self.assertEqual(
            self.testViewCollection.intentionsTableView.numberOfRows(), 1
        )

        # verify initial binding state
        self.assertEqual(
            self.testViewCollection.showAbandonedCheckbox.state(), False
        )
        self.assertEqual(self.macUI.intentionDataSource.showAbandoned, False)
        self.macUI.intentionDataSource.showAbandoned = True
        # verify binding updates UI, including refiltering
        self.assertEqual(
            self.testViewCollection.showAbandonedCheckbox.state(), True
        )
        # we can now see the abandoned intention
        self.assertEqual(
            self.testViewCollection.intentionsTableView.numberOfRows(), 2
        )

        # same but for completed.
        self.assertEqual(
            self.testViewCollection.showCompletedCheckbox.state(), False
        )
        self.assertEqual(self.macUI.intentionDataSource.showCompleted, False)
        self.macUI.intentionDataSource.showCompleted = True
        self.assertEqual(
            self.testViewCollection.showCompletedCheckbox.state(), True
        )
        self.assertEqual(
            self.testViewCollection.intentionsTableView.numberOfRows(), 3
        )
