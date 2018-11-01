import inspect
import types
from functools import wraps

commends = dict()


def command(*,alias:str=None, authonly:bool=False):
    def out(coro: types.coroutine):
        @wraps(coro)
        async def warp(self,*args, **kargs):
            sign=inspect.signature(coro)
            def getParameter(name: str):
                try:
                    keys = sign.parameters.keys()
                    return kargs[name] if name in kargs else args[list(keys).index(name)-1]
                except:
                    return None
            message = getParameter("message")
            if authonly and message.user.ID not in ["3b0f2a3a8a2a35a9c9727f188772ba095b239668", "5df087e5e341f555b0401fb69f89b5937ae7e313"]:
                result = None
                self._log.warning("命令"+coro.__name__+":不符合執行條件")
            else:
                
                result = await coro(self,*args, **kargs)

            return result
        w = warp
        func_name=alias if alias else coro.__name__
        commends[func_name] = w
        return w
    return out
