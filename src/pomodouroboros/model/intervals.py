from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Callable,
    ClassVar,
    Iterable,
    Iterator,
    Literal,
)

from .boundaries import (
    EvaluationResult,
    IntervalType,
    PomStartResult,
    ScoreEvent,
)
from .debugger import debug
from .intention import Intention
from .observables import IgnoreChanges, Observer, observable
from .scoring import BreakCompleted, EvaluationScore, IntentionSet
from .sessions import Session

if TYPE_CHECKING:
    from .nexus import Nexus


@dataclass(frozen=True)
class Duration:
    """
    A duration describes the amount of time that a 'real' interval (i.e. either
    break or pomodoro) that will be generated in a continuing streak.
    """

    intervalType: Literal[IntervalType.Pomodoro] | Literal[IntervalType.Break]
    seconds: float

    def buildNext(
        self,
        nexus: Nexus,
        session: Session | None,
        previous: AnyIntervalOrIdle,
    ) -> AnyIntervalOrIdle:
        startTime = previous.endTime
        endTime = startTime + self.seconds
        match self.intervalType:
            case IntervalType.Pomodoro:
                if session is not None:
                    return GracePeriod(startTime, endTime)
                else:
                    # outside of a session, return to idle
                    return Idle.fromNexus(nexus, startTime)

            case IntervalType.Break:
                return Break(startTime, endTime)


@dataclass
class Evaluation:
    """
    A decision by the user about the successfulness of the intention associated
    with a pomodoro.
    """

    result: EvaluationResult
    timestamp: float

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        yield EvaluationScore(self.timestamp, self.result.points)


@dataclass
class Break:
    """
    Interval where the user is taking some open-ended time to relax, with no
    specific intention.
    """

    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.Break

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return [BreakCompleted(self)]

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        return PomStartResult.OnBreak

    def buildNextInterval(
        self,
        nexus: Nexus,
        session: Session | None,
        durations: Iterator[Duration],
    ) -> AnyIntervalOrIdle:
        return buildNextInStreak(self, nexus, session, durations)


def idleOrPrompt(
    nexus: Nexus, session: Session | None, referenceTime: float
) -> Idle | StartPrompt:
    """
    We have rolled off the end of a streak or a grace period, and it's time to
    start prompting the user to start a new streak with a StartPrompt, or to go
    back to idle with an Idle.
    """
    nexus.endStreak()
    # now = nexus._scheduler.now()
    if session is None or not nexus._promptForStartWhenIdleInSession:
        return Idle.fromNexus(nexus, referenceTime)
    else:
        scoreInfo = session.idealScoreFor(nexus)
        nextDrop = scoreInfo.nextPointLoss
        return StartPrompt(
            referenceTime,
            nextDrop,
            scoreInfo.scoreBeforeLoss(),
            scoreInfo.scoreAfterLoss(),
        )


def buildNextInStreak(
    streakInterval: Break | Pomodoro,
    nexus: Nexus,
    session: Session | None,
    durations: Iterator[Duration],
) -> AnyIntervalOrIdle:
    newDuration = next(durations, None)
    if newDuration is None:
        return idleOrPrompt(nexus, session, streakInterval.endTime)
    else:
        newIntentionType = preludeIntervalMap[newDuration.intervalType]
        return newIntentionType(
            streakInterval.endTime,
            streakInterval.endTime + newDuration.seconds,
        )


@observable()
class Pomodoro:
    """
    Interval where the user has set an intention and is attempting to do
    something.
    """

    startTime: float
    intention: Intention
    endTime: float
    indexInStreak: int

    evaluation: Evaluation | None = None
    intervalType: ClassVar[IntervalType] = IntervalType.Pomodoro
    observer: Observer = field(
        default_factory=IgnoreChanges, compare=False, repr=False
    )

    def buildNextInterval(
        self,
        nexus: Nexus,
        session: Session | None,
        durations: Iterator[Duration],
    ) -> AnyIntervalOrIdle:
        duration = next(durations, None)
        if duration is not None:
            return duration.buildNext(nexus, session, self)
        # FIXME: INCORRECT!  if the streak runs out in a session, we need to
        # cycle back around to the beginning?
        return Idle.fromNexus(nexus, self.endTime)

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        return PomStartResult.AlreadyStarted

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        yield IntentionSet(
            intention=self.intention,
            time=self.startTime,
            duration=self.endTime - self.startTime,
            streakLength=self.indexInStreak,
        )
        if self.evaluation is not None:
            yield from self.evaluation.scoreEvents()


