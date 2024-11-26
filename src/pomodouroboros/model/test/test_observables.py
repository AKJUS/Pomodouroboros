from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Callable, Iterator, Protocol, Sequence, TypeVar

from twisted.trial.unittest import SynchronousTestCase as TC

from pomodouroboros.model.observables import CustomObserver

from ..observables import (
    Changes,
    DebugChanges,
    IgnoreChanges,
    MirrorMapping,
    MirrorSequence,
    MirrorObject,
    MustSpecifyObserver,
    ObservableDict,
    ObservableList,
    Observer,
    PathObserver,
    build,
    observable,
)


class TestObservables(TC):
    """
    tests for observables
    """

    def test_observerErrorMessage(self) -> None:
        """
        If we make an L{observable} class without providing a L{Observer}
        annotation, we get a nice error message telling us that it's invalid.
        """
        with self.assertRaises(MustSpecifyObserver) as msn:

            @observable()
            class Oops:
                name: str
                age: int

        self.assertIn(
            "you must annotate one attribute with Observer",
            str(msn.exception),
        )

    def test_buildAndObserve(self) -> None:
        """
        simple cases
        """
        example, cr = build(
            lambda observer: Example.new(
                observer=observer, name="John", age=30
            ),
            lambda mycls: ChangeRecorder(mycls),
            # strong=True,
        )
        self.assertEqual(cr.changes, [])  # type:ignore[attr-defined]
        example.value1 = "x"
        example.value2 = 3
        example.valueList.append("hello")
        example.valueList.append("goodbye")
        example.valueList[1] = "goodbye!"
        del example.valueList[1]
        self.assertEqual(
            [
                ("will change", ("value1",), "John", "John", "x"),
                ("did change", ("value1",), "x", "John", "x"),
                ("will change", ("value2",), 30, 30, 3),
                ("did change", ("value2",), 3, 30, 3),
                ("will add", ("list", 0), "not found"),
                ("did add", ("list", 0), "not found"),
                ("will add", ("list", 1), "not found"),
                ("did add", ("list", 1), "not found"),
                (
                    "will change",
                    ("list", 1),
                    "not found before",
                    "goodbye",
                    "goodbye!",
                ),
                (
                    "did change",
                    ("list", 1),
                    "not found after",
                    "goodbye",
                    "goodbye!",
                ),
                ("will remove", ("list", 1), "not found", "goodbye!"),
                ("did remove", ("list", 1), "not found", "goodbye!"),
            ],
            cr.changes,  # type:ignore[attr-defined]
        )

    def test_debug(self) -> None:
        """
        L{DebugChanges} will write some text to allow you to easily inspect
        changes being delivered.
        """
        io = StringIO()
        example, debug = build(
            lambda observer: Example.new(
                observer=observer, name="John", age=30
            ),
            lambda mycls: DebugChanges(ChangeRecorder(mycls), io),
            # strong=True,
        )

        # can't express a bound that DebugChanges[K, V].original is a TypeVar
        # with its own type but also bounded by Changes[K, V]
        # https://github.com/python/typing/issues/548
        cr: ChangeRecorder = debug.original  # type:ignore[attr-defined]

        example.value1 = "new value"
        del example.value1
        example.valueList.append("new list value")
        example.secretInternalChange()
        self.maxDiff = 9999
        expectedDebugOutput = "\n".join(
            [
                "will change ('value1',) from 'John' to 'new value'",
                "did change ('value1',) from 'John' to 'new value'",
                "will remove ('value1',) 'new value'",
                "did remove ('value1',) 'new value'",
                "will add ('list', 0) 'new list value'",
                "did add ('list', 0) 'new list value'",
                "",
            ]
        )
        expectedChanges = [
            ("will add", "value1", "John"),
            ("did add", "value1", "new value"),
            ("will remove", "value1", "new value", "new value"),
            ("did remove", "value1", "not found", "new value"),
            ("will add", ("list", 0), "not found"),
            ("did add", ("list", 0), "not found"),
        ]
        self.assertEqual(cr.changes, expectedChanges)
        self.assertEqual(io.getvalue(), expectedDebugOutput)

    def test_mirrorList(self) -> None:
        """
        A L{MirrorList} can update from one list to another.
        """
        a: list[str] = []
        b: list[str] = []

        o = ObservableList(MirrorList(b), a)
        o.append("1")
        self.assertEqual(a, b)
        o.insert(0, "2")
        self.assertEqual(a, b)
        o.extend(str(each) for each in range(10))
        self.assertEqual(a, b)
        del o[3:7]
        self.assertEqual(a, b)

    def test_mirrorDict(self) -> None:
        """
        A L{MirrorMapping} can update from one dictionary to another.
        """
        a: dict[str, float] = {}
        b: dict[str, float] = {}
        o = ObservableDict(MirrorMapping(b), a)
        o["hello"] = 1
        self.assertEqual(a, b)
        o["goodbye"] = 2
        self.assertEqual(a, b)
        o["goodbye"] = 2
        self.assertEqual(a, b)
        o.pop("hello")
        self.assertEqual(a, b)

    def test_mirrorObject(self) -> None:
        nameMapping = {"r": "red", "g": "green", "b": "blue"}
        b = VerboseColor("fullred", 1, 0, 0)
        a = TerseColor(MirrorObject(b, nameMapping), "fullred", 1, 0, 0)

        def check() -> None:
            self.assertEqual(a.tuplify(), b.tuplify())

        check()
        a.name = "fullblue"
        check()
        a.r = 0
        check()
        # check __delete__ for completeness even though this leaves the object
        # invalid
        del a.b
        check()
        a.b = 1
        check()

    def test_hasDefault(self) -> None:
        self.assertEqual(
            HasDefault(IgnoreChanges, "hi"),
            HasDefault(IgnoreChanges, "hi", three=[6]),
        )

    def test_hasDefaultObserver(self) -> None:
        hdo1 = HasDefaultObserver(1)
        hdo2 = HasDefaultObserver(1)
        self.assertEqual(hdo1, hdo2)
        cr = ChangeRecorder(hdo1)
        hdo1.observer = cr
        hdo1.value = 2
        self.assertEqual(
            cr.changes,
            [
                ("will change", "value", 1, 1, 2),
                ("did change", "value", 2, 1, 2),
            ],
        )


