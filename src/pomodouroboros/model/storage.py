# -*- test-case-name: pomodouroboros.model.test -*-

from __future__ import annotations

from datetime import time
from functools import singledispatch
from json import dump, load
from math import inf
from os import makedirs, replace
from os.path import basename, dirname, exists, expanduser, join
from typing import Callable, Iterator, TypeAlias, cast
from zoneinfo import ZoneInfo

from datetype import Time, aware, naive
from fritter.boundaries import Scheduler
from fritter.drivers.memory import MemoryDriver
from fritter.drivers.datetimes import guessLocalZone
from fritter.scheduler import schedulerFromDriver

from pomodouroboros.model.intervals import Idle
from pomodouroboros.model.schema import SavedRule, SavedTime
from pomodouroboros.model.sessions import DailySessionRule, Weekday

from .boundaries import EvaluationResult, IntervalType, UserInterfaceFactory
from .intention import Estimate, Intention
from .intervals import (
    AnyStreakInterval,
    AnyIntervalOrIdle,
    Break,
    Duration,
    Evaluation,
    GracePeriod,
    Pomodoro,
    StartPrompt,
    idleOrPrompt,
)
from .nexus import Nexus
from .observables import IgnoreChanges, ObservableList
from .schema import (
    SavedBreak,
    SavedGracePeriod,
    SavedIntentionID,
    SavedInterval,
    SavedNexus,
    SavedPomodoro,
    SavedStartPrompt,
)
from .sessions import Session, SessionManager


def nexusFromJSON(
    saved: SavedNexus,
    userInterfaceFactory: UserInterfaceFactory,
    issueStartPrompts: bool = True,
) -> Nexus:
    """
    Load a Pomodouroboros Nexus from its saved serialized state.
    """
    intentionIDMap: dict[SavedIntentionID, Intention] = {}
    intentions: list[Intention] = []

    for savedIntention in saved["intentions"]:
        intention = Intention(
            id=int(savedIntention["id"]),
            title=savedIntention["title"],
            created=savedIntention["created"],
            modified=savedIntention["modified"],
            description=savedIntention["description"],
            abandoned=savedIntention["abandoned"],
            estimates=[
                Estimate(
                    duration=savedEstimate["duration"],
                    madeAt=savedEstimate["madeAt"],
                )
                for savedEstimate in savedIntention["estimates"]
            ],
        )
        intentions.append(intention)
        intentionIDMap[savedIntention["id"]] = intention

    def loadInterval(savedInterval: SavedInterval) -> AnyStreakInterval:
        if savedInterval["intervalType"] == "Pomodoro":
            intention = intentionIDMap[savedInterval["intentionID"]]
            evaluation = savedInterval["evaluation"]
            pomodoro = Pomodoro(
                startTime=savedInterval["startTime"],
                intention=intention,
                endTime=savedInterval["endTime"],
                indexInStreak=savedInterval["indexInStreak"],
                evaluation=(
                    Evaluation(
                        EvaluationResult(evaluation["result"]),
                        evaluation["timestamp"],
                    )
                    if evaluation is not None
                    else None
                ),
            )
            intention.pomodoros.append(pomodoro)
            return pomodoro
        elif savedInterval["intervalType"] == "StartPrompt":
            return StartPrompt(
                startTime=savedInterval["startTime"],
                endTime=savedInterval["endTime"],
                pointsBeforeLoss=savedInterval["pointsBeforeLoss"],
                pointsAfterLoss=savedInterval["pointsAfterLoss"],
            )
        elif savedInterval["intervalType"] == "Break":
            return Break(
                startTime=savedInterval["startTime"],
                endTime=savedInterval["endTime"],
            )
        elif savedInterval["intervalType"] == "GracePeriod":
            return GracePeriod(
                startTime=savedInterval["startTime"],
                originalPomEnd=savedInterval["originalPomEnd"],
            )

    previousStreaks = [
        [loadInterval(interval) for interval in savedStreak]
        for savedStreak in saved["previousStreaks"]
    ]
    currentStreak = [
        loadInterval(interval) for interval in saved["currentStreak"]
    ]

    def loadRule(savedRule: SavedRule) -> DailySessionRule:

        def loadOneTime(savedTime: SavedTime) -> Time[None]:
            return naive(
                time.fromisoformat(savedTime["time"]).replace(
                    tzinfo=None,
                ),
            )

        return DailySessionRule(
            dailyStart=loadOneTime(savedRule["dailyStart"]),
            dailyEnd=loadOneTime(savedRule["dailyEnd"]),
            days={Weekday(each) for each in savedRule["days"]},
        )

    lastUpdateTime = saved["lastUpdateTime"]
    scheduler: Scheduler[float, Callable[[], None], int] = schedulerFromDriver(
        driver := MemoryDriver()
    )
    driver.advance(lastUpdateTime)
    sessionRules = [loadRule(rule) for rule in saved.get("sessionRules", [])]
    sessions = [
        Session(
            start=each["start"],
            end=each["end"],
            automatic=bool(each.get("automatic")),
        )
        for each in saved["sessions"]
    ]
    nexus = Nexus(
        scheduler,
        driver,
        _lastIntentionID=int(saved["lastIntentionID"]),
        _intentions=intentions,
        _upcomingDurations=iter(
            [
                Duration(
                    # FIXME: make a function which restricts IntervalType, fix
                    # up the serialized dict to reflect that durations can only
                    # be breaks & pomodoros
                    IntervalType(
                        each["intervalType"]
                    ),  # type:ignore[arg-type]
                    seconds=each["seconds"],
                )
                for each in saved["upcomingDurations"]
            ]
        ),
        _previousStreaks=previousStreaks,
        _currentStreak=currentStreak,
        _interfaceFactory=userInterfaceFactory,
        _sessionManager=SessionManager.new(
            IgnoreChanges,
            scheduler,
            guessLocalZone(),
            sessions,
            sessionRules,
        ),
        # need to deserialize current interval; none-interval means recompute
        # an appropriate idle
        _promptForStartWhenIdleInSession=issueStartPrompts,
    )
    # FIXME: it may be easier to understand to just persist the current
    # interval explicitly and then load it blindly again rather than rederiving
    # it.  Note however that this would mean maintaining a shared mutable
    # reference because ._currentStreak and .currentInterval *must* share a
    # common mutable interval object for (for example) early-evaluation of
    # pomodoros, and any other edits
    nexus.currentInterval = (
        # if we're in a streak then it's the last thing in the streak
        currentStreak[-1]
        if currentStreak and lastUpdateTime < currentStreak[-1].endTime
        else
        # If we're in a session (but *not* a streak as that would be caught
        # above), it's time to prompt
        idleOrPrompt(
            nexus,
            it := nexus._sessionManager.activeSession,
            # FIXME: this is definitely wrong, the correct reference time here
            # would be the end of the streak time
            it.start if it is not None else lastUpdateTime,
        )
    )
    return nexus


