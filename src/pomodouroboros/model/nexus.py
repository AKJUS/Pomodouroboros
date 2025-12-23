from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from math import inf
from typing import Any, Callable, Iterable, Iterator, MutableSequence, Sequence
from zoneinfo import ZoneInfo

from datetype import DateTime, aware
from fritter.boundaries import (
    Cancellable,
    PhysicalScheduler,
    ScheduledCall,
    Scheduler,
)
from fritter.drivers.datetimes import DateScale, DateTimeDriver, guessLocalZone
from fritter.drivers.memory import MemoryDriver
from fritter.drivers.twisted import TwistedTimeDriver
from fritter.scheduler import schedulerFromDriver
from fritter.tree import BranchManager, Scale, branch

from pomodouroboros.model.observables import Filter

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
from .observables import (
    Changes,
    IgnoreChanges,
    ObservableList,
    Observer,
    addObserver,
    observable,
)
from .rescheduling import Rescheduler
from .sessions import (
    DailySessionRule,
    Session,
    SessionManager,
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


@observable()
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

    currentInterval: AnyIntervalOrIdle = field(
        default_factory=lambda: Idle(0.0, inf)
    )
    observer: Observer = IgnoreChanges

    def __post_init__(self) -> None:
        def endInterval() -> None:
            debug("ending interval", self.currentInterval)
            newInterval = self.currentInterval.buildNextInterval(
                self,
                self._sessionManager.activeSession,
                self._upcomingDurations,
            )
            debug("starting new interval", newInterval)
            self.currentInterval = newInterval
            debug("new interval started")

        @Rescheduler
        def intervalEndSchedule() -> Iterable[Cancellable]:
            yield self._scheduler.callAt(
                self.currentInterval.endTime, endInterval
            )

        def filtered(observee: object, name: str) -> Changes[str, object]:
            filter: Filter[str, object] = Filter(name)
            addObserver(observee, filter)
            return filter

        justCurrentInterval = filtered(self, "currentInterval")
        intervalEndSchedule.observe(justCurrentInterval)

        def startNewInterval(
            oldInterval: AnyStreakInterval | None,
            newInterval: AnyStreakInterval,
        ) -> None:
            debug("***START NEW INTERVAL", newInterval)
            self._currentStreak.append(newInterval)
            debug("***intervalStart UI")
            self.userInterface.intervalStart(newInterval)
            debug("***intervalProgress UI")
            self.userInterface.intervalProgress(0.0)
            debug("done with new interval start")

        @dataclass
        class AfterChanger:
            change: Callable[[Any, Any], None]

            @contextmanager
            def added(self, key: str, new: Any) -> Iterator[None]:
                yield
                self.change(None, new)

            @contextmanager
            def changed(
                self, key: str, old: object, new: Any
            ) -> Iterator[None]:
                yield
                self.change(new, new)

            @contextmanager
            def removed(self, key: str, old: Any) -> Iterator[None]:
                assert 0, "this should not be removed"
                yield

            def child(self, key: str) -> Changes[Any, Any]:
                # TODO: should not actually ignore changes on sub-objects
                return IgnoreChanges

        def startNewSession(
            oldSession: Session | None, newSession: Session
        ) -> None:
            if not isinstance(self.currentInterval, Idle):
                debug("SESSION STARTING WHILE NOT IDLE", self.currentInterval)
                return
            debug("SESSION START CHECK!")
            if self._promptForStartWhenIdleInSession and (
                # If we are configured to prompt the user to get started
                # when they're in a session, then compute an ideal score
                # with which to prompt the user. (See cloneWithoutUI for
                # implementation notes.)
                newSession is not None
                and (
                    nextDrop := (
                        scoreInfo := newSession.idealScoreFor(self)
                    ).nextPointLoss
                )
                is not None
            ):
                debug("MAKING START PROMPT!")
                self.currentInterval = StartPrompt(
                    newSession.start,
                    nextDrop,
                    scoreInfo.scoreBeforeLoss(),
                    scoreInfo.scoreAfterLoss(),
                )
            debug("SESSION START CHECK COMPLETE")

        addObserver(justCurrentInterval, AfterChanger(startNewInterval))
        addObserver(
            filtered(self._sessionManager, "activeSession"),
            AfterChanger(startNewSession),
        )

    def blank(self) -> Nexus:
        """
        Create a new, blank Nexus, with no attached UI, in the same time zone
        as this one.

        @see: L{pomodouroboros.model.storage.loadDefaultNexus}; a little bit of
            duplication here, since we are "idle forever" before any data
            exists.
        """
        sched: Scheduler[float, Callable[[], None], int] = schedulerFromDriver(
            driver := MemoryDriver()
        )
        return self.__class__(
            sched,
            driver,
            _lastIntentionID=1000,
            _interfaceFactory=_noUIFactory,
            _userInterface=_theNoUserInterface,
            _sessionManager=SessionManager.new(
                IgnoreChanges,
                sched,
                self._sessionManager.zone,
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
            endTime = self._scheduler.now()
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
            if (active := self.currentInterval) is not None:
                debug("UI reification interval start", active)
                ui.intervalStart(active)
            else:
                debug(
                    "UI reification but no interval running",
                    self._previousStreaks,
                )
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

    def advanceToTime(self, newTime: float) -> None:
        """
        Advance to the epoch time given.
        """
        # self._memDriver.step(until=newTime)
        self._memDriver.advance(newTime - self._memDriver.now())
        self.userInterface.intervalProgress(
            (newTime - self.currentInterval.startTime)
            / (self.currentInterval.endTime - self.currentInterval.startTime)
        )

    def endStreak(self) -> None:
        """
        The streak has ended.
        """
        previous, self._currentStreak = self._currentStreak, []
        self._previousStreaks.append(previous)

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
        now = self._scheduler.now()
        self._intentions.append(
            newIntention := Intention(newID, now, now, title, description)
        )
        if estimate is not None:
            newIntention.estimates.append(
                Estimate(duration=estimate, madeAt=now)
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
            debug("actually starting the pomodoro")
            newPomodoro = Pomodoro(
                intention=intention,
                indexInStreak=sum(
                    isinstance(each, Pomodoro) for each in self._currentStreak
                ),
                startTime=startTime,
                endTime=endTime,
            )
            intention.pomodoros.append(newPomodoro)
            debug("assigning the pomodoro")
            self.currentInterval = newPomodoro
            debug("assigned")

        debug("invoking handleStartPom on", self.currentInterval)
        return self.currentInterval.handleStartPom(self, startPom)

    def evaluatePomodoro(
        self, pomodoro: Pomodoro, result: EvaluationResult
    ) -> None:
        """
        The user has determined the success criteria.
        """
