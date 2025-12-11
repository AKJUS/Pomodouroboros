# -*- test-case-name: pomodouroboros.model.test.test_observables -*-

"""
Create observable mutable objects, for interactive user interfaces to present
changes in real time.

This is a Python native way to achieve something similar to
U{NSKeyValueObserving
<https://developer.apple.com/documentation/objectivec/nsobject/nskeyvalueobserving?language=objc#>};
in addition to being a generally nice way to reflect changes, in the mac UI for
Pomodouroboros, we need to mirror changes into PyObjC model classes for the UI
to observe.

However, unlike Objective C, python does not allow for monkeypatching the
internals of C{object}, nor does it provide a native attribute-change
observation feature in the language itself, so all these classes must be
opt-in.

To declare a class whose changes may be observable, use the L{observable}
decorator.  This creates a dataclass, like so::

    from pomodouroboros.model.observables import observable, Observer

    @observable()
    class Box:
        observer: Observer
        contents: int

Then, to observe the changes, construct your newly-created dataclass with an
object that conforms to the Observer protocol.  Observers have 3 methods:
added, removed, and changed; each of these methods returns a contextmanager,
which will be entered before the change, then exited after the change.  To
implement one, the L{contextlib.contextmanager} decorator is helpful::

    from contextlib import contextmanager
    from typing import Iterator

    class ShowChanges:
        @contextmanager
        def added(self, key: object, new: object) -> Iterator[None]:
            print(f"will add {key} as {new}")
            yield
            print(f"did add {key} as {new}")

        @contextmanager
        def removed(self, key: object, old: object) -> Iterator[None]:
            print(f"will remove {key} (was {old})")
            yield
            print(f"did remove {key} (was {old})")

        @contextmanager
        def changed(self, key: object, old: object, new: object) -> Iterator[None]:
            print(f"will change {key} from {old} to {new}")
            yield
            print(f"did change {key} from {old} to {new}")

Put them together by constructing them::

    box = Box(ShowChanges(), 1)

And then observe the change::

    box.contents += 1

Which should print::

    will add contents as 1
    did add contents as 1
    will change contents from 1 to 2
    did change contents from 1 to 2

This works for the attributes on a single object; however, often you will want
to observe hierarchies of objects, with other mutable containers within it,
such as lists and dictionaries.  To do this, you can construct a parallel
hierarchy of observables with a L{PathObserver}.  Let's put our box on a shelf,
with some other boxes::

    from pomodouroboros.model.observables import PathObserver, CustomObserver, ObservableList

    @observable()
    class Shelf:
        observer: CustomObserver[PathObserver[object, object]]
        boxes: ObservableList[Box]

    def newShelf(observer: Observer) -> Shelf:
        p = PathObserver(observer, "")
        return Shelf(p, ObservableList(p.child("boxes")))

    shelf = newShelf(ShowChanges())
    shelf.boxes.append(box)

You can then see the box being added::

    will add boxes.0 as Box(observer=<__main__.ShowChanges object at 0x10337e630>, contents=2)
    did add boxes.0 as Box(observer=<__main__.ShowChanges object at 0x10337e630>, contents=2)

Note, however, that if you want your observers to see changes to boxes, you
must also change your box's observer::

    box.observer = shelf.observer.child("boxes").child("0")

and now those changes will show up to the path observer::

    box.contents += 1

which will show up as::

    will change boxes.0.contents from 2 to 3
    did change boxes.0.contents from 2 to 3
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import partial, total_ordering
from typing import (
    IO,
    Annotated,
    Any,
    Callable,
    ClassVar,
    ContextManager,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    Protocol,
    Sequence,
    TypeVar,
    dataclass_transform,
    overload,
)
from weakref import proxy

K = TypeVar("K")
V = TypeVar("V")


Kcon = TypeVar("Kcon", contravariant=True)
Vcon = TypeVar("Vcon", contravariant=True)
Scon = TypeVar("Scon", contravariant=True)


class Changes(Protocol[Kcon, Vcon]):
    """
    Methods to observe changes.

    Each method is a context manager; the change will be performed in the body
    of the context manager.

    This is used for mutable mappings, sequences, and objects.

        1. When observing a mapping, C{Kcon} and C{Vcon} are defined by the
           mapping's key and value types.

        2. When observing an object, C{Kcon} is L{str} and C{Vcon} is
           C{object}; you must know the type of the attribute being changed.

        3. When observing a sequence, C{Kcon} is C{int | slice} and C{Vcon} is
           the type of the sequence contents.
    """

    def added(self, key: Kcon, new: Vcon) -> ContextManager[None]:
        """
        C{value} was added for the given C{key}.
        """

    def removed(self, key: Kcon, old: Vcon) -> ContextManager[None]:
        """
        C{key} was removed for the given C{key}.
        """

    def changed(self, key: Kcon, old: Vcon, new: Vcon) -> ContextManager[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """

    def child(self, key: Kcon) -> Changes[Any, Any]:
        """
        Provide a L{Changes} for observing changes to the sub-object at C{key}.

        @note: the type signature here is loose because the structure of C{key}
            will often imply a specific type; for example, if you have an
            attribute C{values: }L{ObservableList}C{[float]}, then
            C{observer.child("values")} ought to be able to return a
            C{Changes[int,float]} without complaint from the type system.
        """


