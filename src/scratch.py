from contextlib import contextmanager
from typing import Iterator

from pomodouroboros.model.observables import (
    Changes,
    CustomObserver,
    Observer,
    observable,
)


@observable()
class Box:
    observer: CustomObserver[Changes[object, object]]
    contents: int


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


box = Box(ShowChanges(), 1)
box.contents += 1


from pomodouroboros.model.observables import (
    CustomObserver,
    ObservableList,
    PathObserver,
)


@observable()
class Shelf:
    observer: CustomObserver[PathObserver[object]]
    boxes: ObservableList[Box]


def newShelf(observer: Changes[tuple[object, ...], object]) -> Shelf:
    p: PathObserver[object] = PathObserver(observer, (), "")
    return Shelf(p, ObservableList(p.child("boxes")))


shelf = newShelf(ShowChanges())
shelf.boxes.append(box)
box.observer = shelf.observer.child("boxes").child(0)
box.contents += 1
