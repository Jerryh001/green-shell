import inspect
import types
from functools import wraps

from .message import Message
from .red import redis
from .user import User

commands = dict()


class Command:
    def __init__(self, coro: types.coroutine, name: str, help: str, authonly: bool):
        self._coro = coro
        self.name = name
        self.help = help
        self.authonly = authonly

    def __call__(self, channnel: 'Channel', *args, **kargs):
        return self._coro(channnel, *args, **kargs)


def command(*, alias: str = None, authonly: bool = False, help: str = ""):
    def allowExec(self: 'Channel', user: User) -> bool:
        if user.ID == self.user.ID:
            return True
        if redis.sismember(f"{self.redisPerfix}auth", user.ID) or redis.sismember("kekeke::bot::global::auth", user.ID):
            return True
        elif not authonly and redis.sismember(f"{self.redisPerfix}members", user.ID):
            return True
        return False

    def out(coro: types.coroutine):

        func_name = alias if alias else coro.__name__

        @wraps(coro)
        async def warp(channnel: 'Channel', *args, **kargs):
            sign = inspect.signature(coro)

            def getParameter(name: str):
                try:
                    keys = sign.parameters.keys()
                    return kargs[name] if name in kargs else args[list(keys).index(name) - 1]
                except Exception:
                    return None

            result = None
            message: Message = getParameter("message")
            if allowExec(channnel, message.user):
                channnel._log.info(f"{message.user}執行了{func_name}")
                result = await coro(channnel, *args, **kargs)
            else:
                channnel._log.warning(f"{message.user}不符合{func_name}的執行條件")
            return result

        w = warp

        commands[func_name] = Command(w, func_name, help, authonly)
        return w

    return out