@observable()
class TerseColor:
    observer: Observer
    name: str
    r: float
    g: float
    b: float

    def tuplify(self) -> tuple[str, float, float, float | None]:
        return (self.name, self.r, self.g, getattr(self, "b", None))


@dataclass
class VerboseColor:
    name: str
    red: float
    green: float
    blue: float

    def tuplify(self) -> tuple[str, float, float, float | None]:
        return (self.name, self.red, self.green, getattr(self, "blue", None))


class MaybeStr(Protocol):
    def __call__(self, nf: str = "not found") -> object: ...


def getfunc(
    key: tuple[object, ...] | str, o: object
) -> tuple[object, MaybeStr]:

    get: MaybeStr
    match key:
        case str(attrkey):
            rekey: object = attrkey

            def get(nf: str = "not found") -> object:
                return getattr(o, attrkey, nf)

        case (str(attrkey),):
            rekey = attrkey

            def get(nf: str = "not found") -> object:
                return getattr(o, attrkey, nf)

        case _:
            rekey = key

            def get(nf: str = "not found") -> object:
                return nf

    return rekey, get


@dataclass(repr=False)
class ChangeRecorder:
    example: object
    changes: list[Any] = field(default_factory=list)

    def __repr__(self) -> str:
        return "~"

    @contextmanager
    def added(
        self, key: tuple[object, ...] | str, new: object
    ) -> Iterator[None]:
        """
        C{value} was added for the given C{key}.
        """
        rekey, get = getfunc(key, self.example)
        self.changes.append(("will add", rekey, get()))
        yield
        self.changes.append(("did add", rekey, get()))

    @contextmanager
    def removed(
        self, key: tuple[object, ...], old: tuple[Any, ...]
    ) -> Iterator[None]:
        """
        C{key} was removed for the given C{key}.
        """
        rekey, get = getfunc(key, self.example)
        self.changes.append(("will remove", rekey, get(), old))
        yield
        self.changes.append(("did remove", rekey, get(), old))

    @contextmanager
    def changed(
        self, key: tuple[object, ...], old: object, new: object
    ) -> Iterator[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        rekey, get = getfunc(key, self.example)
        oldval = get("not found before")
        self.changes.append(("will change", key, oldval, old, new))
        yield
        self.changes.append(
            ("did change", key, get("not found after"), old, new)
        )


@observable()
class Example:
    observer: CustomObserver[Changes[str, object]]
    value1: str
    value2: int
    valueList: ObservableList[str]
    _internalValue: float = 0.0

    def secretInternalChange(self) -> None:
        """
        Change an attribute that should not be observable.
        """
        self._internalValue += 1

    @classmethod
    def new(
        cls, observer: Changes[tuple[Any, ...], object], name: str, age: int
    ) -> Example:
        p: PathObserver[object] = PathObserver(observer, (), "")
        return cls(p, name, age, valueList=ObservableList(p.child("list"), []))


@observable()
class HasDefault:
    observer: Observer
    one: str
    two: int = 5
    three: list = field(default_factory=lambda: [6])


@observable()
class HasDefaultObserver:
    value: int
    observer: Observer = field(default_factory=IgnoreChanges)
