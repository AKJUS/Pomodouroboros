"""
General-purpose PyObjC utilities that might belong in a different package.
"""

from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Generic,
    ParamSpec,
    Protocol,
    TypeVar,
    overload,
)

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSLog,
    NSNotification,
    NSNotificationCenter,
    NSRunningApplication,
    NSWindow,
    NSWindowWillCloseNotification,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
    NSWorkspaceApplicationKey,
    NSWorkspaceDidActivateApplicationNotification,
    NSWorkspaceDidHideApplicationNotification,
)
from Foundation import NSObject
from quickmacapp import Actionable

T = TypeVar("T")
S = TypeVar("S")

ForGetting = TypeVar("ForGetting", covariant=True)
ForSetting = TypeVar("ForSetting", contravariant=True)
SelfType = TypeVar("SelfType", contravariant=True)


class Descriptor(Protocol[ForGetting, ForSetting, SelfType]):
    def __get__(
        self, instance: SelfType, owner: type | None = None
    ) -> ForGetting: ...

    def __set__(self, instance: SelfType, value: ForSetting) -> None: ...


PyType = TypeVar("PyType")
ObjCType = TypeVar("ObjCType")
P = ParamSpec("P")
Attr = Descriptor[T, T, S]


def passthru(value: T) -> T:
    return value


@dataclass
class Forwarder(Generic[SelfType]):
    """
    A builder for descriptors that forward attributes from a (KVO, ObjC) facade
    object to an underlying original (regular Python) object.
    """

    original: str
    "The name of the attribute to forward things to."

    setterWrapper: Callable[
        [Callable[[SelfType, PyType], T]],
        Callable[[SelfType, PyType], T],
    ] = passthru

    @overload
    def forwarded(self, name: str) -> Descriptor[ObjCType, ObjCType, SelfType]:
        """
        Create an attribute that will forward to C{name}.

        @param name: The name of the attribute on C{instance.<original>} to
            forward this attribute to.

        @returns: A descriptor that reads and writes the Objective C type.
        """

    @overload
    def forwarded(
        self,
        name: str,
        pyToC: Callable[[PyType], ObjCType],
        cToPy: Callable[[ObjCType], PyType],
    ) -> Descriptor[ObjCType, ObjCType, SelfType]: ...

    def forwarded(
        self,
        name: str,
        pyToC: Callable[[PyType], ObjCType] | None = None,
        cToPy: Callable[[ObjCType], PyType] | None = None,
    ) -> Descriptor[ObjCType, ObjCType, SelfType]:
        realPyToC: Callable[[PyType], ObjCType] = (
            pyToC if pyToC is not None else passthru  # type:ignore[assignment]
        )
        realCToPy: Callable[[ObjCType], PyType] = (
            cToPy if cToPy is not None else passthru  # type:ignore[assignment]
        )
        return self._forwardedImpl(name, realPyToC, realCToPy)

    def _forwardedImpl(
        self,
        name: str,
        pyToC: Callable[[PyType], ObjCType],
        cToPy: Callable[[ObjCType], PyType],
    ) -> Descriptor[ObjCType, ObjCType, SelfType]:
        prop = objc.object_property()

        @prop.getter
        def getter(oself: SelfType) -> ObjCType:
            wrapped = getattr(oself, self.original)
            return pyToC(getattr(wrapped, name))

        getter.__name__ = f"get {name}"

        @getter.setter
        @self.setterWrapper
        def setter(oself: SelfType, value: ObjCType) -> None:
            wrapped = getattr(oself, self.original)
            setattr(wrapped, name, cToPy(value))

        setter.__name__ = f"set {name}"

        result: Descriptor[ObjCType, ObjCType, SelfType] = prop
        return result


@dataclass
class _ObserverRemover:
    center: NSNotificationCenter | None
    name: str
    observer: NSObject
    sender: NSObject | None

    def removeObserver(self) -> None:
        center = self.center
        if center is None:
            return
        self.center = None
        # lifecycle management: paired with observer.retain() in callOnNotification
        self.observer.release()
        if self.sender is not None:
            # Unused, but lifecycle management would demand sender be retained
            # by any observer-adding code as well.
            self.sender.release()
        center.removeObserver_name_object_(
            self.observer,
            self.name,
        )


class ObserverRemover(Protocol):
    """
    Handle to an observer that is added to a given L{NSNotificationCenter} (by
    L{callOnNotification}).
    """

    def removeObserver(self) -> None:
        """
        Remove the observer added by L{callOnNotification}.
        """


def callOnNotification(
    nsNotificationName: str, f: Callable[[], None]
) -> ObserverRemover:
    """
    When the given notification occurs, call the given callable with no
    arguments.
    """
    defaultCenter = NSNotificationCenter.defaultCenter()
    observer = Actionable.alloc().initWithFunction_(f)
    # lifecycle management: paired with the observer.release() in releaser
    observer.retain()
    sender = None
    defaultCenter.addObserver_selector_name_object_(
        observer,
        "doIt:",
        nsNotificationName,
        sender,
    )
    return _ObserverRemover(
        defaultCenter,
        nsNotificationName,
        observer,
        sender,
    )
