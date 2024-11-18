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
from fritter.boundaries import Cancellable, Day, ScheduledCall, Scheduler
from fritter.drivers.twisted import TwistedAsyncDriver
from fritter.repeat import Async
from fritter.repeat.rules.datetimes import EachDTRule, EachWeekOn
from twisted.internet.defer import Deferred

from pomodouroboros.model.observables import (
    IgnoreChanges,
    ObservableList,
    Observer,
    observable,
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


@observable()
class ActiveSessionManager:
    activeSession: Session | None
    observer: Observer
    rules: ObservableList[SessionRule]
    _scheduler: Scheduler[DateTime[ZoneInfo], Callable[[], None], int]
    _everythingScheduled: list[Cancellable]
    _async: Async

    def _beginSessionWithRule(
        self, rule: SessionRule
    ) -> Callable[[list[DateTime[ZoneInfo]], Cancellable], Deferred[None]]:
        async def work(
            steps: list[DateTime[ZoneInfo]], cancel: Cancellable
        ) -> None:
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
            self._scheduler.callAt(
                endSteps[0], self._endSessionWithRule(rule, session)
            )
            self.activeSession = session

        return lambda steps, cancel: Deferred.fromCoroutine(
            work(steps, cancel)
        )

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
        for sched in self._everythingScheduled:
            sched.cancel()
        for rule in self.rules:
            self._everythingScheduled.append(
                self._async.repeatedly(
                    self._scheduler,
                    rule.startRule(),
                    self._beginSessionWithRule(rule),
                )
            )

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

    @classmethod
    def new(
        cls, observer: Observer, scheduler: Scheduler[DateTime[ZoneInfo], Callable[[], None], int]
    ) -> ActiveSessionManager:
        rules: ObservableList[SessionRule] = ObservableList(IgnoreChanges)
        self = cls(None, observer, rules, scheduler, [], Async(TwistedAsyncDriver()))
        rules.observer = self
        self._reschedule()
        return self
