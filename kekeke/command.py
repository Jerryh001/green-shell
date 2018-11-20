import inspect
import types
from functools import wraps

import redis
from .message import Message
from .user import User
from kekeke import red

commends = dict()


def command(*, alias: str = None, authonly: bool = False):
    def allowExec(self:'Channel',user:User)->bool:
        if user.ID==self.user.ID:
            return True
        _redis = redis.StrictRedis(connection_pool=red.pool())
        if _redis.sismember(self.redisPerfix+"auth",user.ID) or _redis.sismember("kekeke::bot::global::auth",user.ID):
            return True
        elif not authonly and _redis.sismember(self.redisPerfix+"members",user.ID):
            return True
        return False
    def out(coro: types.coroutine):
        @wraps(coro)
        async def warp(self:'Channel', *args, **kargs):
            sign = inspect.signature(coro)

            def getParameter(name: str):
                try:
                    keys = sign.parameters.keys()
                    return kargs[name] if name in kargs else args[list(keys).index(name)-1]
                except:
                    return None
            result=None
            message:Message = getParameter("message")
            if allowExec(self,message.user):
                self._log.info("命令"+coro.__name__+":開始執行")
                result = await coro(self, *args, **kargs)
                self._log.info("命令"+coro.__name__+":執行完成")
            else:
                self._log.warning("命令"+coro.__name__+":不符合執行條件")
            return result
            
            
        w = warp
        func_name = alias if alias else coro.__name__
        commends[func_name] = w
        return w
    return out
