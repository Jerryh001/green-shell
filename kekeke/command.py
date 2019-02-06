import inspect
import types
from functools import wraps

import redis

from kekeke import red

from .message import Message
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
    def allowExec(self: 'Channel', user: User)->bool:
        if user.ID == self.user.ID:
            return True
        _redis = redis.StrictRedis(connection_pool=red.pool())
        if _redis.sismember(self.redisPerfix+"auth", user.ID) or _redis.sismember("kekeke::bot::global::auth", user.ID):
            return True
        elif not authonly and _redis.sismember(self.redisPerfix+"members", user.ID):
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
                    return kargs[name] if name in kargs else args[list(keys).index(name)-1]
                except:
                    return None
            result = None
            message: Message = getParameter("message")
            if allowExec(channnel, message.user):
                channnel._log.info("命令"+func_name+":開始執行")
                result = await coro(channnel, *args, **kargs)
                channnel._log.info("命令"+func_name+":執行完成")
            else:
                channnel._log.warning("命令"+func_name+":不符合執行條件")
            return result

        w = warp
        
        commands[func_name] = Command(w, func_name, help, authonly)
        return w
    return out
