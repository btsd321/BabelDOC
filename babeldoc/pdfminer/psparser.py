#!/usr/bin/env python3
import io
import logging
import re
from collections.abc import Iterator
from typing import Any
from typing import BinaryIO
from typing import Generic
from typing import TypeVar
from typing import Union

from babeldoc.pdfminer.utils import choplist
from babeldoc.pdfminer import psexceptions
from babeldoc.pdfminer import settings

log = logging.getLogger(__name__)


# Adding aliases for these exceptions for backwards compatibility
PSException = psexceptions.PSException
PSEOF = psexceptions.PSEOF
PSSyntaxError = psexceptions.PSSyntaxError
PSTypeError = psexceptions.PSTypeError
PSValueError = psexceptions.PSValueError


class PSObject:
    """Base class for all PS or PDF-related data types."""


class PSLiteral(PSObject):
    """A class that represents a PostScript literal.

    Postscript literals are used as identifiers, such as
    variable names, property names and dictionary keys.
    Literals are case sensitive and denoted by a preceding
    slash sign (e.g. "/Name")

    Note: Do not create an instance of PSLiteral directly.
    Always use PSLiteralTable.intern().
    """

    NameType = Union[str, bytes]

    def __init__(self, name: NameType) -> None:
        self.name = name

    def __repr__(self) -> str:
        name = self.name
        return "/%r" % name


class PSKeyword(PSObject):
    """A class that represents a PostScript keyword.

    PostScript keywords are a dozen of predefined words.
    Commands and directives in PostScript are expressed by keywords.
    They are also used to denote the content boundaries.

    Note: Do not create an instance of PSKeyword directly.
    Always use PSKeywordTable.intern().
    """

    def __init__(self, name: bytes) -> None:
        self.name = name

    def __repr__(self) -> str:
        name = self.name
        return "/%r" % name


_SymbolT = TypeVar("_SymbolT", PSLiteral, PSKeyword)


class PSSymbolTable(Generic[_SymbolT]):
    """A utility class for storing PSLiteral/PSKeyword objects.

    Interned objects can be checked its identity with "is" operator.
    """

    def __init__(self, klass: type[_SymbolT]) -> None:
        self.dict: dict[PSLiteral.NameType, _SymbolT] = {}
        self.klass: type[_SymbolT] = klass

    def intern(self, name: PSLiteral.NameType) -> _SymbolT:
        if name in self.dict:
            lit = self.dict[name]
        else:
            # Type confusion issue: PSKeyword always takes bytes as name
            #                       PSLiteral uses either str or bytes
            lit = self.klass(name)  # type: ignore[arg-type]
            self.dict[name] = lit
        return lit


PSLiteralTable = PSSymbolTable(PSLiteral)
PSKeywordTable = PSSymbolTable(PSKeyword)
LIT = PSLiteralTable.intern
KWD = PSKeywordTable.intern
KEYWORD_PROC_BEGIN = KWD(b"{")
KEYWORD_PROC_END = KWD(b"}")
KEYWORD_ARRAY_BEGIN = KWD(b"[")
KEYWORD_ARRAY_END = KWD(b"]")
KEYWORD_DICT_BEGIN = KWD(b"<<")
KEYWORD_DICT_END = KWD(b">>")


def literal_name(x: Any) -> str:
    if isinstance(x, PSLiteral):
        if isinstance(x.name, str):
            return x.name
        try:
            return str(x.name, "utf-8")
        except UnicodeDecodeError:
            return str(x.name)
    else:
        if settings.STRICT:
            raise PSTypeError(f"Literal required: {x!r}")
        return str(x)


def keyword_name(x: Any) -> Any:
    if not isinstance(x, PSKeyword):
        if settings.STRICT:
            raise PSTypeError("Keyword required: %r" % x)
        else:
            name = x
    else:
        name = str(x.name, "utf-8", "ignore")
    return name


