# -*- test-case-name: pomodouroboros.model.test -*-
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from math import inf
from typing import Callable, Iterable, Iterator, MutableSequence, Sequence
from zoneinfo import ZoneInfo

from datetype import aware, DateTime
from fritter.boundaries import ScheduledCall, Scheduler, PhysicalScheduler
from fritter.drivers.datetimes import DateTimeDriver, guessLocalZone, DateScale
from fritter.drivers.memory import MemoryDriver
from fritter.drivers.twisted import TwistedTimeDriver
from fritter.scheduler import schedulerFromDriver
from fritter.tree import branch, Scale, BranchManager

from .boundaries import (
    EvaluationResult,
    IntervalType,
    NoUserInterface,
    PomStartResult,
    ScoreEvent,
    UIEventListener,
    UserInterfaceFactory,
)
from .debugger import debug
from .intention import Estimate, Intention
from .intervals import (
    AnyIntervalOrIdle,
    AnyStreakInterval,
    Break,
    Duration,
    Evaluation,
    GracePeriod,
    Idle,
    Pomodoro,
    StartPrompt,
)
from .observables import Changes, IgnoreChanges, ObservableList
from .sessions import (
    SessionManager,
    DailySessionRule,
    Session,
)


@dataclass(frozen=True)
class StreakRules:
    """
    The rules for what intervals should be part of a streak.
    """

    streakIntervalDurations: Sequence[Duration] = field(
        default_factory=lambda: [
            each
            for pomMinutes, breakMinutes in [
                (5, 5),
                (10, 5),
                (20, 5),
                (30, 10),
            ]
            for each in [
                Duration(IntervalType.Pomodoro, pomMinutes * 60),
                Duration(IntervalType.Break, breakMinutes * 60),
            ]
        ]
    )


_theNoUserInterface: UIEventListener = NoUserInterface()


def _noUIFactory(nexus: Nexus) -> UIEventListener:
    return _theNoUserInterface


def intervalOverlap(
    startTimeA: float, endTimeA: float, startTimeB: float, endTimeB: float
) -> bool:

    assert startTimeA <= endTimeA
    assert startTimeB <= endTimeB

    return (
        (startTimeA <= endTimeB)
        and (endTimeA >= startTimeB)
        and (startTimeB <= endTimeA)
    )


