#!/usr/bin/env python3
"""Generate std.novs, the NOVA standard library of types (proposals 0008 and 0011).

The patterns of Uri and UriReference are built from the RFC 3986 ABNF. Each rule below transcribes one rule of the RFC 3986 ABNF (Appendix A).
The pattern of Url is built from the URL serializer and the percent-encode
sets of the WHATWG URL Standard (proposal 0011).
The output uses only I-Regexp constructs (RFC 9485): plain groups,
character classes, `|` and bounded quantifiers. Run it with `--check`
to test the patterns against the vectors at the end of this file.

Usage: std.py [--check | --conformance]

Without an option, it rewrites std.novs next to it. --conformance writes
the case conformance/schema/std. Released versions are frozen: std 0.1.0
is std-0.1.0.novs, which this script does not touch.
"""

import re
import sys


def g(*alts: str) -> str:
    """Return a group that matches any of the alternatives."""
    return "(" + "|".join(alts) + ")"


# RFC 3986 Appendix A, bottom up.
ALPHA = "A-Za-z"
DIGIT = "0-9"
HEXDIG = "0-9A-Fa-f"
UNRESERVED = f"{ALPHA}{DIGIT}._~"  # "-" goes last in each class, so it stays literal
SUB_DELIMS = "!$&'()*+,;="

pct_encoded = f"%[{HEXDIG}]{{2}}"
pchar = g(f"[{UNRESERVED}{SUB_DELIMS}:@-]", pct_encoded)

scheme = f"[{ALPHA}][{ALPHA}{DIGIT}+.-]*"
userinfo = g(f"[{UNRESERVED}{SUB_DELIMS}:-]", pct_encoded) + "*"

dec_octet = g("[0-9]", "[1-9][0-9]", "1[0-9]{2}", "2[0-4][0-9]", "25[0-5]")
IPv4address = f"{dec_octet}[.]{dec_octet}[.]{dec_octet}[.]{dec_octet}"

h16 = f"[{HEXDIG}]{{1,4}}"
ls32 = g(f"{h16}:{h16}", IPv4address)


def h16c(n: int) -> str:
    """Return exactly n repetitions of `h16 ":"`."""
    return f"({h16}:){{{n}}}" if n else ""


def upto(n: int) -> str:
    """Return `[ *n( h16 ":" ) h16 ]`, the optional prefix before `::`."""
    if n == 0:
        return f"({h16})?"
    return f"(({h16}:){{0,{n}}}{h16})?"


IPv6address = g(
    h16c(6) + ls32,
    "::" + h16c(5) + ls32,
    upto(0) + "::" + h16c(4) + ls32,
    upto(1) + "::" + h16c(3) + ls32,
    upto(2) + "::" + h16c(2) + ls32,
    upto(3) + "::" + h16c(1) + ls32,
    upto(4) + "::" + ls32,
    upto(5) + "::" + h16,
    upto(6) + "::",
)
IPvFuture = f"[vV][{HEXDIG}]+[.][{UNRESERVED}{SUB_DELIMS}:-]+"
IP_literal = r"\[" + g(IPv6address, IPvFuture) + r"\]"
reg_name = g(f"[{UNRESERVED}{SUB_DELIMS}-]", pct_encoded) + "*"
host = g(IP_literal, IPv4address, reg_name)
port = "[0-9]*"
authority = f"({userinfo}@)?{host}(:{port})?"

segment = pchar + "*"
segment_nz = pchar + "+"
segment_nz_nc = g(f"[{UNRESERVED}{SUB_DELIMS}@-]", pct_encoded) + "+"
path_abempty = f"(/{segment})*"
path_absolute = f"/({segment_nz}(/{segment})*)?"
path_noscheme = f"{segment_nz_nc}(/{segment})*"
path_rootless = f"{segment_nz}(/{segment})*"
path_empty = ""

query = g(pchar, "[/?]") + "*"
fragment = query

hier_part = g("//" + authority + path_abempty, path_absolute, path_rootless, path_empty)
relative_part = g("//" + authority + path_abempty, path_absolute, path_noscheme, path_empty)