@contextmanager
def noop() -> Iterator[None]:
    yield


@dataclass
class IgnoreChanges:
    @classmethod
    def added(cls, key: object, new: object) -> ContextManager[None]:
        return noop()

    @classmethod
    def removed(cls, key: object, old: object) -> ContextManager[None]:
        return noop()

    @classmethod
    def changed(
        cls, key: object, old: object, new: object
    ) -> ContextManager[None]:
        return noop()

    @classmethod
    def child(cls, key: object) -> Changes[Any, Any]:
        return cls


_IgnoreChangesImplements: type[Changes[object, object]] = IgnoreChanges
_IgnoreChangesImplementsClass: Changes[object, object] = IgnoreChanges


@dataclass
class DebugChanges(Generic[Kcon, Vcon]):
    original: Changes[Kcon, Vcon] = IgnoreChanges
    stream: IO[str] = field(default_factory=lambda: sys.stderr)
    prefix: Sequence[object] = ()

    @contextmanager
    def added(self, key: Kcon, new: Vcon) -> Iterator[None]:
        self.stream.write(f"will add {key!r} {new!r}\n")
        with self.original.added(key, new):
            yield
        self.stream.write(f"did add {key!r} {new!r}\n")

    @contextmanager
    def removed(self, key: Kcon, old: Vcon) -> Iterator[None]:
        self.stream.write(f"will remove {key!r} {old!r}\n")
        with self.original.removed(key, old):
            yield
        self.stream.write(f"did remove {key!r} {old!r}\n")

    @contextmanager
    def changed(self, key: Kcon, old: Vcon, new: Vcon) -> Iterator[None]:
        self.stream.write(f"will change {key!r} from {old!r} to {new!r}\n")
        with self.original.added(key, new):
            yield
        self.stream.write(f"did change {key!r} from {old!r} to {new!r}\n")

    def child(self, key: Kcon) -> Changes[Any, Any]:
        return DebugChanges(
            self.original.child(key),
            self.stream,
            prefix=[*self.prefix, key],
        )


_DebugChangesImplements: type[Changes[object, object]] = DebugChanges

_ObjectObserverBound = Changes[str, object]
_O = TypeVar("_O", bound=_ObjectObserverBound)


class ObserverAnnotation(Enum):
    """
    An L{ObserverAnnotation} is a value that can be used in an L{Annotated}
    attribute to indicate the role of that attribute.  Currently, its one value
    is L{ObserverAnnotation.attribute}, which simply means "this attribute is
    the observer for this class, and all changes will be sent to it via the
    L{Changes} protocol."
    """

    attribute = auto()
    "Annotation value indicating that this attribute is the observer attribute."


