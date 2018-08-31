import aiohttp
import asyncio
import json
import re
import time
from os import path
from datetime import datetime
from datetime import timezone
import tzlocal
import logging
import discord
from discord.ext import commands

class DetectDetail(object):
    isdetect:bool=False
    loc:tuple=(0,0)
    def __init__(self,isdetect:bool=False,loc:tuple=(0,0)):
        self.isdetect=isdetect
        self.loc=loc
    def __bool__(self):
        return self.isdetect
        
class Message(object):
    def __init__(self,time:datetime=datetime.now(),ID:int=0,nickname:str="",content:str=""):
        self.time=time
        self.ID=ID
        self.nickname=nickname
        self.content=content
        self.ID_detect=DetectDetail()
        self.name_detect=DetectDetail()
        self.message_detect=DetectDetail()
    def DetectMessage(self,keyword_list:list,trusted_list:list):
        if self.ID in keyword_list["ID"]:
            self.ID_detect=DetectDetail(True)

        for name in keyword_list["name"]:
            s=re.search(name, self.nickname, re.IGNORECASE)
            if s:
                self.name_detect=DetectDetail(True,s.span())
                break

        for m in keyword_list["message"]:
            pattren=re.search(m, self.content, re.IGNORECASE)
            if pattren:
                self.message_detect=DetectDetail(True,pattren.span())
                break

        for ex in keyword_list["EXmessage"]:
            if self.content.lower()==ex.lower():
                self.message_detect=DetectDetail(True,(0,len(ex)))
                break

        for keyword in keyword_list["keyword"]:
            pattren=re.search(keyword, self.nickname, re.IGNORECASE)
            if pattren:
                self.name_detect=DetectDetail(True,pattren.span())
                break


        for keyword in keyword_list["keyword"]:      
            pattren=re.search(keyword, self.content, re.IGNORECASE)
            if pattren:
                self.message_detect=DetectDetail(True,pattren.span())
                break

        if trusted_list.__contains__(self.nickname):
            if self.ID not in trusted_list[self.nickname]:
                self.name_detect=DetectDetail(True,(0,len(self.nickname)))

        if re.search(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',self.content, re.IGNORECASE):
            self.message_detect.isdetect=False
        
    def Detected(self):
        return self.ID_detect or self.name_detect or self.message_detect



class Channel(object):
    name:str
    messages=[]
    thumbnail:str
    def __init__(self,name:str="",ID:int=0,messages=[],thumbnail:str=""):
        self.name=name
        self.messages=messages.copy()
        self.thumbnail=thumbnail


class KWDetector(object):
    _url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    _payload = r"7|0|4|https://kekeke.cc/com.liquable.hiroba.home.gwt.HomeModule/|53263EDF7F9313FDD5BD38B49D3A7A77|com.liquable.hiroba.gwt.client.square.IGwtSquareService|getLatestSquares|1|2|3|4|0|"
    _keyword_list=[]
    _trusted_list=[]
    def __init__(self,stdout):
        self.stdout=stdout
        self._log=logging.getLogger(self.__class__.__name__)
        self.JsonLoad()

    def JsonLoad(self):
        dirname = path.dirname(__file__)
        self._keyword_list=json.load(open(path.join(dirname, "keyword.json"), 'r',encoding='utf8'))
        self._trusted_list=json.load(open(path.join(dirname, "trusted_user.json"), 'r',encoding='utf8'))
    async def GetHPMessages(self):
        try:
            async with aiohttp.request("POST",self._url, data=self._payload,headers=self._header) as r:
                resp = await r.text()
        except:
            self._log.error("Fetch kekeke HP failed")
        if resp[:4]==r"//OK":
            data=json.loads(resp[4:])[-3]
            output=[]
            curr_channel=Channel()
            for s in reversed(data):
                if s[0]=='/':#topic
                    if curr_channel.messages:
                        output.append(curr_channel)
                    curr_channel=Channel(name=s.replace("/topic/",""))
                    curr_channel.messages.clear()#?
                elif s[0]=='{':#message
                    m=json.loads(s)
                    ts=datetime.fromtimestamp(int(m["date"])/1000)
                    message_time=tzlocal.get_localzone().localize(ts)
                    message=Message(time=message_time,ID=m["senderPublicId"],nickname=m["senderNickName"],content=m["content"])
                    message.DetectMessage(self._keyword_list,self._trusted_list)
                    if message.Detected():
                        curr_channel.messages.append(message)
                elif s[:4]=="http":#thumbnail
                    curr_channel.thumbnail=s
            return output

        else:
            self._log.warning("Parse messages kekeke HP failed, response:"+resp[:4])



    async def Detect(self):
        #self.JsonLoad()
        HP=await self.GetHPMessages()          
        return HP

    async def SendReport(self,data:list):
        if not data:
            return
        embed=discord.Embed(timestamp=tzlocal.get_localzone().localize(datetime.now()))
        embed.set_footer(text="kekeke.cc")
        for board in data:
            embed_content="<https://kekeke.cc/"+board.name+">\n\n"
            for message in board.messages:
                embed_content+=r"`"+message.time.strftime('%H:%M:%S')+r"`"

                embed_content+=r":star:"
                if message.ID_detect:
                    embed_content+=r"__**"+message.ID[:5]+r"**__"
                else:
                    embed_content+=message.ID[:5]

                embed_content+=r":spy:"
                if message.name_detect:
                    loc=message.name_detect.loc
                    embed_content+=(
                        message.nickname[:loc[0]]+
                        "__**"+message.nickname[loc[0]:loc[1]]+"**__"+
                        message.nickname[loc[1]:])
                else:
                    embed_content+=message.nickname

                embed_content+="\n"
                
                if message.message_detect:
                    loc=message.message_detect.loc
                    embed_content+=message.content[:loc[0]]+r"__**"+message.content[loc[0]:loc[1]]+r"**__"+message.content[loc[1]:]
                else:
                    embed_content+=message.content

                embed_content+="\n"
            embed_content+="====================\n"
            embed.add_field(name=board.name,value=embed_content,inline=False)
        print("send")
        await self.stdout.send(embed=embed)

    async def PeriodRun(self,period:int):
        self._log.info("Starting monitor kekeke HP ......")
        while True:
            self._log.info("Checking kekeke HP ......")
            data=await self.GetHPMessages()
            if len(data)>0:
                async with self.stdout.typing():
                    await self.SendReport(data)
                self._log.info("kekeke HP updated!")
            else:
                self._log.info("kekeke HP has nothing to update")
            await asyncio.sleep(period)



if __name__=="__main__":
    asyncio.get_event_loop().run_until_complete(KWDetector(None).Detect())