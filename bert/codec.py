
import datetime
import re
import time
import pandas as pd
import numpy as np

from erlastic import ErlangTermDecoder, ErlangTermEncoder, Atom

try:
    basestring
except NameError:
    basestring = str


def utc_to_datetime(seconds, microseconds):
    return datetime.datetime.utcfromtimestamp(seconds).replace(microsecond=microseconds)


def datetime_to_utc(dt):
    # Can't use time.mktime as it assumes local timezone
    delta = dt - datetime.datetime(1970, 1, 1, 0, 0)
    return delta.days * 24 * 60 * 60 + delta.seconds, dt.microsecond


def str_to_list(s):
    return [ord(x) for x in s]


def list_to_str(l):
    return "".join(chr(x) for x in l)

RE_TYPE = type(re.compile("foo"))


class BERTDecoder(object):

    def __init__(self, encoding="utf-8"):
        self.encoding = encoding
        self.erlang_decoder = ErlangTermDecoder()

    def decode(self, bytes, offset=0):
        obj = self.erlang_decoder.decode(bytes, offset)
        return self.convert(obj)

    def convert(self, item):
        if isinstance(item, tuple):
            if item and item[0] == "bert":
                return self.convert_bert(item)
            return tuple(self.convert(i) for i in item)
        elif isinstance(item, list):
            if item and item[0] == "bert":
                return self.convert_bert(item)
            return [self.convert(i) for i in item]
        return item

    def convert_bert(self, item):
        bert_type = item[1]
        if bert_type == "nil":
            return None
        elif bert_type == "string":
            return item[3].decode(Atom(item[2]))
        elif bert_type == "dict":
            return dict((self.convert(k), self.convert(v)) for k, v in item[2])
        elif bert_type in ("true", True):
            return True
        elif bert_type in ("false", False):
            return False
        elif bert_type == "time":
            return utc_to_datetime(item[2] * 1000000 + item[3], item[4])
        elif bert_type == "regex":
            flags = 0
            if 'extended' in item[3]:
                flags |= re.VERBOSE
            if 'caseless' in item[3]:
                flags |= re.IGNORECASE
            if 'multiline' in item[3]:
                flags |= re.MULTILINE
            if 'dotall' in item[3]:
                flags |= re.DOTALL
            return re.compile(item[2], flags)
        elif bert_type == "complex":
            return complex(item[2], item[3])
        elif bert_type == "vector":
            return tuple(self.convert(v) for v in item[2])
        elif bert_type == "set":
            return set(self.convert(v) for v in item[2])
        elif bert_type == "series":
            return pd.Series(self.convert(v) for v in item[2])
        elif bert_type == "dataframe":
            return pd.DataFrame(
                columns=[self.convert(v) for v in item[2]],
                data=[self.convert(v) for v in item[3]]
            )
        elif bert_type == "factor":
            return pd.Categorical(
                [self.convert(v) for v in item[2]],
                categories=[self.convert(v) for v in item[3]]
            )
        elif bert_type == "matrix":
            data = [self.convert(v) for v in item[3]]
            dim = [self.convert(v) for v in item[2]]
            return np.matrix(data).reshape(dim)
        elif bert_type == "array":
            return np.array([self.convert(v) for v in item[3]]).reshape([self.convert(v) for v in item[2]])
        raise NotImplementedError("Unknown BERT type %s" % item[1])


class BERTEncoder(object):

    def __init__(self, encoding="utf-8"):
        self.encoding = encoding
        self.erlang_encoder = ErlangTermEncoder()

    def encode(self, obj):
        bert = self.convert(obj)
        return self.erlang_encoder.encode(bert)

    def convert(self, obj):
        if obj is True:
            return (Atom("bert"), Atom("true"))
        elif obj is False:
            return (Atom("bert"), Atom("false"))
        elif obj is None:
            return (Atom("bert"), Atom("nil"))
        elif isinstance(obj, basestring) and not self.__is_ascii(obj):
            return (Atom("bert"), Atom("string"), Atom(self.encoding.upper()), obj.encode(self.encoding))
        elif isinstance(obj, dict):
            return (Atom("bert"), Atom("dict"), [(self.convert(k), self.convert(v)) for k, v in obj.items()])
        elif isinstance(obj, datetime.datetime):
            seconds, microseconds = datetime_to_utc(obj)
            megaseconds = seconds // 1000000
            seconds = seconds % 1000000
            return (Atom("bert"), Atom("time"), megaseconds, seconds, microseconds)
        elif isinstance(obj, list):
            return [self.convert(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(self.convert(item) for item in obj)
        elif type(obj) == RE_TYPE:
            options = []
            if obj.flags & re.VERBOSE:
                options.append(Atom('extended'))
            if obj.flags & re.IGNORECASE:
                options.append(Atom('caseless'))
            if obj.flags & re.MULTILINE:
                options.append(Atom('multiline'))
            if obj.flags & re.DOTALL:
                options.append(Atom('dotall'))
            return (Atom("bert"), Atom("regex"), obj.pattern, tuple(options))
        elif isinstance(obj, complex):
            return (Atom("bert"), Atom("complex"), obj.real, obj.imag)
        elif isinstance(obj, set):
            return (Atom("bert"), Atom("set"),
                [self.convert(item) for item in obj]
            )
        elif isinstance(obj, pd.Series):
            return (Atom("bert"), Atom("series"),
                [self.convert(item) for item in obj]
            )
        elif isinstance(obj, pd.DataFrame):
            return (Atom("bert"), Atom("dataframe"),
                [self.convert(item) for item in obj.columns],
                [self.convert(item) for item in obj.values]
            )
        elif isinstance(obj, pd.Categorical):
            return (Atom("bert"), Atom("factor"),
                [self.convert(item) for item in obj],
                [self.convert(item) for item in obj.categories]
            )
        elif isinstance(obj, np.matrix):
            return (Atom("bert"), Atom("matrix"), obj.shape, obj.tolist())
        elif isinstance(obj, np.ndarray):
            return (Atom("bert"), Atom("array"), obj.shape, obj.tolist())
        return obj

    def __is_ascii(self, s):
        return all(ord(c) < 128 for c in s)