URI = f"{scheme}:{hier_part}([?]{query})?(#{fragment})?"
relative_ref = f"{relative_part}([?]{query})?(#{fragment})?"
# `URI / relative-ref`, regrouped so `authority` appears once: the pattern
# must stay under the 4096-character limit of the reference implementation.
URI_reference = (
    g(f"({scheme}:)?" + g("//" + authority + path_abempty, path_absolute, path_empty), f"{scheme}:{path_rootless}", path_noscheme)
    + f"([?]{query})?(#{fragment})?"
)

# Vectors: RFC 3986 §1.1.2 and §5.4, plus edge cases.
VALID_URI = [
    "ftp://ftp.is.co.za/rfc/rfc1808.txt",
    "http://www.ietf.org/rfc/rfc2396.txt",
    "ldap://[2001:db8::7]/c=GB?objectClass?one",
    "mailto:John.Doe@example.com",
    "news:comp.infosystems.www.servers.unix",
    "tel:+1-816-555-1212",
    "telnet://192.0.2.16:80/",
    "urn:oasis:names:specification:docbook:dtd:xml:4.1.2",
    "http://a/b/c/d;p?q",
    "g:h",
    "file:///etc/hosts",
    "http://[::1]:8080/",
    "http://[v7.fe80::1]/",
    "http://[::ffff:192.0.2.1]/",
    "http://user:pw@host/%7Euser",
    "s://",
    "s:",
    "http://a/b/c/g#s/../x",
]
VALID_REF_ONLY = ["g", "./g", "g/", "/g", "//g", "?y", "g?y", "#s", "g#s", "g?y#s", ";x", "g;x", "", ".", "./", "..", "../g", "../../../g"]
INVALID = [
    "http://a b/",
    "http://[::1/",
    "http://[1:2:3:4:5:6:7:8:9]/",
    "http://[:::1]/",
    "http://a/%zz",
    "http://a/\\b",
    " http://a/",
    "http://a/^",
    "1http://a",
]


def check() -> int:
    """Test the patterns against the vectors; return the failure count."""
    uri = re.compile(URI)
    ref = re.compile(URI_reference)
    failures = 0
    cases = [(uri, s, True) for s in VALID_URI]
    cases += [(ref, s, True) for s in VALID_URI + VALID_REF_ONLY]
    cases += [(uri, s, False) for s in VALID_REF_ONLY if ":" not in s.split("/")[0]]
    cases += [(p, s, False) for p in (uri, ref) for s in INVALID]
    for p, s, want in cases:
        if (p.fullmatch(s) is not None) != want:
            name = "Uri" if p is uri else "UriReference"
            print(f"FAIL {name} {s!r}: expected {'match' if want else 'no match'}")
            failures += 1
    failures += check_regrouping()
    failures += check_url()
    return failures


def check_url() -> int:
    """Test Url against its vectors, and the port patterns against every number."""
    url = re.compile(URL)
    failures = 0
    for s, want in [(s, True) for s in VALID_URL] + [(s, False) for s in INVALID_URL]:
        if (url.fullmatch(s) is not None) != want:
            print(f"FAIL Url {s!r}: expected {'match' if want else 'no match'}")
            failures += 1
    for default in set(DEFAULT_PORTS.values()):
        p = re.compile(port_except(default))
        for n in range(0, 70000):
            if (p.fullmatch(str(n)) is not None) != (n != default and n <= 65535):
                print(f"FAIL port_except({default}) on {n}")
                failures += 1
        failures += sum(1 for z in ("00", "01", "080") if p.fullmatch(z))
    if len(URL) > 4096:
        print(f"FAIL Url pattern has {len(URL)} characters, over the 4096 of the reference implementation")
        failures += 1
    return failures


