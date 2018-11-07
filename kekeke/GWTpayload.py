

class GWTPayload:

    def __init__(self,target:list):
        self._list_head=["7","0"]
        self._str_table=[]
        self._target_info=[]
        self._para_type_table=[]
        self._para_table=[]
        for s in target:
            index=self._AddStr(s)
            self._target_info.append(str(index))

    def _AddStr(self,s:str):
        if s is None:
            return 0
        try:
            return self._str_table.index(s)+1
        except ValueError:
            self._str_table.append(s)
            return self._str_table.index(s)+1



    def AddPara(self,ptype:str,para:list,regonly=False):
        index=self._AddStr(ptype)
        self._para_type_table.append(str(index))
        if not regonly:
            self._para_table.append(str(index))
        for p in para:
            index=self._AddStr(p)
            self._para_table.append(str(index))
    @property
    def string(self):
        return "|".join(self._list_head+
        [str(len(self._str_table))]+
        self._str_table+
        self._target_info+
        [str(len(self._para_type_table))]+
        self._para_type_table+
        self._para_table)+"|"
    
    def __str__(self):
        return self.string

if __name__=="__main__":
    p=GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/","C8317665135E6B272FC628F709ED7F2C","com.liquable.hiroba.gwt.client.vote.IGwtVoteService","createVotingForForbid"])
    p.AddPara("com.liquable.gwt.transport.client.Destination/2061503238",["/topic/測試123"])
    p.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082",["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017","7b301154","3b0f2a3a8a2a35a9c9727f188772ba095b239668","Jerryh001","3b0f2a3a8a2a35a9c9727f188772ba095b239668"])
    p.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082",["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017",None,"59049bd18178820ed6db05aab2617ede7a1cf25e","Discord#Bot","59049bd18178820ed6db05aab2617ede7a1cf25e"])
    p.AddPara("java.lang.String/2004016611",[""],True)
    print(p)
