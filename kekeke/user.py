import re


class User:
    def __init__(self, name: str = "", ID: str = "", color: str = "", anchorUsername: str = ""):
        self.nickname = name[6:] if re.match(r"[0-9a-f]{5}#", name) else name
        self.ID = ID
        self.color = color
        self.anchorUsername = anchorUsername

    def __eq__(self, that):
        return isinstance(that, User) and self.ID == that.ID

    def __hash__(self):
        return int(self.ID, 16) if self.ID else 0