def _copyUpcomingDurations(self: Nexus) -> list[Duration]:
    """
    C{_upcomingDurations} is an iterator, but sometimes we need to capture
    it for serialization; exhaust the iterator into a new list, make a new
    iterator of the new list, put the new iterator of the new list back and
    then return a copy of the list that was created.

    This is needed for serialization.
    """
    previouslyUpcoming = list(self._upcomingDurations)

    def split() -> Iterator[Duration]:
        return iter(previouslyUpcoming)

    self._upcomingDurations = split()
    return previouslyUpcoming[:]


def nexusToJSON(nexus: Nexus) -> SavedNexus:
    @singledispatch
    def saveInterval(interval: AnyStreakInterval) -> SavedInterval:
        """
        Save any interval to its paired JSON data structure.
        """
        raise TypeError(f"unsupported type: {interval}")

    @saveInterval.register(Pomodoro)
    def savePomodoro(interval: Pomodoro) -> SavedPomodoro:
        return {
            "startTime": interval.startTime,
            "intentionID": str(interval.intention.id),
            "endTime": interval.endTime,
            "evaluation": (
                {
                    "result": interval.evaluation.result.value,
                    "timestamp": interval.evaluation.timestamp,
                }
                if interval.evaluation is not None
                else None
            ),
            "indexInStreak": interval.indexInStreak,
            "intervalType": "Pomodoro",
        }

    @saveInterval.register(Break)
    def saveBreak(interval: Break) -> SavedBreak:
        return {
            "startTime": interval.startTime,
            "endTime": interval.endTime,
            "intervalType": "Break",
        }

    @saveInterval.register(GracePeriod)
    def saveGracePeriod(interval: GracePeriod) -> SavedGracePeriod:
        return {
            "startTime": interval.startTime,
            "originalPomEnd": interval.originalPomEnd,
            "intervalType": "GracePeriod",
        }

    @saveInterval.register(StartPrompt)
    def saveStartPrompt(interval: StartPrompt) -> SavedStartPrompt:
        return {
            "startTime": interval.startTime,
            "endTime": interval.endTime,
            "pointsBeforeLoss": interval.pointsBeforeLoss,
            "pointsAfterLoss": interval.pointsAfterLoss,
            "intervalType": "StartPrompt",
        }

    return {
        "lastIntentionID": str(nexus._lastIntentionID),
        "intentions": [
            {
                "created": intention.created,
                "modified": intention.modified,
                "title": intention.title,
                "description": intention.description,
                "estimates": [
                    {"duration": estimate.duration, "madeAt": estimate.madeAt}
                    for estimate in intention.estimates
                ],
                "abandoned": intention.abandoned,
                "id": str(intention.id),
            }
            for intention in nexus._intentions
        ],
        "lastUpdateTime": nexus._scheduler.now(),
        "upcomingDurations": [
            {
                "intervalType": duration.intervalType.value,
                "seconds": duration.seconds,
            }
            # TODO: slightly inefficient, don't clone the whole thing just to
            # clone the iterator
            for duration in _copyUpcomingDurations(nexus)
        ],
        "currentStreak": [
            saveInterval(streakInterval)
            for streakInterval in nexus._currentStreak
        ],
        "previousStreaks": [
            [
                saveInterval(streakInterval)
                for streakInterval in streakIntervals
            ]
            for streakIntervals in nexus._previousStreaks
        ],
        "sessions": [
            {
                "start": session.start,
                "end": session.end,
                "automatic": session.automatic,
            }
            for session in [
                *nexus._sessionManager.previousSessions,
                *nexus._sessionManager.upcomingSessions,
            ]
        ],
        "sessionRules": [
            {
                "dailyStart": {
                    "time": rule.dailyStart.isoformat(),
                },
                "dailyEnd": {
                    "time": rule.dailyEnd.isoformat(),
                },
                "days": [day.value for day in rule.days],
            }
            for rule in nexus._sessionManager.rules
        ],
    }


