import inspect
import types
from functools import wraps

import redis

from kekeke import red

commends = dict()


def command(*, alias: str = None, authonly: bool = False):
    def out(coro: types.coroutine):
        @wraps(coro)
        async def warp(self, *args, **kargs):
            sign = inspect.signature(coro)

            def getParameter(name: str):
                try:
                    keys = sign.parameters.keys()
                    return kargs[name] if name in kargs else args[list(keys).index(name)-1]
                except:
                    return None
            message = getParameter("message")
            if authonly:
                _redis = redis.StrictRedis(connection_pool=red.pool())
                if not _redis.sismember(self.redisPerfix+"auth",message.user.ID) and not _redis.sismember("kekeke::bot::global::auth",message.user.ID) and not message.user.ID==self.bot.user.ID:
                    self._log.warning("命令"+coro.__name__+":不符合執行條件")
                    return None
            self._log.info("命令"+coro.__name__+":開始執行")
            result = await coro(self, *args, **kargs)
            self._log.info("命令"+coro.__name__+":執行完成")
            return result
        w = warp
        func_name = alias if alias else coro.__name__
        commends[func_name] = w
        return w
    return out
