from .gobj_utils import gSimpleProp
from .platspec import GObject


class SignalMe(GObject.Object):
    alpha = gSimpleProp("alpha", type=int)
    beta = gSimpleProp("beta", type=int)


sm = SignalMe(alpha=1, beta=2)


def n(o: object, p: GObject.ParamSpec) -> None:
    print("set", p.name, "to", getattr(o, p.name))


sm.connect("notify", n)
sm.alpha = 3
sm.beta = 4
