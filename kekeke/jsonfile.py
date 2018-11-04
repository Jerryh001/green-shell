import time
import json
import os


class JsonFile:
    def __init__(self, path: str):
        self._path = path
        self._time = time.ctime(0)
        self._json = None

    @property
    def json(self):
        time = os.stat(self._path).st_mtime
        if not self._json or time > self._time:
            self._json = json.load(open(self._path, 'r', encoding='utf8'))
            self._time = time
        return self._json