JSON: TypeAlias = (
    "None | str | float | bool | dict[str, JSON] | list[JSON] | SavedNexus"
)


def saveToFile(filename: str, jsonObject: JSON) -> None:
    """
    Save the given JSON object to a file.
    """
    newp = join(dirname(filename), ".temporary-" + basename(filename) + ".new")
    with open(newp, "w") as new:
        dump(jsonObject, new)
    replace(newp, filename)


def loadFromFile(filename: str) -> JSON:
    with open(filename) as f:
        result: JSON = load(f)
        return result


defaultNexusFile = expanduser(
    "~/.local/share/pomodouroboros/current-nexus.json"
)


def loadDefaultNexus(
    currentTime: float,
    userInterfaceFactory: UserInterfaceFactory,
) -> Nexus:
    """
    Load the default nexus.
    """
    if exists(defaultNexusFile):
        # TODO: probably need to be extremely careful before shipping to
        # end-users here, since failing to create a nexus makes the app
        # unlaunchable
        loaded = nexusFromJSON(
            cast(
                SavedNexus,
                loadFromFile(defaultNexusFile),
            ),
            userInterfaceFactory,
        )
        loaded.advanceToTime(currentTime)
        return loaded
    # See pomodouroboros.model.nexus.Nexus.blank() for an explanation fo this
    # interval
    sched: Scheduler[float, Callable[[], None], int] = schedulerFromDriver(
        driver := MemoryDriver()
    )
    return Nexus(
        sched,
        driver,
        userInterfaceFactory,
        0,
        _sessionManager=SessionManager.new(
            IgnoreChanges, sched, guessLocalZone()
        ),
    )


def saveDefaultNexus(nexus: Nexus) -> None:
    """
    Save a given nexus to the default file for the current user.
    """
    makedirs(dirname(defaultNexusFile), exist_ok=True)
    saveToFile(defaultNexusFile, nexusToJSON(nexus))
