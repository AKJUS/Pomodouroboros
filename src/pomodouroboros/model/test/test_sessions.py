from contextlib import contextmanager
from datetime import datetime, time
from typing import Any, Callable, Iterator
from unittest import TestCase
from zoneinfo import ZoneInfo

from datetype import DateTime, aware, naive
from fritter.boundaries import Scheduler
from fritter.drivers.datetimes import DateTimeDriver
from fritter.drivers.memory import MemoryDriver
from fritter.scheduler import schedulerFromDriver

from pomodouroboros.model.observables import Changes, addObserver, DebugChanges

from ..sessions import SessionManager, DailySessionRule, Session, Weekday

PT = ZoneInfo("US/Pacific")
testingRule = DailySessionRule(
    naive(time(3, 4, 5)),
    naive(time(4, 5, 6)),
    days={Weekday.tuesday, Weekday.wednesday, Weekday.friday},
)


class SessionStartEndSchedulingTests(TestCase):
    def test_observeScheduledSession(self) -> None:
        scheduler: Scheduler[float, Callable[[], None], int] = (
            schedulerFromDriver(memory := MemoryDriver())
        )
        desiredStart = aware(
            datetime(2023, 11, 7, 3, 4, 5, tzinfo=PT), ZoneInfo
        ).timestamp()
        desiredEnd = aware(
            datetime(2023, 11, 7, 4, 5, 6, tzinfo=PT), ZoneInfo
        ).timestamp()
        # start at a reasonable time that is not in the 1970s
        memory.advance(
            aware(datetime(2023, 11, 7, 2, tzinfo=PT), ZoneInfo).timestamp()
            - memory.now()
        )
        sessionChanges = []
        extraneousChanges = []

        class Observe:
            @contextmanager
            def added(self, key: object, new: object) -> Iterator[None]:
                yield
                extraneousChanges.append(("add", key, new))

            @contextmanager
            def removed(self, key: object, old: object) -> Iterator[None]:
                yield
                extraneousChanges.append(("remove", key, old))

            @contextmanager
            def changed(
                self, key: object, old: object, new: object
            ) -> Iterator[None]:
                yield
                sessionChanges.append((key, old, new))

            def child(self, key: object) -> Changes[Any, Any]:
                return self

        asm = SessionManager.new(Observe(), scheduler, PT)
        if 0:
            addObserver(asm, DebugChanges())
        asm.rules.append(testingRule)
        self.assertIs(asm.activeSession, None)
        memory.advance(desiredStart + 10 - memory.now())
        self.assertEqual(
            asm.activeSession,
            Session(start=desiredStart, end=desiredEnd, automatic=True),
        )
        memory.advance(desiredEnd + 15 - memory.now())
        self.assertEqual(asm.activeSession, None)
        expectedSession = Session(
            start=desiredStart, end=desiredEnd, automatic=True
        )
        self.assertEqual(
            sessionChanges,
            [
                ("activeSession", None, expectedSession),
                ("activeSession", expectedSession, None),
            ],
        )
        expectedRule = DailySessionRule(
            dailyStart=naive(time(3, 4, 5)),
            dailyEnd=naive(time(4, 5, 6)),
            days={Weekday.tuesday, Weekday.wednesday, Weekday.friday},
        )
        self.assertIn(
            (
                "add",
                "rules",
                [expectedRule],
            ),
            extraneousChanges,
        )
