"""
Utility for repeatedly re-scheduling a group of scheduled events derived from a
given object.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Sequence

from fritter.boundaries import Cancellable

from .observables import Changes, addObserver


@dataclass
class Rescheduler:
    """
    A L{Rescheduler} tracks changes on one or more objects, and, after they
    change, re-derives a group of scheduled calls.
    """

    scheduleCallback: Callable[[], Iterable[Cancellable]]
    _currentlyScheduled: list[Cancellable] = field(default_factory=list)

    def _reschedule(self, path: Sequence[object] = ()) -> None:
        self._currentlyScheduled, toCancel = [], self._currentlyScheduled[:]
        for sched in toCancel:
            sched.cancel()
        # TODO: better handling of reentrancy here; stop rescheduling if
        # something interrupts us midway. (possible solution: "scheduling
        # generation" counter that gets checked each time?)
        for rescheduled in self.scheduleCallback():
            self._currentlyScheduled.append(rescheduled)

    def observe(self, observable: object, path: str = "") -> None:
        addObserver(observable, self._observer(path))
        self._reschedule()

    def _observer(self, path: str = "") -> Changes[object, object]:
        return _RescheduleObserver(self, path)


@dataclass(frozen=True)
class _RescheduleObserver:
    _rescheduler: Rescheduler
    _path: str = ""

    # Implementation of observer protocol, for watching changes to the list of
    # L{SessionRule} objects in C{self.rules}
    @contextmanager
    def added(self, key: object, new: object) -> Iterator[None]:
        yield
        self._rescheduler._reschedule((self._path, "added", key, new))

    @contextmanager
    def removed(self, key: object, old: object) -> Iterator[None]:
        yield
        self._rescheduler._reschedule((self._path, "removed", key, old))

    @contextmanager
    def changed(self, key: object, old: object, new: object) -> Iterator[None]:
        yield
        self._rescheduler._reschedule((self._path, "changed", key, old, new))

    def child(self, key: object) -> Changes[object, object]:
        return _RescheduleObserver(self._rescheduler, f"{self._path}.{key}")

    # End observer protocol