ObserverAttribute = Annotated[_O, ObserverAnnotation.attribute]
_AnnotatedType = type(ObserverAttribute)
Observer = ObserverAttribute[_ObjectObserverBound]

SequenceObserver = Changes[int | slice, V | Iterable[V]]


@dataclass(eq=False, order=False)
class ObservableDict(MutableMapping[K, V]):
    observer: Changes[K, V]
    _storage: MutableMapping[K, V] = field(default_factory=dict)
    __observable_observer__: ClassVar[str] = "observer"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ObservableDict):
            return dict(self._storage) == dict(other._storage)
        elif isinstance(other, dict):
            return dict(self._storage) == dict(other)
        else:
            return NotImplemented

    # unchanged proxied read operations
    def __getitem__(self, key: K) -> V:
        return self._storage.__getitem__(key)

    def __iter__(self) -> Iterator[K]:
        return self._storage.__iter__()

    def __len__(self) -> int:
        return self._storage.__len__()

    # notifying write operations
    def __setitem__(self, key: K, value: V) -> None:
        with (
            self.observer.changed(key, self._storage[key], value)
            if key in self._storage
            else self.observer.added(key, value)
        ):
            return self._storage.__setitem__(key, value)

    def __delitem__(self, key: K) -> None:
        with self.observer.removed(key, self._storage[key]):
            return self._storage.__delitem__(key)


@total_ordering
@dataclass(repr=False, eq=False, order=False)
class ObservableList(MutableSequence[V]):
    observer: SequenceObserver[V]
    _storage: MutableSequence[V] = field(default_factory=list)
    __observable_observer__: ClassVar[str] = "observer"

    def __lt__(self, other: object) -> bool:
        if isinstance(other, ObservableList):
            return list(self._storage) < list(other._storage)
        elif isinstance(other, list):
            return list(self._storage) < list(other)
        else:
            return NotImplemented

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ObservableList):
            return list(self._storage) == list(other._storage)
        elif isinstance(other, list):
            return list(self._storage) == list(other)
        else:
            return NotImplemented

    def __repr__(self) -> str:
        return repr(self._storage) + "~(observable)"

    @overload
    def __setitem__(self, index: int, value: V) -> None: ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[V]) -> None: ...

    def __setitem__(self, index: int | slice, value: V | Iterable[V]) -> None:
        with (
            self.observer.changed(index, self._storage[index], value)
            if (
                isinstance(index, int)
                and (0 <= index < len(self._storage))
                or isinstance(index, slice)
            )
            else self.observer.added(index, value)
        ):
            # the overloads above ensure the proper type dependence between
            # 'index' and 'slice' (slice index means Iterable[V], int index
            # means V), but we can't express the dependent relationship to
            # mypy, so we ignore the resulting errors as narrowly as possible.

            self._storage.__setitem__(
                index,  # type:ignore[index]
                value,  # type:ignore[assignment]
            )

    def __delitem__(self, index: int | slice) -> None:
        with self.observer.removed(index, self._storage[index]):
            self._storage.__delitem__(index)

    def insert(self, index: int, value: V) -> None:
        """
        a value was inserted
        """
        with self.observer.added(index, value):
            self._storage.insert(index, value)

    # proxied read operations
    @overload
    def __getitem__(self, index: int) -> V: ...

    @overload
    def __getitem__(self, index: slice) -> MutableSequence[V]: ...

    def __getitem__(self, index: slice | int) -> V | MutableSequence[V]:
        return self._storage.__getitem__(index)

    def __iter__(self) -> Iterator[V]:
        return self._storage.__iter__()

    def __len__(self) -> int:
        return self._storage.__len__()