EOL = re.compile(rb"[\r\n]")
SPC = re.compile(rb"\s")
NONSPC = re.compile(rb"\S")
HEX = re.compile(rb"[0-9a-fA-F]")
END_LITERAL = re.compile(rb"[#/%\[\]()<>{}\s]")
END_HEX_STRING = re.compile(rb"[^\s0-9a-fA-F]")
HEX_PAIR = re.compile(rb"[0-9a-fA-F]{2}|.")
END_NUMBER = re.compile(rb"[^0-9]")
END_KEYWORD = re.compile(rb"[#/%\[\]()<>{}\s]")
END_STRING = re.compile(rb"[()\134]")
OCT_STRING = re.compile(rb"[0-7]")
ESC_STRING = {
    b"b": 8,
    b"t": 9,
    b"n": 10,
    b"f": 12,
    b"r": 13,
    b"(": 40,
    b")": 41,
    b"\\": 92,
}


PSBaseParserToken = Union[float, bool, PSLiteral, PSKeyword, bytes]


class PSBaseParser:
    """Most basic PostScript parser that performs only tokenization."""

    BUFSIZ = 4096

    def __init__(self, fp: BinaryIO) -> None:
        self.fp = fp
        self.eof = False
        self.seek(0)

    def __repr__(self) -> str:
        return "<%s: %r, bufpos=%d>" % (self.__class__.__name__, self.fp, self.bufpos)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.flush()

    def tell(self) -> int:
        return self.bufpos + self.charpos

    def poll(self, pos: int | None = None, n: int = 80) -> None:
        pos0 = self.fp.tell()
        if not pos:
            pos = self.bufpos + self.charpos
        self.fp.seek(pos)
        log.debug("poll(%d): %r", pos, self.fp.read(n))
        self.fp.seek(pos0)

    def seek(self, pos: int) -> None:
        """Seeks the parser to the given position."""
        log.debug("seek: %r", pos)
        self.fp.seek(pos)
        # reset the status for nextline()
        self.bufpos = pos
        self.buf = b""
        self.charpos = 0
        # reset the status for nexttoken()
        self._parse1 = self._parse_main
        self._curtoken = b""
        self._curtokenpos = 0
        self._tokens: list[tuple[int, PSBaseParserToken]] = []
        self.eof = False

    def fillbuf(self) -> None:
        if self.charpos < len(self.buf):
            return
        # fetch next chunk.
        self.bufpos = self.fp.tell()
        self.buf = self.fp.read(self.BUFSIZ)
        if not self.buf:
            raise PSEOF("Unexpected EOF")
        self.charpos = 0

    def nextline(self) -> tuple[int, bytes]:
        """Fetches a next line that ends either with \\r or \\n."""
        linebuf = b""
        linepos = self.bufpos + self.charpos
        eol = False
        while 1:
            self.fillbuf()
            if eol:
                c = self.buf[self.charpos : self.charpos + 1]
                # handle b'\r\n'
                if c == b"\n":
                    linebuf += c
                    self.charpos += 1
                break
            m = EOL.search(self.buf, self.charpos)
            if m:
                linebuf += self.buf[self.charpos : m.end(0)]
                self.charpos = m.end(0)
                if linebuf[-1:] == b"\r":
                    eol = True
                else:
                    break
            else:
                linebuf += self.buf[self.charpos :]
                self.charpos = len(self.buf)
        log.debug("nextline: %r, %r", linepos, linebuf)

        return (linepos, linebuf)

    def revreadlines(self) -> Iterator[bytes]:
        """Fetches a next line backword.

        This is used to locate the trailers at the end of a file.
        """
        self.fp.seek(0, io.SEEK_END)
        pos = self.fp.tell()
        buf = b""
        while pos > 0:
            prevpos = pos
            pos = max(0, pos - self.BUFSIZ)
            self.fp.seek(pos)
            s = self.fp.read(prevpos - pos)
            if not s:
                break
            while 1:
                n = max(s.rfind(b"\r"), s.rfind(b"\n"))
                if n == -1:
                    buf = s + buf
                    break
                yield s[n:] + buf
                s = s[:n]
                buf = b""

    def _parse_main(self, s: bytes, i: int) -> int:
        m = NONSPC.search(s, i)
        if not m:
            return len(s)
        j = m.start(0)
        c = s[j : j + 1]
        self._curtokenpos = self.bufpos + j
        if c == b"%":
            self._curtoken = b"%"
            self._parse1 = self._parse_comment
            return j + 1
        elif c == b"/":
            self._curtoken = b""
            self._parse1 = self._parse_literal
            return j + 1
        elif c in b"-+" or c.isdigit():
            self._curtoken = c
            self._parse1 = self._parse_number
            return j + 1
        elif c == b".":
            self._curtoken = c
            self._parse1 = self._parse_float
            return j + 1
        elif c.isalpha():
            self._curtoken = c
            self._parse1 = self._parse_keyword
            return j + 1
        elif c == b"(":
            self._curtoken = b""
            self.paren = 1
            self._parse1 = self._parse_string
            return j + 1
        elif c == b"<":
            self._curtoken = b""
            self._parse1 = self._parse_wopen
            return j + 1
        elif c == b">":
            self._curtoken = b""
            self._parse1 = self._parse_wclose
            return j + 1
        elif c == b"\x00":
            return j + 1
        else:
            self._add_token(KWD(c))
            return j + 1

    def _add_token(self, obj: PSBaseParserToken) -> None:
        self._tokens.append((self._curtokenpos, obj))

    def _parse_comment(self, s: bytes, i: int) -> int:
        m = EOL.search(s, i)
        if not m:
            self._curtoken += s[i:]
            return len(s)
        j = m.start(0)
        self._curtoken += s[i:j]
        self._parse1 = self._parse_main
        # We ignore comments.
        # self._tokens.append(self._curtoken)
        return j

    def _parse_literal(self, s: bytes, i: int) -> int:
        m = END_LITERAL.search(s, i)
        if not m:
            self._curtoken += s[i:]
            return len(s)
        j = m.start(0)
        self._curtoken += s[i:j]
        c = s[j : j + 1]
        if c == b"#":
            self.hex = b""
            self._parse1 = self._parse_literal_hex
            return j + 1
        try:
            name: str | bytes = str(self._curtoken, "utf-8")
        except Exception:
            name = self._curtoken
        self._add_token(LIT(name))
        self._parse1 = self._parse_main
        return j

    def _parse_literal_hex(self, s: bytes, i: int) -> int:
        c = s[i : i + 1]
        if HEX.match(c) and len(self.hex) < 2:
            self.hex += c
            return i + 1
        if self.hex:
            self._curtoken += bytes((int(self.hex, 16),))
        self._parse1 = self._parse_literal
        return i

    def _parse_number(self, s: bytes, i: int) -> int:
        m = END_NUMBER.search(s, i)
        if not m:
            self._curtoken += s[i:]
            return len(s)
        j = m.start(0)
        self._curtoken += s[i:j]
        c = s[j : j + 1]
        if c == b".":
            self._curtoken += c
            self._parse1 = self._parse_float
            return j + 1
        try:
            self._add_token(int(self._curtoken))
        except ValueError:
            pass
        self._parse1 = self._parse_main
        return j

    def _parse_float(self, s: bytes, i: int) -> int:
        m = END_NUMBER.search(s, i)
        if not m:
            self._curtoken += s[i:]
            return len(s)
        j = m.start(0)
        self._curtoken += s[i:j]
        try:
            self._add_token(float(self._curtoken))
        except ValueError:
            pass
        self._parse1 = self._parse_main
        return j

    def _parse_keyword(self, s: bytes, i: int) -> int:
        m = END_KEYWORD.search(s, i)
        if m:
            j = m.start(0)
            self._curtoken += s[i:j]
        else:
            self._curtoken += s[i:]
            return len(s)
        if self._curtoken == b"true":
            token: bool | PSKeyword = True
        elif self._curtoken == b"false":
            token = False
        else:
            token = KWD(self._curtoken)
        self._add_token(token)
        self._parse1 = self._parse_main
        return j

    def _parse_string(self, s: bytes, i: int) -> int:
        m = END_STRING.search(s, i)
        if not m:
            self._curtoken += s[i:]
            return len(s)
        j = m.start(0)
        self._curtoken += s[i:j]
        c = s[j : j + 1]
        if c == b"\\":
            self.oct = b""
            self._parse1 = self._parse_string_1
            return j + 1
        if c == b"(":
            self.paren += 1
            self._curtoken += c
            return j + 1
        if c == b")":
            self.paren -= 1
            if self.paren:
                # WTF, they said balanced parens need no special treatment.
                self._curtoken += c
                return j + 1
        self._add_token(self._curtoken)
        self._parse1 = self._parse_main
        return j + 1

    def _parse_string_1(self, s: bytes, i: int) -> int:
        """Parse literal strings

        PDF Reference 3.2.3
        """
        c = s[i : i + 1]
        if OCT_STRING.match(c) and len(self.oct) < 3:
            self.oct += c
            return i + 1

        elif self.oct:
            chrcode = int(self.oct, 8)
            assert chrcode < 256, "Invalid octal %s (%d)" % (repr(self.oct), chrcode)
            self._curtoken += bytes((chrcode,))
            self._parse1 = self._parse_string
            return i

        elif c in ESC_STRING:
            self._curtoken += bytes((ESC_STRING[c],))

        elif c == b"\r" and len(s) > i + 1 and s[i + 1 : i + 2] == b"\n":
            # If current and next character is \r\n skip both because enters
            # after a \ are ignored
            i += 1

        # default action
        self._parse1 = self._parse_string
        return i + 1

    def _parse_wopen(self, s: bytes, i: int) -> int:
        c = s[i : i + 1]
        if c == b"<":
            self._add_token(KEYWORD_DICT_BEGIN)
            self._parse1 = self._parse_main
            i += 1
        else:
            self._parse1 = self._parse_hexstring
        return i

    def _parse_wclose(self, s: bytes, i: int) -> int:
        c = s[i : i + 1]
        if c == b">":
            self._add_token(KEYWORD_DICT_END)
            i += 1
        self._parse1 = self._parse_main
        return i

    def _parse_hexstring(self, s: bytes, i: int) -> int:
        m = END_HEX_STRING.search(s, i)
        if not m:
            self._curtoken += s[i:]
            return len(s)
        j = m.start(0)
        self._curtoken += s[i:j]
        token = HEX_PAIR.sub(
            lambda m: bytes((int(m.group(0), 16),)),
            SPC.sub(b"", self._curtoken),
        )
        self._add_token(token)
        self._parse1 = self._parse_main
        return j

    def nexttoken(self) -> tuple[int, PSBaseParserToken]:
        if self.eof:
            # It's not really unexpected, come on now...
            raise PSEOF("Unexpected EOF")
        while not self._tokens:
            try:
                self.fillbuf()
                self.charpos = self._parse1(self.buf, self.charpos)
            except PSEOF:
                # If we hit EOF in the middle of a token, try to parse
                # it by tacking on whitespace, and delay raising PSEOF
                # until next time around
                self.charpos = self._parse1(b"\n", 0)
                self.eof = True
                # Oh, so there wasn't actually a token there? OK.
                if not self._tokens:
                    raise
        token = self._tokens.pop(0)
        log.debug("nexttoken: %r", token)
        return token


