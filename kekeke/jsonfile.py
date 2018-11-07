import json
import os
from datetime import datetime

import tzlocal


class JsonFile:
    def __init__(self, path: str):
        self._path = path
        self._time = tzlocal.get_localzone().localize(datetime.fromtimestamp(0))
        self._json = None

    @property
    def json(self):
        time = tzlocal.get_localzone().localize(datetime.fromtimestamp(os.path.getmtime(self._path)))
        if not self._json or time > self._time:
            self._json = json.load(open(self._path, 'r', encoding='utf8'))
            self._time = time
        return self._json