@dataclass
class MirrorMapping(Generic[K, V]):
    """
    A L{MirrorMapping} is a L{Changes} observer, which, when observing a
    L{ObservableDict}, can propagate all changes from that dictionary into
    another mutable mapping.

    This can be useful for:

        - maintaining a plain dictionary for communication with other libraries
          that need a copy of the state of an observable mapping for purposes
          like serialization

        - propagating changes from observable objects in this library to other
          systems with their own observer pattern implementations, such as
          mirroring into an NSMutableDictionary wrapped by PyObjC in order to
          participate in KVO.
    """

    mirror: MutableMapping[K, V]

    @contextmanager
    def added(self, key: K, new: V) -> Iterator[None]:
        yield
        self.mirror[key] = new

    @contextmanager
    def removed(self, key: K, old: V) -> Iterator[None]:
        yield
        del self.mirror[key]

    @contextmanager
    def changed(self, key: K, old: V, new: V) -> Iterator[None]:
        yield
        self.mirror[key] = new

    def child(self, key: K) -> Changes[Any, Any]:
        # TODO: clients should be able to pass a function that provides a
        # sub-observer type for objects of type V (assuming that V is itself
        # observable), so that when we get a change notification for a
        # particular (attribute,index) of a particular key, we relay that
        # change down through our mirrored dictionary
        return IgnoreChanges


_MirrorMappingImplements: type[Changes[str, float]] = MirrorMapping[str, float]


@dataclass
class MirrorSequence(Generic[V]):
    """
    A L{MirrorSequence} is a L{Changes} observer, which, when observing a
    L{ObservableList}, can propagate all changes from that list into another
    mutable sequence.

    This can be useful for:

        - maintaining a plain list for communication with other libraries that
          need a copy of the state of an observable list for purposes like
          serialization

        - propagating changes from observable objects in this library to other
          systems with their own observer pattern implementations, such as
          mirroring into an NSMutableArray wrapped by PyObjC in order to
          participate in KVO.
    """

    mirror: MutableSequence[V]

    @contextmanager
    def added(self, key: int | slice, new: V | Iterable[V]) -> Iterator[None]:
        yield
        if isinstance(key, int):
            key = slice(key, key)
            new = [new]  # type:ignore
        self.mirror[key] = new  # type:ignore

    @contextmanager
    def removed(
        self, key: int | slice, old: V | Iterable[V]
    ) -> Iterator[None]:
        yield
        del self.mirror[key]

    @contextmanager
    def changed(
        self, key: int | slice, old: V | Iterable[V], new: V | Iterable[V]
    ) -> Iterator[None]:
        yield
        self.mirror[key] = new  # type:ignore

    def child(self, key: int | slice) -> Changes[Any, Any]:
        # TODO: clients should be able to pass a function that provides a
        # sub-observer type for objects of type V (assuming that V is itself
        # observable), so that when we get a change notification for a
        # particular (attribute,index) of a particular key, we relay that
        # change down through our mirrored dictionary

        # TODO: upon insertion and removal, the indexes of the sub-observer
        # need to be able to change somehow.
        return IgnoreChanges


_MirrorSequenceImplements: type[SequenceObserver[str]] = MirrorSequence[str]


@dataclass
class MirrorObject:
    """
    A L{MirrorObject} is a L{Changes} observer, which, when observing any
    instance of an @L{observable} class, can propagate all attribute changes
    from the observed object into another object.

    This can be useful for:

        - propagating changes from observable objects in this library to other
          systems with their own observer pattern implementations, such as
          mirroring into any NSObject with its attributes declared as
          L{objc.object_property} wrapped by PyObjC in order to participate in
          KVO.

        - wrapping a mutable object from a library for debugging purposes, to
          observe changes that are made to it via any code the mirror is passed
          to.
    """

    mirror: object
    nameTranslation: Mapping[str, str]

    @contextmanager
    def added(self, key: str, new: object) -> Iterator[None]:
        yield
        setattr(self.mirror, self.nameTranslation.get(key, key), new)

    @contextmanager
    def removed(self, key: str, old: object) -> Iterator[None]:
        yield
        delattr(self.mirror, self.nameTranslation.get(key, key))

    @contextmanager
    def changed(self, key: str, old: object, new: object) -> Iterator[None]:
        yield
        setattr(self.mirror, self.nameTranslation.get(key, key), new)

    def child(self, key: str) -> Changes[Any, Any]:
        # TODO: should not actually ignore changes on sub-objects
        return IgnoreChanges