@dataclass
class GracePeriod:
    """
    Interval where the user is in a streak, but is taking some time to set the
    intention before the next Pomodoro interval gets started.
    """

    startTime: float
    originalPomEnd: float
    intervalType: ClassVar[IntervalType] = IntervalType.GracePeriod

    def buildNextInterval(
        self,
        nexus: Nexus,
        session: Session | None,
        durations: Iterator[Duration],
    ) -> AnyIntervalOrIdle:
        # grace period expired, time to break the streak.
        return idleOrPrompt(nexus, session, self.endTime)

    @property
    def endTime(self) -> float:
        """
        Compute the end time from the grace period.

        This is the time at which the grace period itself ends (and, if it
        elapses, when we will break the streak), in contrast to
        C{originalPomEnd}, the time at which the L{Pomodoro} interval for which
        this L{GracePeriod} is temporarily standing in will end if an intention
        is set.
        """
        return self.startTime + ((self.originalPomEnd - self.startTime) / 3)

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        """
        A L{GracePeriod} awards no points for anything; the hope is that it
        will be replaced by a pomodoro.
        """
        return ()

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        # if it's a grace period then we're going to replace it, same start
        # time, same original end time (the grace period itself may be
        # shorter)
        startPom(self.startTime, self.originalPomEnd)
        return PomStartResult.Continued


@dataclass
class StartPrompt:
    """
    Interval where the user is not currently in a streak, and we are prompting
    them to get started.
    """

    startTime: float
    endTime: float
    pointsBeforeLoss: float
    pointsAfterLoss: float

    intervalType: ClassVar[IntervalType] = IntervalType.StartPrompt

    def buildNextInterval(
        self,
        nexus: Nexus,
        session: Session | None,
        durations: Iterator[Duration],
    ) -> AnyIntervalOrIdle:
        # refactor with startNewSession
        return idleOrPrompt(nexus, session, self.endTime)

    @property
    def pointsLost(self) -> float:
        """
        Convenience attribute to compute the number of points that will be
        lost.
        """
        return self.pointsBeforeLoss - self.pointsAfterLoss

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return ()

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        nexus.userInterface.intervalProgress(1.0)
        nexus.userInterface.intervalEnd()
        return handleIdleStartPom(nexus, startPom)


@dataclass
class Idle:
    startTime: float
    endTime: float
    intervalType: ClassVar[IntervalType] = IntervalType.Idle

    @classmethod
    def fromNexus(cls, nexus: Nexus, timestamp: float) -> Idle:
        return cls(
            timestamp,
            nexus._sessionManager.upcomingSessionStartTime(timestamp),
        )

    def buildNextInterval(
        self,
        nexus: Nexus,
        session: Session | None,
        durations: Iterator[Duration],
    ) -> AnyIntervalOrIdle:
        # FIXME: no tests!
        debug("Idle idling out", self.startTime, self.endTime, session)
        return idleOrPrompt(nexus, session, self.endTime)

    def scoreEvents(self) -> Iterable[ScoreEvent]:
        return ()

    def handleStartPom(
        self, nexus: Nexus, startPom: Callable[[float, float], None]
    ) -> PomStartResult:
        nexus.userInterface.intervalProgress(1.0)
        nexus.userInterface.intervalEnd()
        return handleIdleStartPom(nexus, startPom)


AnyStreakInterval = Pomodoro | Break | GracePeriod | StartPrompt
"""
Any interval that can occur in a streak.
"""
AnyIntervalOrIdle = AnyStreakInterval | Idle
"""
Any interval at all.
"""

AnyRealInterval = Pomodoro | Break
"""
'Real' intervals are those which persist as a historical record past the end of
their elapsed time.  Grace periods and start prompts are temporary placeholders
which are replaced by a started pomodoro once it gets going; start prompts are
just removed and grace periods are clipped out in-place with the start of the
pomodoro going back to their genesis.
"""


def handleIdleStartPom(
    nexus: Nexus, startPom: Callable[[float, float], None]
) -> PomStartResult:
    nexus._upcomingDurations = iter(nexus._streakRules.streakIntervalDurations)
    nextDuration = next(nexus._upcomingDurations, None)
    assert (
        nextDuration is not None
    ), "empty streak interval durations is invalid"
    assert (
        nextDuration.intervalType == IntervalType.Pomodoro
    ), "streak must begin with a pomodoro"

    startTime = nexus._scheduler.now()
    endTime = nexus._scheduler.now() + nextDuration.seconds

    startPom(startTime, endTime)
    return PomStartResult.Started


preludeIntervalMap: dict[IntervalType, type[GracePeriod | Break]] = {
    Pomodoro.intervalType: GracePeriod,
    Break.intervalType: Break,
}