@dataclass
class Nexus:
    """
    Nexus where all the models of the user's ongoing pomodoro experience are
    coordinated, dispatched, and collected for things like serialization.
    """

    _scheduler: Scheduler[float, Callable[[], None], int]
    _memDriver: MemoryDriver

    _interfaceFactory: UserInterfaceFactory
    "A factory to create a user interface as the Nexus is being instantiated."

    _lastIntentionID: int
    """
    The last ID used for an intention, incremented by 1 each time a new one is
    created.
    """

    _liveInterval: AnyIntervalOrIdle
    """
    The current interval that is executing.

    XXX this is the mutable replacement for _activeInterval, named differently
    while implementing so as to avoid confusion
    """

    _sessionManager: SessionManager
    """
    The manager of and creator of session objects.
    """

    _intentions: MutableSequence[Intention] = field(
        default_factory=lambda: ObservableList(IgnoreChanges)
    )
    "A list of all the intentions that the user has specified."
    # TODO: intentions should be archived like streaks.

    _userInterface: UIEventListener | None = None
    "The user interface to deliver information to."

    _upcomingDurations: Iterator[Duration] = iter(())
    "The durations that are upcoming in the current streak."

    _streakRules: StreakRules = field(default_factory=StreakRules)
    """
    The rules of what constitutes a streak; how long the durations of breaks
    and pomodoros are.
    """

    # TODO: there should be other types of rules via DailySessionRule

    _previousStreaks: list[list[AnyStreakInterval]] = field(
        default_factory=list
    )
    "An archive of the previous streaks that the user has completed."

    _currentStreak: list[AnyStreakInterval] = field(default_factory=list)
    "The user's current streak."

    _promptForStartWhenIdleInSession: bool = True
    """
    If true, generate start prompts based on potential score loss (before end
    of session) during active sessions.
    """

    _lastUpdateTime: float = field(default=0.0)

    """
    I want to put the nexus into a state where there is always an active
    interval, always scheduled against _scheduler to do something upon its end.
    One way to do this is to force the caller to pass in a _scheduler *and* a
    current interval, then make the 'front door' construction a classmethod
    that builds this for us.  Which should be fine, because there are only a
    few call sites for constructing a nexus, even the tests only have a single
    one in setUp.

    So how do we compute the initial active interval?  Very much like
    _activeInterval currently does.  We can refer to the scheduler's now()
    rather than lastUpdateTime.
    """

    def _newIdleInterval(self) -> Idle:
        nextSessionTime = self._sessionManager.upcomingSessionStartTime(
            self._lastUpdateTime
        )
        return Idle(startTime=self._lastUpdateTime, endTime=nextSessionTime)

    @property
    def _activeInterval(self) -> AnyIntervalOrIdle:
        if not self._currentStreak:
            return self._newIdleInterval()

        candidateInterval = self._currentStreak[-1]
        now = self._lastUpdateTime

        if now < candidateInterval.startTime:
            # when would this happen? interval at the end of the current streak
            # somehow has not started?
            return self._newIdleInterval()

        if now > candidateInterval.endTime:
            # We've moved on past the end of the interval, so it is no longer
            # active.  Note: this corner of the logic is extremely finicky,
            # because evaluating the currently-executing pomodoro depends on it
            # *remaining* the _activeInterval while doing advanceToTime at the
            # current timestamp.  therefore '>=' would be incorrect here in an
            # important way, even though these values are normally real time
            # and therefore not meaningfully comparable on exact equality.
            debug("active interval: now after end")
            return self._newIdleInterval()
        debug("active interval: yay:", candidateInterval)
        return candidateInterval

    def blank(self) -> Nexus:
        """
        Create a new, blank Nexus, with no attached UI, in the same time zone
        as this one.

        @see: L{pomodouroboros.model.storage.loadDefaultNexus}; a little bit of
            duplication here, since we are "idle forever" before any data
            exists.
        """
        # this is a new, blank nexus, so we can know that the active interval
        # is going to be an Idle interval that goes forever.
        currentInterval = Idle(startTime=0.0, endTime=inf)
        sched: Scheduler[float, Callable[[], None], int] = schedulerFromDriver(
            driver := MemoryDriver()
        )
        return self.__class__(
            sched,
            driver,
            _lastIntentionID=1000,
            _interfaceFactory=_noUIFactory,
            _userInterface=_theNoUserInterface,
            _liveInterval=currentInterval,
            _sessionManager=SessionManager.new(
                IgnoreChanges,
                sched,
                self._sessionManager._civilScheduler.now().tzinfo,
            ),
        )

    def cloneWithoutUI(self) -> Nexus:
        """
        Create a deep copy of this L{Nexus}, detached from any user interface,
        to perform hypothetical model interactions.
        """
        debug("constructing hypothetical")
        from .storage import nexusFromJSON, nexusToJSON

        hypothetical = nexusFromJSON(nexusToJSON(self), _noUIFactory)
        # Given that we are creating this hypothetical future to determine when
        # to emit our next start prompt, configure it such that advancing its
        # timeline will not recursively attempt to perform the same
        # computation.
        hypothetical._promptForStartWhenIdleInSession = False
        debug("constructed")
        return hypothetical

    def intervalsBetween(
        self, startTime: float, endTime: float
    ) -> Iterable[AnyStreakInterval]:
        for streak in self._previousStreaks + [self._currentStreak]:
            for interval in streak:
                if intervalOverlap(
                    startTime, endTime, interval.startTime, interval.endTime
                ):
                    yield interval

    def scoreEvents(
        self, *, startTime: float | None = None, endTime: float | None = None
    ) -> Iterable[ScoreEvent]:
        """
        Get all score-relevant events since the given timestamp.
        """
        if startTime is None:
            startTime = 0.0
        if endTime is None:
            endTime = self._lastUpdateTime
        for intentionIndex, intention in enumerate(self._intentions):
            for event in intention.intentionScoreEvents(intentionIndex):
                if startTime <= event.time and event.time <= endTime:
                    yield event
        for streak in self._previousStreaks + [self._currentStreak]:
            for interval in streak:
                if interval.startTime >= startTime:
                    for event in interval.scoreEvents():
                        debug(
                            "score", event.time > endTime, event, event.points
                        )
                        if startTime <= event.time and event.time <= endTime:
                            yield event

    @property
    def userInterface(self) -> UIEventListener:
        """
        build the user interface on demand
        """
        if self._userInterface is None:
            debug("creating user interface for the first time")
            ui: UIEventListener = self._interfaceFactory(self)
            debug("creating user interface for the first time", ui)
            self._userInterface = ui
            active = self._activeInterval
            if active is not None:
                debug("UI reification interval start", active)
                ui.intervalStart(active)
            else:
                debug("UI reification but no interval running", self._streaks)
        return self._userInterface

    @property
    def intentions(self) -> Sequence[Intention]:
        return self._intentions

    @property
    def availableIntentions(self) -> Sequence[Intention]:
        """
        This property is a list of all intentions that are available for the
        user to select for a new pomodoro.
        """
        return [
            i for i in self._intentions if not i.completed and not i.abandoned
        ]

    def _updateLastUpdate(self, newTime: float) -> None:
        """
        Update L{Nexus._lastUpdateTime} to C{newTime}, as well as running any
        timed calls scheduled against L{Nexus._memDriver}.
        """
        self._lastUpdateTime = newTime
        self._memDriver.advance(newTime - self._memDriver.now())

    def advanceToTime(self, newTime: float) -> None:
        """
        Advance to the epoch time given.
        """
        # ensure lazy user-interface is reified before we start updating so
        # that notifications of interval starts happen in the correct order
        # (particularly important so tests can be exact).
        self.userInterface

        debug("begin advance from", self._lastUpdateTime, "to", newTime)
        earlyEvaluationSpecialCase = (
            # if our current streak is not empty (i.e. we are continuing it)
            self._currentStreak
            # and the current end time happens to correspond *exactly* to the
            # last update time
            and self._currentStreak[-1].endTime == self._lastUpdateTime
            # then even if the new time has not moved and we are still on the
            # last update time exactly, we need to process a loop update
            # because the timer at the end of the interval has moved.
        )
        while self._lastUpdateTime < newTime or earlyEvaluationSpecialCase:
            earlyEvaluationSpecialCase = False
            newInterval: AnyStreakInterval | None = None
            currentInterval = self._activeInterval
            if isinstance(currentInterval, Idle):
                # If there's no current interval then there's nothing to end
                # and we can skip forward to current time, and let the start
                # prompt just begin at the current time, not some point in the
                # past where some reminder *might* have been appropriate.
                self._updateLastUpdate(newTime)
                debug("interval None, update to real time", newTime)

                if self._promptForStartWhenIdleInSession and (
                    # If we are configured to prompt the user to get started
                    # when they're in a session, then compute an ideal score
                    # with which to prompt the user. (See cloneWithoutUI for
                    # implementation notes.)
                    (activeSession := self._sessionManager.activeSession)
                    is not None
                    and (
                        nextDrop := (
                            scoreInfo := activeSession.idealScoreFor(self)
                        ).nextPointLoss
                    )
                    is not None
                    and nextDrop > newTime
                ):
                    newInterval = StartPrompt(
                        self._lastUpdateTime,
                        nextDrop,
                        scoreInfo.scoreBeforeLoss(),
                        scoreInfo.scoreAfterLoss(),
                    )
            else:
                if newTime >= currentInterval.endTime:
                    self._updateLastUpdate(currentInterval.endTime)

                    if currentInterval.intervalType in {
                        GracePeriod.intervalType,
                        StartPrompt.intervalType,
                    }:
                        # New streaks begin when grace periods expire.
                        self._upcomingDurations = iter(())

                    newDuration = next(self._upcomingDurations, None)
                    self.userInterface.intervalProgress(1.0)
                    self.userInterface.intervalEnd()
                    # in this implementation, there is a missing test case:
                    # if we fall off the end of the streak rule, and it's
                    # time to issue another StartPrompt after the final
                    # break (or, hypothetically, the final pomodoro if we
                    # organize a streak rule like that) we just … won't.
                    if newDuration is None:
                        # XXX needs test coverage
                        previous, self._currentStreak = (
                            self._currentStreak,
                            [],
                        )
                        assert (
                            previous
                        ), "rolling off the end of a streak but the streak is empty somehow"
                        self._previousStreaks.append(previous)
                    else:
                        newInterval = preludeIntervalMap[
                            newDuration.intervalType
                        ](
                            currentInterval.endTime,
                            currentInterval.endTime + newDuration.seconds,
                        )
                else:
                    # We're landing in the middle of an interval, so we need to
                    # update its progress.  If it's in the middle then we can
                    # move time all the way forward.
                    self._updateLastUpdate(newTime)
                    elapsedWithinInterval = newTime - currentInterval.startTime
                    intervalDuration = (
                        currentInterval.endTime - currentInterval.startTime
                    )
                    self.userInterface.intervalProgress(
                        elapsedWithinInterval / intervalDuration
                    )

            # if we created a new interval for any reason on this iteration
            # through the loop, then we need to mention that fact to the UI.
            if newInterval is not None:
                self._createdInterval(newInterval)
                # should really be active now
                assert self._activeInterval is newInterval

    def _createdInterval(self, newInterval: AnyStreakInterval) -> None:
        self._currentStreak.append(newInterval)
        self.userInterface.intervalStart(newInterval)
        self.userInterface.intervalProgress(0.0)

    def addIntention(
        self,
        title: str = "",
        description: str = "",
        estimate: float | None = None,
    ) -> Intention:
        """
        Add an intention with the given description and time estimate.
        """
        self._lastIntentionID += 1
        newID = self._lastIntentionID
        self._intentions.append(
            newIntention := Intention(
                newID,
                self._lastUpdateTime,
                self._lastUpdateTime,
                title,
                description,
            )
        )
        if estimate is not None:
            newIntention.estimates.append(
                Estimate(duration=estimate, madeAt=self._lastUpdateTime)
            )
        return newIntention

    def addManualSession(self, startTime: float, endTime: float) -> None:
        """
        Add a 'work session'; a discrete interval where we will be scored, and
        notified of potential drops to our score if we don't set intentions.
        """
        self._sessionManager.addManualSession(startTime, endTime)

    def startPomodoro(self, intention: Intention) -> PomStartResult:
        """
        When you start a pomodoro, the length of time set by the pomodoro is
        determined by your current streak so it's not a parameter.
        """

        def startPom(startTime: float, endTime: float) -> None:
            newPomodoro = Pomodoro(
                intention=intention,
                indexInStreak=sum(
                    isinstance(each, Pomodoro) for each in self._currentStreak
                ),
                startTime=startTime,
                endTime=endTime,
            )
            intention.pomodoros.append(newPomodoro)
            self._createdInterval(newPomodoro)

        return self._activeInterval.handleStartPom(self, startPom)

    def evaluatePomodoro(
        self, pomodoro: Pomodoro, result: EvaluationResult
    ) -> None:
        """
        The user has determined the success criteria.
        """
        timestamp = self._lastUpdateTime
        pomodoro.evaluation = Evaluation(result, timestamp)
        if result == EvaluationResult.achieved:
            assert (
                pomodoro.intention.completed
            ), "evaluation was set, should be complete"
            if timestamp < pomodoro.endTime:
                # We evaluated the pomodoro as *complete* early, which is a
                # special case.  Evaluating it in other ways allows it to
                # continue.  (Might want an 'are you sure' in the UI for this,
                # since other evaluations can be reversed.)
                assert pomodoro is (
                    active := self._activeInterval
                ), f"""
                   the pomodoro {pomodoro} is not ended yet, but it is not the
                   active interval {active}
                   """
                pomodoro.endTime = timestamp
                # We now need to advance back to the current time since we've
                # changed the landscape; there's a new interval that now starts
                # there, and we need to emit our final progress notification
                # and build that new interval.
                self.advanceToTime(self._lastUpdateTime)

    def _intervalJustEnded(self) -> None:
        """
        An interval just ended, specifically because its endTime elapsed.

        Explicit user actions may also end an interval.

        if time is actually passing then::

            Idle->StartPrompt
            StartPrompt->new StartPrompt  # if there's more time left in the session

            StartPrompt->Idle       # when the session expires mid-startprompt
                                    # (it feels like this isn't actually possible,
                                    # due to the way it's calculated? session-end
                                    # will always be an inflection point?)

            Pomodoro->Break         # when pomodoro done
            Break->StartPrompt      # when break done

            # due to user actions,
            StartPrompt->Pomodoro   # set intention explicitly
            GracePeriod->Pomodoro   # set intention to continue streak
            Pomodoro->Break         # evaluate pomodoro early

        What do we do?
        """


preludeIntervalMap: dict[IntervalType, type[GracePeriod | Break]] = {
    Pomodoro.intervalType: GracePeriod,
    Break.intervalType: Break,
}