_MirrorObjectImplements: type[Changes[str, object]] = MirrorObject


@dataclass
class _ObservableProperty:
    """
    An L{_ObservableProperty} is the descriptor placed into a class dictionary
    by the L{observable} decorator.  This is not visible at type-time, only at
    runtime, to catch attriubte get/set/delete calls and relay them to
    observers.
    """

    observer_name: str
    field_name: str

    def __get__(self, instance: object, owner: object) -> object:
        if self.field_name not in instance.__dict__:
            raise AttributeError(f"couldn't find {self.field_name!r}")
        return instance.__dict__[self.field_name]

    def __set__(self, instance: object, value: object) -> None:
        notify: Changes[str, object] = getattr(instance, self.observer_name)

        # I need to avoid invoking the observer if the instance isn't fully
        # initialized
        with (
            notify.changed(
                self.field_name, instance.__dict__[self.field_name], value
            )
            if self.field_name in instance.__dict__
            else notify.added(self.field_name, value)
        ):
            observerSetter = _canSetObserver(value)
            instance.__dict__[self.field_name] = value
            if observerSetter is not None:
                c = notify.child(self.field_name)
                observerSetter(c)

    def __delete__(self, instance: object) -> None:
        if self.field_name not in instance.__dict__:
            raise AttributeError(f"couldn't find {self.field_name!r}")
        notify: Changes[str, object] = getattr(instance, self.observer_name)
        with notify.removed(
            self.field_name, instance.__dict__[self.field_name]
        ):
            del instance.__dict__[self.field_name]


def _unstringify(cls: type, annotation: object) -> object:
    """
    Evaluate the given C{annotatation}, if it is a string, given the namespace
    of the type object where it is declared.

    This is very much like L{inspect.get_annotations}C{(..., eval_str=True)},
    but respecting the class dictionary namespace.
    """
    if not isinstance(annotation, str):
        return annotation
    try:
        mod = sys.modules[cls.__module__]
        clslocals = dict(vars(cls))
        return eval(annotation, mod.__dict__, clslocals)
    except:
        return None


def _isObserver(annotation: object) -> bool:
    """
    Does this C{annotation} carry the L{ObserverAnnotation} annotation,
    indicating that the attribute this annotates is the observer which should
    be skipped for the purposes of notifying about changes?
    """
    if isinstance(annotation, _AnnotatedType):
        # does the standard lib have no nicer way to ask 'is this `Annotated`'?
        for element in annotation.__metadata__:
            if element is ObserverAnnotation.attribute:
                return True
    return False


Ty = TypeVar("Ty", bound=type)


class MustSpecifyObserver(Exception):
    """
    You must annotate exactly one attribute with Observer when declaring a
    class to be L{observable}.
    """


def _shouldBeObservable(
    key: str, annotation: object, observerName: str
) -> bool:
    """
    Should the attribute with the given name and annotation emit messages to
    the observer, for an L{observable} class with an observer named
    C{observerName}.
    """
    return (
        key
        != observerName  # the observer should not be able to observe the
        # observer changing
    ) and (
        not key.startswith(
            "_"
        )  # TODO: test for private attribute observability
    )


_observabilityHint = "__observable_observer__"


def _canSetObserver(
    maybeObservable: object,
) -> Callable[[Changes[Any, Any]], None] | None:
    """
    Determine if the given C{maybeObservable} is an C{@}L{observable} object;
    if it is, return a function that can set its observer (which takes a
    L{Changes} and returns C{None}).  If it is not observable, return C{None}.
    """
    observerName = getattr(maybeObservable, _observabilityHint, None)
    if observerName is None:
        return None

    def _setObserver(anObserver: Changes[Any, Any]) -> None:
        setattr(maybeObservable, observerName, anObserver)

    return _setObserver


