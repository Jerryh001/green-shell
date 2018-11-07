__all__=["Message","MessageType"]
import html
import json
import re
from datetime import datetime
from enum import Enum

import tzlocal

from .user import User


class MessageType(Enum):
    chat="CHAT_MESSAGE"
    deleteimage="DELETE_MEDIA"
    vote="VOTE_MESSAGE"
    other=""
    population="NO_OF_CROWD_MESSAGE"
class Message:
    def __init__(self,mtype:MessageType=MessageType.other,time:datetime=datetime.now(),user:User=User(),content:str="",url:str="",metionUsers:list=[],payload:dict=dict()):
        self.mtype=mtype
        self.time=time
        self.user=user
        self.content=content
        self.url=url
        self.metionUsers=metionUsers
        self.payload=payload

    @staticmethod
    def loadjson(json_str:str)->'Message':
        message=json.loads(json_str)
        mtype:MessageType
        try:
            mtype=MessageType(message["eventType"])
        except ValueError:
            mtype=MessageType.other
        if mtype == MessageType.other:
            return None
        for key in message:
            message[key]=html.unescape(message[key])
        message_time=tzlocal.get_localzone().localize(datetime.fromtimestamp(float(message["date"])/1000))
        
        url=re.search(r'https?://\S+',message["content"], re.IGNORECASE)
        
        metionUsers=[]
        try:
            metionIDs=message["payload"]["replyPublicIds"]
            names=re.findall(r"(?<=@)\S+",message["content"],re.IGNORECASE)
            prefix="?#" if len(names) != len(metionIDs) else ""
            for i in range(len(metionIDs)):
                if i<len(names):
                    metionUsers.append(User(name=prefix+names[i],ID=metionIDs[i]))
                else:
                    metionUsers.append(User(name=prefix+metionIDs[i][:5],ID=metionIDs[i]))
        except:
            pass
        usercolor:str=""
        try:
            usercolor=message["senderColorToken"]
        except:
            pass
        return Message(mtype=mtype,time=message_time,user=User(ID=message["senderPublicId"],name=message["senderNickName"],color=usercolor),content=message["content"],url=url.group(0) if url else "",metionUsers=metionUsers,payload=message["payload"])
