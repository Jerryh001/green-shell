class GWTPayload:
    def __init__(self, target: list):
        self._list_head = ["7", "0"]
        self._str_table = []
        self._target_info = []
        self._para_type_table = []
        self._para_table = []
        for s in target:
            index = self._AddStr(s)
            self._target_info.append(str(index))

    def _AddStr(self, s: str):
        if s is None:
            return 0
        try:
            return self._str_table.index(s) + 1
        except ValueError:
            self._str_table.append(s)
            return self._str_table.index(s) + 1

    def AddPara(self, ptype: str, para: list, *, regonly=False, rawpara=False):
        index = self._AddStr(ptype)
        self._para_type_table.append(str(index))
        if not regonly:
            self._para_table.append(str(index))
        for p in para:
            index = p
            if not rawpara and not isinstance(p, int):
                index = self._AddStr(p)
            self._para_table.append(str(index))

    @property
    def string(self):
        return "|".join(self._list_head + [str(len(self._str_table))] + self._str_table + self._target_info + [str(len(self._para_type_table))] + self._para_type_table + self._para_table) + "|"

    def __str__(self):
        return self.string