@dataclass_transform(field_specifiers=(field,))
def observable(repr: bool = True) -> Callable[[Ty], Ty]:
    """
    Decorate a dataclass to indicate that it may be observed by its observer
    attribute.  This is a dataclass transform that uses the standard library
    L{dataclass} type, and thus the standard library L{field} function for
    field metadata.

    Indicate which attribute represents the observer by using the
    L{ObserverAttribute} annotation.
    """

    def make_observable(cls: Ty) -> Ty:
        observerName = None
        originalAnnotations = cls.__annotations__

        cls = dataclass(repr=repr)(cls)  # type:ignore[assignment]
        for i, (k, v) in enumerate(originalAnnotations.items()):
            if _isObserver(_unstringify(cls, v)):
                observerIndex = i
                observerName = k
                break

        if observerName is None:
            raise MustSpecifyObserver(
                "you must annotate one attribute with Observer"
            )

        setattr(cls, _observabilityHint, observerName)
        for k, v in originalAnnotations.items():
            if _shouldBeObservable(k, v, observerName):
                setattr(cls, k, _ObservableProperty(observerName, k))
        if observerIndex != 0:
            # If the observer is not specified as the first argument, then the
            # dataclass-generated __init__ is going to assign other attributes
            # first, and therefore we cannot observe them.  So here we provide
            # a class-level default that will allow the attribute to be
            # retrieved by ObservableProperty.__set__/.__delete__.
            setattr(cls, observerName, IgnoreChanges)
        return cls

    return make_observable


@dataclass
class DispatchingObserver(Generic[Kcon, Vcon]):
    _adders: dict[
        Kcon, tuple[list[Callable[[Vcon], None]], list[Callable[[Vcon], None]]]
    ]
    _removers: dict[
        Kcon, tuple[list[Callable[[Vcon], None]], list[Callable[[Vcon], None]]]
    ]
    _changers: dict[
        Kcon,
        tuple[
            list[Callable[[Vcon, Vcon], None]],
            list[Callable[[Vcon, Vcon], None]],
        ],
    ]

    def beforeAdd(self, key: Kcon) -> None:
        pass

    def afterAdd(self, key: Kcon) -> None:
        pass

    def beforeRemove(self, key: Kcon) -> None:
        pass

    def afterRemove(self, key: Kcon) -> None:
        pass

    def beforeChange(self, key: Kcon) -> None:
        pass

    def afterChange(self, key: Kcon) -> None:
        pass

    @contextmanager
    def added(self, key: Kcon, new: Vcon) -> Iterator[None]:
        before, after = self._adders.get(key, ([], []))
        for each in before:
            each(new)
        yield
        for each in after:
            each(new)

    @contextmanager
    def removed(self, key: Kcon, old: Vcon) -> Iterator[None]:
        before, after = self._removers.get(key, ([], []))
        for each in before:
            each(old)
        yield
        for each in after:
            each(old)

    @contextmanager
    def changed(self, key: Kcon, old: Vcon, new: Vcon) -> Iterator[None]:
        before, after = self._changers.get(key, ([], []))
        for each in before:
            each(old, new)
        yield
        for each in after:
            each(old, new)