# Stack slots may by occupied by any of:
#  * the name of a literal
#  * the PSBaseParserToken types
#  * list (via KEYWORD_ARRAY)
#  * dict (via KEYWORD_DICT)
#  * subclass-specific extensions (e.g. PDFStream, PDFObjRef) via ExtraT
ExtraT = TypeVar("ExtraT")
PSStackType = Union[str, float, bool, PSLiteral, bytes, list, dict, ExtraT]
PSStackEntry = tuple[int, PSStackType[ExtraT]]


class PSStackParser(PSBaseParser, Generic[ExtraT]):
    def __init__(self, fp: BinaryIO) -> None:
        PSBaseParser.__init__(self, fp)
        self.reset()

    def reset(self) -> None:
        self.context: list[tuple[int, str | None, list[PSStackEntry[ExtraT]]]] = []
        self.curtype: str | None = None
        self.curstack: list[PSStackEntry[ExtraT]] = []
        self.results: list[PSStackEntry[ExtraT]] = []

    def seek(self, pos: int) -> None:
        PSBaseParser.seek(self, pos)
        self.reset()

    def push(self, *objs: PSStackEntry[ExtraT]) -> None:
        self.curstack.extend(objs)

    def pop(self, n: int) -> list[PSStackEntry[ExtraT]]:
        objs = self.curstack[-n:]
        self.curstack[-n:] = []
        return objs

    def popall(self) -> list[PSStackEntry[ExtraT]]:
        objs = self.curstack
        self.curstack = []
        return objs

    def add_results(self, *objs: PSStackEntry[ExtraT]) -> None:
        try:
            log.debug("add_results: %r", objs)
        except Exception:
            log.debug("add_results: (unprintable object)")
        self.results.extend(objs)

    def start_type(self, pos: int, type: str) -> None:
        self.context.append((pos, self.curtype, self.curstack))
        (self.curtype, self.curstack) = (type, [])
        log.debug("start_type: pos=%r, type=%r", pos, type)

    def end_type(self, type: str) -> tuple[int, list[PSStackType[ExtraT]]]:
        if self.curtype != type:
            raise PSTypeError(f"Type mismatch: {self.curtype!r} != {type!r}")
        objs = [obj for (_, obj) in self.curstack]
        (pos, self.curtype, self.curstack) = self.context.pop()
        log.debug("end_type: pos=%r, type=%r, objs=%r", pos, type, objs)
        return (pos, objs)

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        pass

    def nextobject(self) -> PSStackEntry[ExtraT]:
        """Yields a list of objects.

        Arrays and dictionaries are represented as Python lists and
        dictionaries.

        :return: keywords, literals, strings, numbers, arrays and dictionaries.
        """
        while not self.results:
            (pos, token) = self.nexttoken()
            if isinstance(token, (int, float, bool, str, bytes, PSLiteral)):
                # normal token
                self.push((pos, token))
            elif token == KEYWORD_ARRAY_BEGIN:
                # begin array
                self.start_type(pos, "a")
            elif token == KEYWORD_ARRAY_END:
                # end array
                try:
                    self.push(self.end_type("a"))
                except PSTypeError:
                    if settings.STRICT:
                        raise
            elif token == KEYWORD_DICT_BEGIN:
                # begin dictionary
                self.start_type(pos, "d")
            elif token == KEYWORD_DICT_END:
                # end dictionary
                try:
                    (pos, objs) = self.end_type("d")
                    if len(objs) % 2 != 0:
                        error_msg = "Invalid dictionary construct: %r" % objs
                        raise PSSyntaxError(error_msg)
                    d = {
                        literal_name(k): v
                        for (k, v) in choplist(2, objs)
                        if v is not None
                    }
                    self.push((pos, d))
                except PSTypeError:
                    if settings.STRICT:
                        raise
            elif token == KEYWORD_PROC_BEGIN:
                # begin proc
                self.start_type(pos, "p")
            elif token == KEYWORD_PROC_END:
                # end proc
                try:
                    self.push(self.end_type("p"))
                except PSTypeError:
                    if settings.STRICT:
                        raise
            elif isinstance(token, PSKeyword):
                log.debug(
                    "do_keyword: pos=%r, token=%r, stack=%r",
                    pos,
                    token,
                    self.curstack,
                )
                self.do_keyword(pos, token)
            else:
                log.error(
                    "unknown token: pos=%r, token=%r, stack=%r",
                    pos,
                    token,
                    self.curstack,
                )
                self.do_keyword(pos, token)
                raise PSException
            if self.context:
                continue
            else:
                self.flush()
        obj = self.results.pop(0)
        try:
            log.debug("nextobject: %r", obj)
        except Exception:
            log.debug("nextobject: (unprintable object)")
        return obj
