import asyncio
import inspect
import types
from functools import wraps

from .message import Message
from .red import redis
from .user import User

commands = dict()


class Command:
    def __init__(self, coro: types.coroutine, name: str, help: str, safe: bool, authonly: bool):
        self._coro = coro
        self.name = name
        self.help = help
        self.authonly = authonly
        self.safe = safe

    def __call__(self, channel: 'Channel', *args, **kargs):
        return self._coro(channel, *args, **kargs)


def command(*, safe: bool = False, alias: str = None, authonly: bool = False, help: str = ""):
    def allowExec(self: 'Channel', user: User) -> bool:
        if user.ID == self.user.ID:
            return True
        if redis.sismember(f"{self.redisPerfix}auth", user.ID) or redis.sismember("kekeke::bot::global::auth", user.ID):
            return True
        elif not authonly and redis.sismember(f"{self.redisPerfix}members", user.ID):
            return True
        return False

    async def runLater(job):
        await asyncio.sleep(10)
        try:
            return await job
        except asyncio.CancelledError:
            return None

    def out(coro: types.coroutine):

        func_name = alias if alias else coro.__name__

        @wraps(coro)
        async def warp(self: 'Channel', *args, **kargs):
            sign = inspect.signature(coro)

            def getParameter(name: str):
                try:
                    keys = sign.parameters.keys()
                    return kargs[name] if name in kargs else args[list(keys).index(name) - 1]
                except Exception:
                    return None

            result = None
            message: Message = getParameter("message")
            if allowExec(self, message.user):
                job = coro(self, *args, **kargs)
                if not safe and self.mode != self.BotType.defender:
                    panding = asyncio.ensure_future(runLater(job))
                    self._log.info(f"{message.user}即將執行危險指令{func_name}")
                    self.pandingCommands.append(panding)
                    await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f"❗【危】{message.user}即將執行{func_name}，輸入.stop可以強制終止", metionUsers=list(self.users)), showID=False)
                    result = await panding
                    try:
                        self.pandingCommands.remove(panding)
                    except ValueError:
                        pass
                else:
                    self._log.info(f"{message.user}執行了{func_name}")
                    result = await job
            else:
                self._log.warning(f"{message.user}不符合{func_name}的執行條件")
            return result

        commands[func_name] = Command(warp, func_name, help, safe, authonly)
        return warp

    return out