@dataclass(repr=False)
class PathObserver(Generic[Vcon]):
    """
    A L{PathObserver} implements L{Changes} for any key / value type and
    translates the key type to a string that represents a path.  You can add
    elements to the path.

    For example, if you have two observables like so, one containing the other,
    and you want to keep track of which thing was changed::

        @observable()
        class B:
            bValue: str
            observer: Observer = IgnoreChanges


        @observable()
        class A:
            b: B
            aValue: str
            observer: Observer = IgnoreChanges

    You can then arrange observers like so::

        root = DebugChanges()
        path = PathObserver(root, "a")

        a = A(B("b"), "a")
        a.observer = path
        a.b.observer = path.child("b")
        a.aValue = "x"
        a.b.bValue = "y"

    and you will see that the changes are reflected with keys of 'a.aValue' and
    'a.b.bValue' respectively.
    """

    wrapped: Changes[tuple[object, ...], Vcon]
    keyPrefix: tuple[object, ...]
    displayPrefix: str = ""
    convert: Callable[[tuple[object, ...]], str] = str
    sep: str = "."

    def __repr__(self) -> str:
        return f"{self.wrapped}/({self.displayPrefix})"

    def _keyPath(self, segment: K) -> str:
        segstr = str(segment)
        return (
            self.sep.join([self.displayPrefix, segstr])
            if self.displayPrefix
            else segstr
        )

    def _key(self, segment: K) -> tuple[object, ...]:
        return (*self.keyPrefix, segment)

    def child(self, segment: K) -> PathObserver[Vcon]:
        """
        create child path observer
        """
        return PathObserver(
            self.wrapped,
            self._key(segment),
            self._keyPath(segment),
            self.convert,
            self.sep,
        )

    @contextmanager
    def added(self, key: K, new: Vcon) -> Iterator[None]:
        """
        C{value} was added for the given C{key}.
        """
        with self.wrapped.added(self._key(key), new):
            yield

    @contextmanager
    def removed(self, key: K, old: Vcon) -> Iterator[None]:
        """
        C{key} was removed for the given C{key}.
        """
        with self.wrapped.removed(self._key(key), old):
            yield

    @contextmanager
    def changed(self, key: K, old: Vcon, new: Vcon) -> Iterator[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        with self.wrapped.changed(self._key(key), old, new):
            yield


@dataclass(repr=False)
class AfterInitObserver:
    """
    Interposer that handles attribute-added notifications during object
    initialization.
    """

    _original: Changes[object, object] | None = None
    _childs: list[tuple[object, AfterInitObserver]] = field(
        default_factory=list
    )

    def __repr__(self) -> str:
        return repr(self._original) + "(after init)"

    def added(self, key: object, new: object) -> ContextManager[None]:
        """
        C{value} was added for the given C{key}.
        """
        original = self._original
        if original is not None:
            return original.added(key, new)
        else:
            return noop()

    def removed(self, key: object, old: object) -> ContextManager[None]:
        """
        C{key} was removed for the given C{key}.
        """
        original = self._original
        if original is not None:
            return original.removed(key, old)
        else:
            return noop()

    def changed(
        self, key: object, old: object, new: object
    ) -> ContextManager[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        original = self._original
        if original is not None:
            return original.changed(key, old, new)
        else:
            return noop()

    def finalize(self, ref: object) -> None:
        """
        The observed object has been garbage collected; let the observer go.
        """
        self._original = None

    def child(self, key: object) -> Changes[Any, Any]:
        if self._original is not None:
            return self._original.child(key)
        else:
            # TODO: do we need to do something here when _original is set?
            self._childs.append((key, aoi := AfterInitObserver()))
            return aoi

    def _setOriginal(self, newOriginal: Changes[object, object]) -> None:
        self._original = newOriginal
        for k, child in self._childs:
            child._setOriginal(newOriginal.child(k))
            # TODO: clean up


_AfterInitObserver: type[Changes[object, object]] = AfterInitObserver

CN = TypeVar("CN", bound=Changes[Any, Any])


def build(
    observed: Callable[[Changes[object, object]], V],
    observer: Callable[[V], CN],
    *,
    strong: bool = False,
) -> tuple[V, CN]:
    """
    Build an observer that requires being told about the object it's observing.

    @param strong: By default, to avoid circular references and the attendant
        load on the cyclic GC, we will give C{observer} a weakref proxy object
        to the result of C{builder} rather than a direct reference.  For
        esoteric use-cases, however, a strong reference may be required, so
        passing C{strong=True} will omit the proxy.
    """
    interpose: AfterInitObserver = AfterInitObserver()
    observable: V = observed(interpose)
    o = observer(
        observable if strong else proxy(observable, interpose.finalize)
    )
    interpose._setOriginal(o)
    return observable, o