def check_regrouping() -> int:
    """Compare UriReference with the literal `URI / relative-ref` on random input."""
    import random

    literal = re.compile(g(URI, relative_ref))
    ref = re.compile(URI_reference)
    rng = random.Random(3986)
    alphabet = "ab1:/?#[]@%.vF-"
    failures = 0
    for _ in range(50000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        if (literal.fullmatch(s) is None) != (ref.fullmatch(s) is None):
            print(f"FAIL regrouping differs on {s!r}")
            failures += 1
    return failures


VERSION = "0.2.0"
VISIBLE = r"[^\p{Z}\p{Cc}\p{Cf}]"
SEMVER_NUM = "(0|[1-9][0-9]*)"
SEMVER_ID = "(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = (
    f"{SEMVER_NUM}[.]{SEMVER_NUM}[.]{SEMVER_NUM}(-{SEMVER_ID}([.]{SEMVER_ID})*)?"
    "([+][0-9A-Za-z-]+([.][0-9A-Za-z-]+)*)?"
)
PATH_SEGMENT = "[.]?[A-Za-z0-9_]([A-Za-z0-9._-]*[A-Za-z0-9_-])?"
EMAIL = (
    "[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    "([.][A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
)
URN = (
    "urn:[A-Za-z0-9][A-Za-z0-9-]{0,30}[A-Za-z0-9]:([A-Za-z0-9._~!$&'()*+,;=:@-]|%[0-9A-Fa-f]{2})"
    "([A-Za-z0-9._~!$&'()*+,;=:@/-]|%[0-9A-Fa-f]{2})*"
)

# WHATWG URL serializations (proposal 0011). A serialization is ASCII: every
# percent-encode set contains all code points above U+007E. "%" is never encoded.
PRINTABLE = [chr(c) for c in range(0x21, 0x7F)]


def chars(excluded: str, space: bool = False) -> str:
    """A class of the printable ASCII characters (and space) not in `excluded`."""
    return char_class(set(([" "] if space else []) + PRINTABLE) - set(excluded))


def char_class(cs: set) -> str:
    """A class of exactly the ASCII characters `cs`, as ranges where possible."""
    allowed = sorted(cs)
    out, i = [], 0
    while i < len(allowed):
        j = i
        while j + 1 < len(allowed) and ord(allowed[j + 1]) == ord(allowed[j]) + 1:
            j += 1
        esc = lambda c: "\\" + c if c in "\\]^-[" else c
        out.append(esc(allowed[i]) if j == i else esc(allowed[i]) + ("-" if j > i + 1 else "") + esc(allowed[j]))
        i = j + 1
    return "[" + "".join(out) + "]"


def number_range(lo: int, hi: int) -> str:
    """The decimal integers lo..=hi without leading zeros."""

    def split(a: str, b: str) -> list:
        if len(a) == 1:
            return [a if a == b else f"[{a}-{b}]"]
        if a[0] == b[0]:
            return [a[0] + r for r in split(a[1:], b[1:])]
        zeros, nines = "0" * (len(a) - 1), "9" * (len(a) - 1)
        out, tail = [], []
        if a[1:] != zeros:
            out += [a[0] + r for r in split(a[1:], nines)]
            a = str(int(a[0]) + 1) + zeros
        if b[1:] != nines:
            tail = [b[0] + r for r in split(zeros, b[1:])]
            b = str(int(b[0]) - 1) + nines
        if a[0] <= b[0]:
            out.append((a[0] if a[0] == b[0] else f"[{a[0]}-{b[0]}]") + "[0-9]" * (len(a) - 1))
        return out + tail

    alts = []
    for n in range(len(str(lo)), len(str(hi)) + 1):
        a, b = max(lo, 10 ** (n - 1) if n > 1 else 0), min(hi, 10**n - 1)
        if a <= b:
            alts += split(str(a), str(b))
    return g(*alts)


def port_except(default: int) -> str:
    """A port 0..=65535 other than the scheme's default, which serializers drop."""
    return g(number_range(0, default - 1), number_range(default + 1, 65535))


def not_special(words: list, first: bool = True) -> str:
    """Every scheme `[a-z][a-z0-9+.-]*` except `words`; I-Regexp has no lookahead."""
    letters = [chr(c) for c in range(ord("a"), ord("z") + 1)]
    rest = letters + [chr(c) for c in range(ord("0"), ord("9") + 1)] + list("+.-")
    heads = sorted({w[0] for w in words if w})
    alts = [] if first or "" in words else [""]
    others = sorted(set(letters if first else rest) - set(heads))
    if others:
        alts.append(char_class(set(others)) + char_class(set(rest)) + "*")
    for c in heads:
        alts.append(c + not_special([w[1:] for w in words if w and w[0] == c], False))
    return g(*alts)


FORBIDDEN_HOST = " #/:<>?@[\\]^|"
UPPER = "".join(chr(c) for c in range(ord("A"), ord("Z") + 1))
url_domain = chars(FORBIDDEN_HOST + "%" + UPPER) + "+"  # after domain-to-ASCII: lowercase, punycode
url_opaque_host = chars(FORBIDDEN_HOST) + "+"
url_ipv6 = r"\[[0-9a-f:]+\]"
url_userinfo_ch = chars(' "#<>?^`{}/:;=@[\\]|')
url_userinfo = g(f"{url_userinfo_ch}+(:{url_userinfo_ch}+)?", f":{url_userinfo_ch}+") + "@"
url_segment = chars(' "#<>?^`{}/')  # path percent-encode set
url_segment_special = chars(' "#<>?^`{}/\\')  # special schemes read "\\" as "/"
url_query = chars(' "#<>')
url_query_special = chars(' "#<>\'')
url_fragment = chars(' "<>`')
url_port = number_range(0, 65535)
DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}
url_tail_special = f"([?]{url_query_special}*)?(#{url_fragment}*)?"
url_tail = f"([?]{url_query}*)?(#{url_fragment}*)?"
url_scheme = not_special(list(DEFAULT_PORTS) + ["file"])
URL = "|".join(
    [
        f"{scheme}://({url_userinfo})?{g(url_domain, url_ipv6)}(:{port_except(d)})?(/{url_segment_special}*)+{url_tail_special}"
        for scheme, d in DEFAULT_PORTS.items()
    ]
    + [
        f"file://{g(url_domain, url_ipv6)}?(/{url_segment_special}*)+{url_tail_special}",
        f"{url_scheme}://(({url_userinfo})?{g(url_opaque_host, url_ipv6)}(:{url_port})?)?(/{url_segment}*)*{url_tail}",
        f"{url_scheme}:" + g("/", f"/{url_segment}+(/{url_segment}*)*", f"/[.](/{url_segment}*)+") + url_tail,
        f"{url_scheme}:({chars('/?#', space=True)}{chars('?#', space=True)}*)?{url_tail}",
    ]
)

# Vectors: serializations a URL parser writes, and strings it never writes.
VALID_URL = [
    "https://example.com/",
    "https://shop.example/?filter[size]=m|l",
    "https://a.example/p|q[x]?a`b{c}^#f{|}#g",
    "https://a.example/%zz",
    "http://[::1]:8080/a",
    "http://127.0.0.1/",
    "https://xn--bcher-kva.example/",
    "wss://h:8443/x?y#z",
    "ftp://user:pw@ftp.example/f.txt",
    "file:///etc/hosts",
    "file://server/share/x",
    "mailto:a b@example.com",
    "data:text/plain,a b",
    "urn:isbn:0451450523",
    "foo://h",
    "foo://H:80/p\\q",
    "foo:/.//p",
    "foo:/a/b",
    "git+ssh://git@example.com/r.git",
]
INVALID_URL = [
    "https://example.com",
    "HTTPS://example.com/",
    "https://Example.com/",
    "https://example.com:443/",
    "http://example.com:080/",
    "https://b\u00fccher.example/",
    "https://a.example/ b",
    "https://a.example/a\\b",
    "https://a.example/{",
    "https://a.example/^",
    "http:example.com",
    " https://a.example/",
    "foo://h:65536/",
    "1a:x",
    "",
]



def quote(p: str) -> str:
    """Return p as a NOVA quoted string."""
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def pattern(p: str, prefix: str = "string") -> str:
    """Return a string type constrained by the I-Regexp p."""
    return f"{prefix} @pattern({quote(p)})"


# (name, documentation, type), sorted by name like canonical text.
TYPES = [
    ("CountryCode", "ISO 3166-1 alpha-2 country code, by shape only. The ISO list changes, so std does not enumerate it.", pattern("[A-Z]{2}")),
    ("CurrencyCode", "ISO 4217 currency code, by shape only. The ISO list changes, so std does not enumerate it.", pattern("[A-Z]{3}")),
    ("E164", 'ITU-T E.164 telephone number: "+", then 2 to 15 digits, no leading zero. Syntax only.', pattern("[+][1-9][0-9]{1,14}")),
    ("Email", 'HTML "valid e-mail address": ASCII only, case preserved. RFC 6531 addresses are out of scope.', pattern(EMAIL)),
    # Inside, no control character (C0, C1 and so NEL) and no line or paragraph separator.
    # Format characters stay allowed: emoji sequences need ZWJ, and right-to-left text needs bidi marks.
    ("Name", "Trimmed single-line text without control characters. Follows the Unicode version of the implementation.", pattern(f"{VISIBLE}([^\\p{{Cc}}\\p{{Zl}}\\p{{Zp}}]*{VISIBLE})?")),
    ("NonBlank", "Text with at least one visible character; may span lines. Follows the Unicode version of the implementation.", pattern(f"(.|\\n|\\r)*{VISIBLE}(.|\\n|\\r)*")),
    ("Port", "TCP or UDP port number.", "int @range(0..65535)"),
    ("PortablePath", 'Relative path with "/" separators and POSIX portable file names. Windows reserved names (CON, NUL, ...) are not checked.', pattern(f"{PATH_SEGMENT}(/{PATH_SEGMENT})*", "string @len(1..1024, utf8)")),
    ("SemVer", 'Semantic Versioning 2.0.0 version, without a leading "v".', pattern(SEMVER)),
    ("Sha256Hex", "SHA-256 digest as 64 lowercase hex digits.", pattern("[0-9a-f]{64}")),
    ("Uri", "RFC 3986 absolute URI (section 3). Not a WHATWG URL: no whitespace stripping, no IDNs in Unicode form.", pattern(URI)),
    ("UriReference", "RFC 3986 URI reference (section 4.1): absolute or relative.", pattern(URI_reference)),
    ("Url", "WHATWG URL Standard serialization: what a URL parser writes back, ASCII with a lowercase scheme. Neither contains nor is contained in Uri (proposal 0011).", pattern(URL)),
    ("Urn", 'RFC 8141 URN, assigned name only (no r-, q- or f-components). Lowercase "urn:" only.', pattern(URN)),
    ("Uuid", "RFC 9562 UUID in lowercase hex with hyphens. Any version and variant, nil and max included.", pattern("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")),
]


def novs() -> str:
    """Return the text of std.novs."""
    out = [
        "# The NOVA standard library of types (proposal 0008). Implementations bundle",
        "# every released version and never fetch it. A fix to a type is a new breaking version (§6.5).",
        "# Generated by std.py: edit that script, not this file.",
        f"@schema novafile.dev/std@{VERSION}",
    ]
    for name, doc, ty in TYPES:
        out += ["", f"# {doc}", f"type {name} = {ty}"]
    return "\n".join(out) + "\n"


# Accept and reject vectors per type, for the conformance suite.
VECTORS = {
    "Uuid": (["0f8fad5b-d9cb-469f-a165-70867728950e", "00000000-0000-0000-0000-000000000000", "ffffffff-ffff-ffff-ffff-ffffffffffff"],
             ["0F8FAD5B-D9CB-469F-A165-70867728950E", "{0f8fad5b-d9cb-469f-a165-70867728950e}", "urn:uuid:0f8fad5b-d9cb-469f-a165-70867728950e", "0f8fad5bd9cb469fa16570867728950e"]),
    "Uri": (VALID_URI, INVALID + VALID_REF_ONLY[:4]),
    "UriReference": (VALID_URI + VALID_REF_ONLY, INVALID),
    "Url": (VALID_URL, INVALID_URL),
    "Urn": (["urn:isbn:0451450523", "urn:ietf:rfc:2648", "urn:example:a123,z456/x%2F"], ["URN:isbn:1", "urn:a:b", "urn:-x:y", "urn:isbn:", "urn:x:%zz"]),
    "Email": (["ada@example.org", "a.b+tag@sub.example.co", "x@localhost"], ["ada", "@example.org", "ada@", "ada@-x.org", "ad a@example.org", "ada@ex_ample.org"]),
    "E164": (["+4930123456", "+12", "+123456789012345"], ["030123456", "+0123", "+1", "+1234567890123456", "+49 30 123"]),
    "NonBlank": (["a", " a ", "\u200bx", "line\nnext"], ["", " ", "\u00a0\u3000", "\n\t", "\u200b\ufeff"]),
    "Name": (["Ada", "Ada Lovelace", "\u00c9mile"], ["", " Ada", "Ada ", "Ada\nLovelace", "\u200dAda", "Ada\u0085Lovelace", "Ada\u2028Lovelace", "Ada\u2029Lovelace", "Ada\u001bLovelace", "Ada\tLovelace"]),
    "PortablePath": (["a", ".github/workflows/ci.yml", "src/lib.rs", "a_b-c.d"], ["/etc/passwd", "../x", "a//b", "a/./b", "-rf", "C:/x", "a\\b", "a.", "a:b", "a b"]),
    "SemVer": (["1.0.0", "0.0.4", "1.2.3-alpha.1+build.5", "10.20.30-rc.1"], ["1.0", "01.0.0", "1.0.0-01", "v1.0.0", "1.0.0+"]),
    "Sha256Hex": (["0" * 64], ["0" * 63, "A" * 64]),
    "CountryCode": (["DE", "US"], ["de", "DEU"]),
    "CurrencyCode": (["EUR"], ["eur", "EU"]),
}


def conformance(root: "Path") -> None:
    """Write the conformance case schema/std below the conformance root."""
    case = root / "schema" / "std"
    (case / "valid").mkdir(parents=True, exist_ok=True)
    (case / "invalid").mkdir(parents=True, exist_ok=True)
    for old in (case / "invalid").glob("*.nova"):
        old.unlink()
    fields = "\n".join(f"  {n.lower()}?: list<std.{n}>" for n in VECTORS)
    (case / "schema.novs").write_text(
        "# Generated by spec/meta/std.py: accept and reject vectors of the standard library.\n"
        f"@import novafile.dev/std@{VERSION} as std\n@root Doc\n\nrecord Doc:\n{fields}\n"
    )
    valid = "".join(f"{n.lower()}:\n" + "".join(f"  - {qv(v)}\n" for v in ok) for n, (ok, _) in VECTORS.items())
    (case / "valid" / "all.nova").write_text(valid)
    for n, (_, bad) in VECTORS.items():
        for i, v in enumerate(bad):
            (case / "invalid" / f"{n.lower()}-{i}.nova").write_text(f"{n.lower()}: [{qv(v)}]\n")


def qv(v: str) -> str:
    """Return v as a NOVA quoted string."""
    out = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    # Other control characters and line separators may not appear raw in a quoted string.
    out = "".join(f"\\u{{{ord(c):X}}}" if ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or c in "\u2028\u2029" else c for c in out)
    return '"' + out + '"'


if __name__ == "__main__":
    if "--conformance" in sys.argv:
        from pathlib import Path

        conformance(Path(__file__).parent.parent / "conformance")
        sys.exit(0)
    if "--check" in sys.argv:
        n = check()
        print("ok" if n == 0 else f"{n} failures")
        sys.exit(1 if n else 0)
    from pathlib import Path

    Path(__file__).with_name("std.novs").write_text(novs())
