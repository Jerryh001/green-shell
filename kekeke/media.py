from .user import User


class Media:
    def __init__(self,user:User,url:str,remove=False):
        self.user=user
        self.url=url
        self.remove=remove
    
    def __hash__(self):
        return hash(self.user.ID+self.url)

    def __eq__(self,that):
        return self.user.ID==that.user.ID and self.url==that.url
