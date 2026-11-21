import re

INVALID_XML_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]")

ROMAN_CHAPTER_RE = re.compile(
    r"^(?:(?=[IVXLCDM])M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})|[Ⅰ-Ⅻⅰ-ⅻ]{1,4})"
    r"(?:\s*[・◆◇■□●○◎★☆\-－―─:.：]\s*\S.*|\s+[^\x00-\x7F].*)$"
)

ROMAN_ALONE_RE = re.compile(
    r"^(?:(?=[IVXLCDM])M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})|[Ⅰ-Ⅻⅰ-ⅻ]{1,4})$"
)

SYMBOL_CHAPTER_RE = re.compile(r"^[◆◇■□●○◎▲△▼▽★☆]\s*\S.{0,48}$")

CHAPTER_PATTERNS = [
    re.compile(r"^(プロローグ|エピローグ|あとがき|序章|終章|幕間|外伝|番外編)(\s*.*)?$"),
    re.compile(r"^電子版\s*SS.*$", re.I),
    re.compile(r"^第[〇一二三四五六七八九十百千0-9０-９]+[章話部節編].*$"),
    re.compile(r"^제\s*[0-9일이삼사오육칠팔구십]+\s*[장화편부절].*$"),
    re.compile(r"^(Chapter|Prologue|Epilogue)\b.*$", re.I),
    ROMAN_CHAPTER_RE,
]

SECTION_PATTERNS = [
    re.compile(r"^第[〇一二三四五六七八九十百千0-9０-９]+節.*$"),
    re.compile(r"^제\s*[0-9일이삼사오육칠팔구십]+\s*절.*$"),
    re.compile(r"^(Section|Part)\s+\d+\b.*$", re.I),
]

TOC_TITLE_RE = re.compile(r"^(目次|もくじ|목차|차례|TABLE OF CONTENTS|CONTENTS)$", re.I)
TOC_ROW_RE = re.compile(r"(?:\.{2,}|…{1,}|⋯{1,}|・{2,})[　 \t]*[0-9０-９]{1,4}\s*$|[　 \t]{2,}[0-9０-９]{1,4}\s*$")
PAGE_SUFFIX_RE = re.compile(r"(?:\.{2,}|…+|⋯+|・{2,}|[　 \t]{2,})[　 \t]*[0-9０-９]{1,4}\s*$")