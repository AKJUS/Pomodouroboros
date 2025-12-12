# -*- test-case-name: pomodouroboros.model.test.test_sessions -*-
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from enum import IntEnum
from typing import (
    TYPE_CHECKING,
    Callable,
    ContextManager,
    Iterator,
    Protocol,
    Sequence,
)
from zoneinfo import ZoneInfo

from datetype import DateTime, Time
from fritter.boundaries import (
    Cancellable,
    Day,
    RepeatingWork,
    ScheduledCall,
    Scheduler,
)
from fritter.drivers.datetimes import DateScale, guessLocalZone
from fritter.drivers.twisted import TwistedAsyncDriver
from fritter.repeat import repeatedly
from fritter.repeat.rules.datetimes import EachDTRule, EachWeekOn
from fritter.tree import Scale, branch
from twisted.internet.defer import Deferred

from pomodouroboros.model.observables import (
    Changes,
    IgnoreChanges,
    ObservableList,
    Observer,
    observable,
    addObserver,
)

if TYPE_CHECKING:
    from .ideal import IdealScoreInfo
    from .nexus import Nexus


class Weekday(IntEnum):
    monday = 0
    tuesday = 1
    wednesday = 2
    thursday = 3
    friday = 4
    saturday = 5
    sunday = 6


@dataclass(frozen=True, order=True)
class Session:
    """
    A session describes a period during which the user wishes to be
    intentionally actively using the app.  During an active session, users will
    be notified of the next time their score will decrease.
    """

    start: float
    end: float
    automatic: bool

    def idealScoreFor(self, nexus: Nexus) -> IdealScoreInfo:
        from .ideal import idealScore

        return idealScore(nexus, self.start, self.end)


class SessionRule(Protocol):
    def startRule(self) -> EachDTRule:
        """
        The recurrence rule for starting sessions according to this rule.
        """

    def endRule(self) -> EachDTRule:
        """
        The recurrence rule for ending sessions according to this rule.
        """


@dataclass(frozen=True)
class DailySessionRule:
    dailyStart: Time[ZoneInfo]
    dailyEnd: Time[ZoneInfo]
    days: set[Weekday]

    def startRule(self) -> EachDTRule:
        return EachWeekOn(
            {getattr(Day, each.name.upper()) for each in self.days},
            hour=self.dailyStart.hour,
            minute=self.dailyStart.minute,
            second=self.dailyStart.second,
        )

    def endRule(self) -> EachDTRule:
        return EachWeekOn(
            {getattr(Day, each.name.upper()) for each in self.days},
            hour=self.dailyEnd.hour,
            minute=self.dailyEnd.minute,
            second=self.dailyEnd.second,
        )

    def nextAutomaticSession(
        self, fromTimestamp: DateTime[ZoneInfo]
    ) -> Session | None:
        assert self.dailyStart.tzinfo == fromTimestamp.tzinfo
        assert self.dailyEnd.tzinfo == fromTimestamp.tzinfo
        if not self.days:
            return None
        startRule = self.startRule()
        endRule = self.endRule()
        startSteps, startNextRefs = startRule(
            fromTimestamp, fromTimestamp + timedelta(days=7)
        )
        if not startSteps:
            return None
        endSteps, endNextRefs = endRule(
            startSteps[0], startSteps[0] + timedelta(days=7)
        )
        if not endSteps:
            return None
        return Session(
            startSteps[0].timestamp(), endSteps[0].timestamp(), True
        )


@dataclass
class StatefulCancel:
    """
    a canceller that holds another canceller and updates it, canceling it when
    cancelled
    """

    _state: Cancellable | None = None

    def cancel(self) -> None:
        state = self._state
        if self._state is not None:
            self._state.cancel()

    def update(self, state: Cancellable | None) -> None:
        self._state = state


@observable()
class SessionManager:
    observer: Observer
    upcomingSessions: ObservableList[Session]
    previousSessions: ObservableList[Session]
    rules: ObservableList[DailySessionRule]
    _physicalScheduler: Scheduler[float, Callable[[], None], int]
    _civilScheduler: Scheduler[DateTime[ZoneInfo], Callable[[], None], int]
    _everythingScheduled: list[Cancellable] = field(default_factory=list)
    activeSession: Session | None = None

    def _beginSessionWithRule(
        self, state: StatefulCancel, rule: SessionRule
    ) -> RepeatingWork[list[DateTime[ZoneInfo]]]:
        def work(
            steps: list[DateTime[ZoneInfo]], scheduled: Cancellable
        ) -> None:
            state.update(scheduled)
            if not steps:
                # We will be run with an empty C{steps} when the repeating call
                # is set up.  Once an actual instance of the rule has passed,
                # C{steps} will have that value in it.
                return
            endSteps, endNextRefs = rule.endRule()(
                steps[0], steps[0] + timedelta(days=7)
            )
            if not endSteps:
                return None
            session = Session(
                steps[0].timestamp(), endSteps[0].timestamp(), True
            )
            self._civilScheduler.callAt(
                endSteps[0], self._endSessionWithRule(rule, session)
            )
            self.activeSession = session

        return work

    def _endSessionWithRule(
        self, rule: SessionRule, session: Session
    ) -> Callable[[], None]:
        def work() -> None:
            self.activeSession = None

        return work

    def _reschedule(self) -> None:
        """
        Something has changed; reschedule all the scheduled stuff.
        """
        # TODO: reentrancy guard; if _reschedule() changes .rules somehow, this
        # state will be corrupted
        self._everythingScheduled, toCancel = [], self._everythingScheduled[:]
        for sched in self._everythingScheduled:
            sched.cancel()
        for rule in self.rules:
            self._everythingScheduled.append(sc := StatefulCancel())
            repeatedly(
                self._civilScheduler,
                self._beginSessionWithRule(sc, rule),
                rule.startRule(),
            )

        def startStaticSession() -> None:
            self.activeSession = self.upcomingSessions.pop(0)

        if self.upcomingSessions:
            earliestSession = self.upcomingSessions[0]
            self._everythingScheduled.append(
                self._physicalScheduler.callAt(
                    earliestSession.start,
                    startStaticSession,
                )
            )

    # Implementation of observer protocol, for watching changes to the list of
    # L{SessionRule} objects in C{self.rules}

    @contextmanager
    def added(self, key: object, new: object) -> Iterator[None]:
        yield
        self._reschedule()

    @contextmanager
    def removed(self, key: object, old: object) -> Iterator[None]:
        yield
        self._reschedule()

    @contextmanager
    def changed(self, key: object, old: object, new: object) -> Iterator[None]:
        yield
        self._reschedule()

    def child(self, key: object) -> Changes[object, object]:
        return IgnoreChanges

    # End observer protocol

    @classmethod
    def new(
        cls,
        observer: Observer,
        scheduler: Scheduler[float, Callable[[], None], int],
    ) -> SessionManager:
        dateScale: Scale[DateTime[ZoneInfo], float, float] = DateScale(
            guessLocalZone()
        )
        branchManager, dateScheduler = branch(scheduler, dateScale)
        self = cls(
            observer,
            ObservableList(IgnoreChanges),
            ObservableList(IgnoreChanges),
            ObservableList(IgnoreChanges),
            scheduler,
            dateScheduler,
        )
        addObserver(self.rules, self)
        self._reschedule()
        return self
