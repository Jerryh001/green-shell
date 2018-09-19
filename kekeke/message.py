from kekeke import *

class MessageType(Enum):
    chat="CHAT_MESSAGE"
    deleteimage="DELETE_MEDIA"
    other=""
    #population="NO_OF_CROWD_MESSAGE"
class Message(object):
    def __init__(self,mtype:MessageType=MessageType.other,time:datetime=datetime.now(),ID:str=0,nickname:str="",content:str="",url:str="",metionIDs=[]):
        self.mtype=mtype
        self.time=time
        self.ID=ID
        self.nickname=nickname
        self.content=content
        self.url=url
        self.metionIDs=metionIDs

    @staticmethod
    def loadjson(json_str:str):
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
        metionIDs=[]
        try:
            metionIDs=message["payload"]["replyPublicIds"]
        except:
            pass
        return Message(mtype=mtype,time=message_time,ID=message["senderPublicId"],nickname=message["senderNickName"],content=message["content"],url=url.group(0) if url else "",metionIDs=metionIDs)