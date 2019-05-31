__all__ = ["Message", "Media"]


import html
import json
import re
from datetime import datetime

import tzlocal

from .user import User


class Message:
    from enum import Enum

    class MessageType(Enum):
        chat = "CHAT_MESSAGE"
        keke = "KEKE_MESSAGE"
        deleteimage = "DELETE_MEDIA"
        vote = "VOTE_MESSAGE"
        other = ""
        population = "NO_OF_CROWD_MESSAGE"
        system = "SYSTEM_MESSAGE"
        euro = "SUCK_EURO_AIR_MESSAGE"

    def __init__(self, mtype: MessageType = MessageType.chat, time: datetime = None, user: User = User(), content: str = "", url: str = "", metionUsers: list = [], payload: dict = dict(), anchorUsername: str = ""):
        self.mtype = mtype
        self.time = time if time else tzlocal.get_localzone().localize(datetime.now())
        self.user = user
        self.content = content
        self.url = url
        self.metionUsers = metionUsers
        self.payload = payload

    @staticmethod
    def loadjsonlist(jsonlist: list)->list:
        messages: list = list()
        for json in jsonlist:
            m = Message.loadjson(json)
            if(not m or not m.user.ID):
                continue
            messages.append(m)
        return messages

    @staticmethod
    def loadjson(json_str: str)->'Message':
        try:
            message = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        mtype: Message.MessageType
        try:
            mtype = Message.MessageType(message["eventType"])
        except ValueError:
            mtype = Message.MessageType.other
        if mtype == Message.MessageType.other:
            return None
        for key in message:
            message[key] = html.unescape(message[key])
        message_time = tzlocal.get_localzone().localize(datetime.fromtimestamp(float(message["date"])/1000))

        url = re.search(r'https?://\S+', message["content"], re.IGNORECASE)

        metionUsers = []
        try:
            metionIDs = message["payload"]["replyPublicIds"]
            names = re.findall(r"(?<=@)\S+", message["content"], re.IGNORECASE)
            prefix = "?#" if len(names) != len(metionIDs) else ""
            for i in range(len(metionIDs)):
                if i < len(names):
                    metionUsers.append(User(name=prefix+names[i], ID=metionIDs[i]))
                else:
                    metionUsers.append(User(name=prefix+metionIDs[i][:5], ID=metionIDs[i]))
        except:
            pass
        usercolor: str = ""
        try:
            usercolor = message["senderColorToken"]
        except:
            pass
        return Message(mtype=mtype, time=message_time, user=User(ID=message["senderPublicId"], name=message["senderNickName"], color=usercolor, anchorUsername=message["anchorUsername"]), content=message["content"], url=url.group(0) if url else "", metionUsers=metionUsers, payload=message["payload"] if "payload" in message else dict())

    def __eq__(self, that):
        return isinstance(that, Message) and self.mtype == that.mtype and self.time == that.time and self.user.ID == that.user.ID and self.content == that.content


class Media:

    @staticmethod
    def loadMeaaage(message: Message)->"Media":
        media = None
        if re.search(r"(^https://.+\.youtube\.com/.+|^https?://\S+\.(jpe?g|png|gif|mp4)$)", message.url, re.IGNORECASE):
            media = Media(user=message.user, url=message.url, remove=(message.mtype == Message.MessageType.deleteimage))
        return media

    def __init__(self, user: User, url: str, remove=False):
        self.user = user
        self.url = url
        self.remove = remove

    def __hash__(self):
        return hash(self.user.ID+self.url)

    def __eq__(self, that):
        return self.user.ID == that.user.ID and self.url == that.url
