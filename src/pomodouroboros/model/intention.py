# -*- test-case-name: pomodouroboros.model.test -*-
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from itertools import islice
from typing import TYPE_CHECKING, Iterable

from .boundaries import EvaluationResult, ScoreEvent
from .observables import IgnoreChanges, Observer, observable
from .scoring import (
    AttemptedEstimation,
    EstimationAccuracy,
    IntentionCompleted,
    IntentionCreatedEvent,
)

if TYPE_CHECKING:
    from .intervals import Pomodoro


@dataclass
class Estimate:
    """
    A guess was made about how long an L{Intention} would take to complete.
    """

    duration: float  # how long do we think the thing is going to take?
    madeAt: float  # when was this estimate made?


@observable()
class Intention:
    """
    An intention of something to do.
    """

    id: int
    created: float
    modified: float
    title: str
    description: str
    estimates: list[Estimate] = field(default_factory=list)
    pomodoros: list[Pomodoro] = field(default_factory=list)
    abandoned: bool = False

    observer: Observer = field(default_factory=IgnoreChanges)
    # id: ULID = field(default_factory=new_ulid, compare=False)

    def _compref(self) -> dict[str, object]:
        """
        Get a reference copy of data, in the format of a dict of goop, for
        comparison.
        """
        return asdict(
            replace(
                self,
                pomodoros=[
                    replace(
                        each,
                        # we're just going to dump it into a dict here anyway,
                        # so the type ignore isn't a big deal
                        intention=None,  # type:ignore[arg-type]
                        # existing observer points at both the whole nexus and
                        # the UI and will this not be deep-copyable
                        observer=IgnoreChanges,
                    )
                    for each in self.pomodoros
                ],
                id=None,  # type:ignore[arg-type]
            )
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Intention):
            return NotImplemented
        return self._compref() == other._compref()

    @property
    def completed(self) -> bool:
        """
        Has this intention been completed?
        """
        return (
            False
            if not self.pomodoros
            else (evaluation := self.pomodoros[-1].evaluation) is not None
            and evaluation.result == EvaluationResult.achieved
        )

    def intentionScoreEvents(
        self, intentionIndex: int
    ) -> Iterable[ScoreEvent]:
        yield IntentionCreatedEvent(self, intentionIndex)
        for estimate in islice(self.estimates, len(self.pomodoros) + 1):
            # Only give a point for one estimation per attempt; estimating is
            # good, but correcting more than once per work session is just
            # faffing around
            yield AttemptedEstimation(estimate)
        if self.completed:
            yield IntentionCompleted(self)
            if self.estimates:
                yield EstimationAccuracy(self)
