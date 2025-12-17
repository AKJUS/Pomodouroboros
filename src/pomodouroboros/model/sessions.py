# -*- test-case-name: pomodouroboros.model.test.test_sessions,pomodouroboros.model.test.test_model -*-
from __future__ import annotations

from bisect import bisect
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from enum import IntEnum
from math import inf
from functools import cached_property
from typing import (
    TYPE_CHECKING,
    Callable,
    ContextManager,
    Iterator,
    Iterable,
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
    dailyStart: Time[None]
    dailyEnd: Time[None]
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

    @classmethod
    @contextmanager
    def create(cls) -> Iterator[StatefulCancel]:
        self = cls()
        yield self
        assert (
            self._state is not None
        ), "should be populated by the time the context is done"


@dataclass
class Rescheduler:
    scheduleCallback: Callable[[], Iterable[Cancellable]]
    _currentlyScheduled: list[Cancellable] = field(default_factory=list)

    def reschedule(self, path: Sequence[object] = ()) -> None:
        self._currentlyScheduled, toCancel = [], self._currentlyScheduled[:]
        for sched in toCancel:
            sched.cancel()
            # TODO: better handling of reentrancy here; stop rescheduling if
            # something interrupts us midway
        for rescheduled in self.scheduleCallback():
            self._currentlyScheduled.append(rescheduled)

    def observer(self, path: str = "") -> Changes[object, object]:
        return RescheduleObserver(self, path)


@dataclass
class RescheduleObserver:
    _rescheduler: Rescheduler
    _path: str = ""

    # Implementation of observer protocol, for watching changes to the list of
    # L{SessionRule} objects in C{self.rules}
    @contextmanager
    def added(self, key: object, new: object) -> Iterator[None]:
        yield
        self._rescheduler.reschedule((self._path, "added", key, new))

    @contextmanager
    def removed(self, key: object, old: object) -> Iterator[None]:
        yield
        self._rescheduler.reschedule((self._path, "removed", key, old))

    @contextmanager
    def changed(self, key: object, old: object, new: object) -> Iterator[None]:
        yield
        self._rescheduler.reschedule((self._path, "changed", key, old, new))

    def child(self, key: object) -> Changes[object, object]:
        return RescheduleObserver(self._rescheduler, f"{self._path}.{key}")

    # End observer protocol


MAX_SESSION_LENGTH = timedelta(days=7)


@observable()
class SessionManager:
    observer: Observer
    upcomingSessions: ObservableList[Session]
    previousSessions: ObservableList[Session]
    rules: ObservableList[DailySessionRule]
    _physicalScheduler: Scheduler[float, Callable[[], None], int]
    _civilScheduler: Scheduler[DateTime[ZoneInfo], Callable[[], None], int]
    activeSession: Session | None = None

    def upcomingSessionStartTime(self, fromTime: float) -> float:
        """
        Return the time of the next upcoming session.
        """
        return next(
            (
                session.start
                for session in self.upcomingSessions
                if session.end > fromTime and session.start > fromTime
            ),
            inf,
        )

    def addManualSession(self, startTime: float, endTime: float) -> None:
        """
        Create a new manual upcoming session with the given start and end time.
        """
        newSession = Session(startTime, endTime, False)
        self._insort(newSession)

    def _insort(self, session: Session) -> None:
        """
        Insert the given session into the upcoming sessions list (potentially
        implicitly rescheduling and starting it in the process, if the time is
        right for that).
        """
        location = bisect(
            self.upcomingSessions,
            session.start,
            0,
            None,
            key=lambda session: session.start,
        )
        self.upcomingSessions.insert(location, session)

    def _beginSessionWithRule(
        self, state: StatefulCancel, rule: SessionRule
    ) -> RepeatingWork[list[DateTime[ZoneInfo]]]:
        def createAndBeginRuleSession(
            steps: list[DateTime[ZoneInfo]], scheduled: Cancellable
        ) -> None:
            state.update(scheduled)
            if not steps:
                # We will be run with an empty C{steps} when the repeating call
                # is set up.  Once an actual instance of the rule has passed,
                # C{steps} will have that value in it.
                return
            # Get the matched recurrence of the ending rule, for the starting
            # rule that we created.
            endRule = rule.endRule()
            endSteps, endNextRefs = endRule(
                steps[-1], steps[-1] + MAX_SESSION_LENGTH
            )
            if not endSteps:
                # the session end wasn't found within the maximum session
                # begin/end interval delta, so it's invalid; do nothing.
                # FIXME: test
                # maybe: state.cancel()
                return None
            self._insort(
                Session(steps[-1].timestamp(), endSteps[0].timestamp(), True)
            )

        return createAndBeginRuleSession

    @cached_property
    def _rescheduler(self) -> Rescheduler:
        """
        Create the rescheduler and attach necessary observers for it to derive
        a current scheduler state.
        """
        rescheduler = Rescheduler(self._toScheduled)
        addObserver(self.rules, rescheduler.observer("rules"))
        addObserver(
            self.upcomingSessions, rescheduler.observer("upcomingSessions")
        )
        return rescheduler

    def _toScheduled(self) -> Iterable[Cancellable]:
        """
        Re-derive all scheduled calls from the current state of this
        L{SessionManager}.
        """
        for rule in self.rules:
            with StatefulCancel.create() as sc:
                repeatedly(
                    self._civilScheduler,
                    self._beginSessionWithRule(sc, rule),
                    rule.startRule(),
                )
            yield sc

        if self.upcomingSessions:

            def startStaticSession() -> None:
                # TODO: make sure it's … the same session? just generally clean up?
                session = self.activeSession = self.upcomingSessions.pop(0)
                self._rescheduler.reschedule(["just-set-active"])
                self.previousSessions.append(session)

            earliestSession = self.upcomingSessions[0]
            yield self._physicalScheduler.callAt(
                earliestSession.start,
                startStaticSession,
            )

        if self.activeSession is not None:

            def endSession() -> None:
                self.activeSession = None

            yield self._physicalScheduler.callAt(
                self.activeSession.end, endSession
            )

    @classmethod
    def new(
        cls,
        observer: Observer,
        scheduler: Scheduler[float, Callable[[], None], int],
        zone: ZoneInfo,
        sessions: Iterable[Session] = (),
        rules: Iterable[DailySessionRule] = (),
    ) -> SessionManager:
        if zone is None:
            # zone = guessLocalZone()
            zone = ZoneInfo("Etc/UTC")
        dateScale: Scale[DateTime[ZoneInfo], float, float] = DateScale(zone)
        now = scheduler.now()
        branchManager, dateScheduler = branch(scheduler, dateScale)
        upcoming: ObservableList[Session] = ObservableList(IgnoreChanges)
        previous: ObservableList[Session] = ObservableList(IgnoreChanges)
        for session in sessions:
            (upcoming if session.start > now else previous).append(session)
        active: Session | None
        active = previous[0] if previous and previous[0].end > now else None
        self = cls(
            observer=observer,
            upcomingSessions=upcoming,
            previousSessions=previous,
            rules=ObservableList(IgnoreChanges, list(rules)),
            activeSession=active,
            _physicalScheduler=scheduler,
            _civilScheduler=dateScheduler,
        )
        self._rescheduler.reschedule("new")
        return self
