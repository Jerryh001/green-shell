class User:
    def __init__(self,name:str="",ID:str="",color:str=""):
        self.nickname=name
        self.ID=ID
        self.color=color
    def __eq__(self,that):
        return isinstance(that,User) and self.ID==that.ID
    def __hash__(self):
        return int(self.ID,16) if self.ID else 0
