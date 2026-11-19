# NOVA — Notation for Objects, Values & Agents

**Specification, version 0.1 (draft)**
Status: working draft, accompanied by a Rust reference implementation at <https://github.com/novafile/nova>.
License: this specification is licensed under the Apache License, Version 2.0 (`Apache-2.0`). The examples in it — every code block in this document and in the proposals, and the files in [`examples/`](examples/) — are dedicated to the public domain under CC0 1.0 (`CC0-1.0`), as are the conformance test vectors, so they can be copied into any project without conditions. The meta-schema (§6.8) is Apache-2.0, like this document.

---

## Contents

0. [Conventions](#0-conventions)
1. [Overview and design principles](#1-overview-and-design-principles)
2. [The value model](#2-the-value-model)
3. [Representations and fidelity](#3-representations-and-fidelity)
4. [Text syntax](#4-text-syntax)
5. [Binary encoding](#5-binary-encoding)
6. [Schemas](#6-schemas)
7. [Paths, queries and patches](#7-paths-queries-and-patches)
8. [The agent interaction model](#8-the-agent-interaction-model)
9. [Templates and composition](#9-templates-and-composition)
10. [Token-aware representation selection](#10-token-aware-representation-selection)
11. [Interoperability mappings](#11-interoperability-mappings)
12. [Security considerations](#12-security-considerations)
13. [Conformance](#13-conformance)
14. [Reference implementation](#14-reference-implementation)
- [Appendix A — Grammar summary](#appendix-a--grammar-summary)
- [Appendix B — Comparison with existing formats](#appendix-b--comparison-with-existing-formats)
- [Appendix C — Open questions and future work](#appendix-c--open-questions-and-future-work)
- [Appendix E — Conventions and lints](#appendix-e--conventions-and-lints)

---

## 0. Conventions

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, MAY and OPTIONAL are to be interpreted as described in RFC 2119 and RFC 8174 when, and only when, they appear in all capitals.

*Non-normative* sections and notes explain intent; they impose no requirements.

Grammar fragments use an EBNF variant: `"x"` is a literal, `[a]` is optional, `a*` is zero or more, `a+` is one or more, `a | b` is alternation, and `'a'..'z'` is a character range. `SP` is U+0020, `NL` is U+000A (optionally preceded by U+000D).

---

## 1. Overview and design principles

NOVA, the **Notation for Objects, Values & Agents**, is **one precise semantic model with several interchangeable representations**, each optimized for a different consumer. The name states its scope:

- *Objects:* structured documents that people write and read.
- *Values:* a typed model with exact equality and canonical revisions, which machines exchange.
- *Agents:* projections, conditional patches and provenance, so that automated editors read and change parts of a document safely.

The representations, by consumer:

| Consumer | Representation | Optimized for |
| --- | --- | --- |
| People editing configuration | Human text (§4, profile *human*) | Readability, diffs, comments |
| LLMs reading data | Compact text (§4.9, profile *compact*) | Few tokens, explicit structure |
| Services, storage | Binary (§5) | Size, speed, streaming |
| Agents changing state | Queries and patches (§7) | Reading and writing *parts* of a document |
| Authors reusing structure | Templates (§9) | Composition without text templating |

Design principles:

1. **Semantics first.** Every representation maps to the same value model (§2). Converting between representations never changes a value unless the conversion is explicitly declared lossy (§11).
2. **No surprising conversions.** The only bare words with special meaning are `true`, `false`, `null`, and tokens that match the strict number grammar (§4.5). Everything else is a string. Richer types are written explicitly or supplied by a schema (§6.3).
3. **Partial information is a first-class concept.** Agents read projections (§7.3) and write conditional, atomically applied patches (§7.4) rather than whole documents.
4. **Data is not code.** Data documents contain no expressions, references or directives that execute. Composition lives in a separate, total template layer (§9) that is rendered *before* any consumer sees the data.
5. **Determinism.** Every value has exactly one canonical binary encoding and one canonical text form, from which equality, ordering and revisions are derived (§2.12–2.13).
6. **Reuse proven techniques.** The binary encoding borrows varints, zigzag encoding and length prefixes from Protobuf and CBOR; tables borrow from TOON and CSV; patches borrow from JSON Patch. Novelty is reserved for where existing formats fall short.

---

## 2. The value model

A NOVA **value** is one of the following kinds. The model is a tree: there are no references, aliases or cycles.

| Kind | Description |
| --- | --- |
| `null` | No value: a field or element that is present but holds nothing. Distinct from an absent field (§2.10). |
| `bool` | `true` or `false`. |
| `int` | A mathematical integer. |
| `float` | An IEEE 754 binary64 number. |
| `decimal` | An exact base-10 number. |
| `rational` | An exact fraction. |
| `string` | A sequence of Unicode scalar values. |
| `bytes` | A sequence of octets. |
| `timestamp` | An instant on the UTC time line. |
| `duration` | A signed, exact span of time. |
| `list` | An ordered sequence of values. |
| `tuple` | A fixed-length ordered sequence of values; distinct from `list`. |
| `set` | An unordered collection of distinct values. |
| `record` | A collection of string-keyed fields with unique keys. |
| `map` | A collection of entries with unique keys of any kind. |
| `variant` | A tagged value: a tag and an optional payload. |

### 2.1 Integers

An `int` is an arbitrary mathematical integer. Implementations MUST support at least the range [−2^63, 2^64 − 1] and MUST reject (not truncate or round) integers outside their supported range. The reference implementation supports the signed 128-bit range.

### 2.2 Floats

A `float` is an IEEE 754 binary64 value, including −0.0, +∞, −∞ and NaN.

- `+0.0` and `−0.0` are **distinct** values.
- All NaN values are **equal** to each other and are canonicalized to the bit pattern `0x7FF8000000000000`.
- `int` and `float` are distinct kinds: `1` ≠ `1.0`.

### 2.3 Decimals

A `decimal` is `c × 10^e` with integer coefficient `c` and integer exponent `e` (32-bit signed). Decimals are **normalized**: `c` has no trailing decimal zeros, and zero is `0 × 10^0`. Hence `1.50` and `1.5` are the same value. Scale is not preserved; schemas that need a fixed scale constrain it separately. Implementations MUST support at least 38 significant digits.

### 2.4 Rationals

A `rational` is `n / d` with integers `n` and `d`, `d > 0`, normalized to lowest terms (`gcd(|n|, d) = 1`; zero is `0/1`). Hence `2/4` and `1/2` are the same value. `n/1` is still a rational, distinct from the integer `n`. Implementations MUST support numerators and denominators of at least 64 bits; the reference implementation supports signed 128-bit components.

> *Note (non-normative).* Rationals exist so that exact ratios — aspect ratios, sampling rates, probabilities, musical intervals, `22/7` — survive serialization. Converting a rational to a float is lossy and is therefore never performed implicitly (§6.3). Language bindings MAY expose rationals as a native float when the application opts in to that loss.

### 2.5 Numeric kinds are distinct

`int`, `float`, `decimal` and `rational` are separate kinds. Values of different numeric kinds are never equal (`1`, `1.0`, `@decimal("1")` and `1/1` are four different values), and no implementation performs implicit numeric conversion. The only conversions are the lossless ones that a schema requests (§6.3).

### 2.6 Timestamps

A `timestamp` is an instant: whole seconds since 1970-01-01T00:00:00Z plus nanoseconds in [0, 10^9). Leap seconds are not represented. Implementations MUST support years 0001–9999 with nanosecond precision.

A timestamp carries **no time zone or offset**. An offset in the text form (§4.8) is presentation and is applied when parsing; it is not preserved.

### 2.7 Durations

A `duration` is a signed number of nanoseconds. There are no calendar units: a day is exactly 86 400 seconds. Implementations MUST support magnitudes up to (2^63 − 1) seconds.

### 2.8 Strings and bytes

A `string` is a sequence of Unicode scalar values (surrogate code points are excluded). Strings are compared by code point; **no Unicode normalization** is performed by NOVA. A `bytes` value is an arbitrary octet sequence.

### 2.9 Lists, tuples and sets

A `list` is ordered and may contain duplicates. A `tuple` is ordered with a fixed length; `()` and `(x,)` are valid tuples. A list and a tuple with the same elements are different values. A `set` contains no two equal elements (§2.12); duplicates MUST be rejected when constructing, parsing or decoding a set. Set element order is not part of the value.

### 2.10 Records

A `record` maps string keys to values. Keys MUST be unique; duplicate keys MUST be rejected by every parser and decoder. **Field order is not part of the value**: two records with the same fields are equal regardless of order. Implementations SHOULD retain the order in which fields were written so that human-oriented output follows the author's order.

A field that is **absent** and a field that is present with the value `null` are different records: `{}` and `{x: null}` are not equal, and every representation (§3), the JSON mapping (§11.1) and patches (§7.4: `remove` versus setting `null`) keep them apart.

### 2.11 Maps and variants

A `map` maps keys of any kind to values. Keys MUST be unique (by §2.12 equality). Entry order is not part of the value.

A `variant` is a tag — a name matching `[A-Za-z_][A-Za-z0-9_-]*` — and an optional payload value. `!active` and `!failed("disk full")` are variants. A schema's `enum` (§6.1) constrains which tags and payloads are permitted. Variants express both C-style enums (no payload) and tagged unions (payload).

### 2.12 Equality and ordering

Two values are **equal** if and only if their canonical binary encodings (§5.2) are byte-for-byte identical. Consequently:

- values of different kinds are never equal;
- record, set and map equality ignore order;
- NaN equals NaN; `0.0` does not equal `-0.0`.

The **canonical order** of values is the lexicographic order of their canonical encodings. It is used to order set elements and map keys in canonical form. It is a total order, but it is not numeric order and SHOULD NOT be presented to users as one.

### 2.13 Revisions

The **revision** of a value is the SHA-256 digest of its canonical binary encoding, written `sha256:` followed by 64 lowercase hexadecimal digits. Revisions identify document states for optimistic concurrency (§7.5). Where a revision is given as a precondition it MAY be abbreviated to a prefix of at least 8 hexadecimal digits.

> *Note.* A revision covers values only. Comments, formatting and field order do not affect it, so reformatting a document never invalidates a pending patch.

---

## 3. Representations and fidelity

A **representation** maps values to octets and back. NOVA defines:

| Representation | Section | Self-describing | Needs schema |
| --- | --- | --- | --- |
| Text, profile *human* | §4 | yes | no |
| Text, profile *compact* | §4.9 | yes | no |
| Text, profile *canonical* | §4.10 | yes | no |
| Binary value encoding and frames | §5 | yes | no |
| Positional text | §4.12 | no | yes |

Conversions are classified by **fidelity level**:

- **Value-preserving** — the decoded value equals the original (§2.12). All conversions among NOVA representations MUST be value-preserving.
- **Document-preserving** — additionally preserves comments, field order, blank lines, and the author's choice among equivalent spellings. This applies to tools that edit text in place (formatters, refactoring tools, schema migrations). A conforming *editor* (§13) MUST be document-preserving for edits it did not intend to make.

**Comment attachment.** To carry comments through a re-rendering, a document-preserving formatter attaches each comment to a path:
- A comment that follows code on the same line *trails* the innermost line-level construct (block entry, list item or table row) that starts on that line.
- Any other comment *leads* the next line-level construct; when several start at the same place, it leads the outermost (the list item rather than its first field).
- Comments before the body stay with the directives, and comments after the last entry stay at the end.
- A comment inside a value that is re-rendered on a single line (for example, a multi-line flow list) moves to that entry's line.

**Patching text.** A document-preserving patch host (§7.5) SHOULD apply each operation as a minimal edit of the source text at the target's span:
- replace the value text in place when it stays on one line;
- re-render only the affected entry otherwise, carrying over the comments inside it;
- insert new fields after the last sibling, and new list items at the requested position;
- delete removed entries together with the comment lines directly above them.

The result MUST parse to the same value that value-level application produces. Hosts SHOULD verify this, and fall back to a comment-preserving re-rendering if it does not.

The canonical form of a value preserves the value and nothing else. Comments are presentation metadata: they belong to a document, not to its value, and are discarded by value-preserving conversions such as text → binary.

---

## 4. Text syntax

### 4.1 Encoding and lines

A text document is UTF-8. A leading byte-order mark is ignored. Lines end with LF or CRLF. Tab characters MUST NOT appear in indentation; they MAY appear inside strings and comments, and as inline whitespace between tokens.

A **comment** begins with `#` at a token boundary — at the start of a line (after indentation), after whitespace, or after a complete flow value — and extends to the end of the line. Within a plain scalar (§4.4), only `#` preceded by whitespace starts a comment.

### 4.2 Documents and directives

```
document  = directive* body
directive = "@" name [SP argument] NL        ; at column 1, before the body
```

A directive is `@` immediately followed by a name and then whitespace or end of line. (`@timestamp(...)` is a typed literal, not a directive, because a `(` follows the name.)

Directives defined for **data documents**:

| Directive | Meaning |
| --- | --- |
| `@nova MAJOR.MINOR` | The NOVA language version the document is written in. OPTIONAL. If present it MUST be the first directive, and readers MUST reject versions they do not support (§13.1). |
| `@schema <ref>` | The schema version the data was written against: `name@MAJOR.MINOR.PATCH`, optionally followed by `#` and a fingerprint (§6.6–6.7), e.g. `infrastructure@1.2.0#8c21a0f3d5e6b7c8`. Parsers MUST NOT fetch it. A validator that is given a schema MUST check the reference against it (§6.7). |
| `@revision <rev>` | The revision of the document the body was taken from (used in query responses, §7.3). |
| `@scope <path>` | The location within that document the body was taken from (§7.3). |
| `@envelope <kind>` | Marks an agent-result envelope (§8.2). |
| `@mode positional` | The body is in the positional profile (§4.12). |
| `@compat json` \| `yaml` \| `toml` | The document mirrors a contract in that format: names are dictated externally, and the data should stay representable in it. Tools SHOULD NOT apply naming conventions to such documents, and SHOULD report values the format cannot represent (Appendix E). |

Template documents (§9), patch documents (§7.4) and query documents (§7.3) define their own directives. Directive names beginning with `x-` are reserved for extensions and MUST be ignored by implementations that do not understand them. Any other unknown directive MUST be rejected.

The **body** is one of:

- empty — the document's value is the empty record `{}`;
- a block record (§4.3), if the first line is a key;
- a block list (§4.3), if the first line starts with `- `;
- a top-level table (§4.9), if the first line is `[N]{...}:`;
- a single flow value (§4.7) on its own.

Content after the body is an error.

### 4.3 Block structure

Block structure is expressed by indentation. **Indentation is fixed by the grammar**: the children of a line are indented by *exactly two spaces* more than that line. Any other indentation is an error. There is no context-dependent interpretation of indentation.

**Block records.** Each line is an entry:

```
key: value              # value on the same line (§4.6)
key:                    # value is the indented block below
  nested: 1
key[N]{a,b}:            # a table (§4.9)
  1, 2
```

Keys are bare identifiers `[A-Za-z_][A-Za-z0-9_-]*` or quoted strings (§4.6). The key MUST be followed by `:` and then a space, a comment, or the end of the line. Duplicate keys are an error.

A key followed by nothing MUST be followed by an indented block; writing `key:` with no value and no block is an error (write `null`, `{}` or `[]` explicitly).

**Block lists.** Each item starts with `- ` at the list's indentation:

```
services:
  - id: auth            # an item that is a record: first field on the dash line,
    port: 8080          #   further fields indented two spaces past the dash
  - plain string item
  - [1, 2]              # a flow value
  -                     # a nested block on the following lines
    - nested list item
```

A list item MUST NOT start another list item on the same line (`- - x`); use a nested block or a flow list.

### 4.4 Plain scalars and token classification

After `key: ` or `- `, a value that does not begin with one of `" [ { ( @ ! $ |` is a **plain scalar**: the rest of the line, up to a comment, with trailing whitespace removed.

A plain scalar MUST NOT

- begin with any **reserved character** ``! " # $ % & ' * , : < = > ? @ [ \ ] ^ ` { | } ~ ( )``,
- begin with `...` or with `- `, or be exactly `-`,
- contain `: ` (colon followed by space),
- end with `:`,
- contain control characters other than tab.

Violations are errors that ask the author to quote the string. This removes the most common ambiguities of YAML (`a: b: c`, `key: - x`).

Every **bare token** — a plain scalar or a flow word (§4.7) — is classified by exactly these rules:

1. `true`, `false` → `bool`; `null` → `null`.
2. A token that matches the number grammar (§4.5) exactly → `int`, `float` or `rational`.
3. Anything else → `string`.

There are no other implicit conversions. `yes`, `NO`, `on`, `1.2.3`, `08080` and `2026-11-17T16:00:00Z` are all strings. A schema MAY resolve a string into a richer type (§6.3); without a schema, write a typed literal (§4.8).

> *Rationale (non-normative): why `null` and not `none`.* Languages such as Rust replaced null with an option type, and a keyword like `none` would echo that. NOVA keeps `null` for three reasons:
>
> - **`none` is common string data; `null` is not.** Configuration is full of `compression: none`, `auth: none`, `display: none`, and enums with a `none` variant, which a schema resolves from the string `none` (§6.3). A `none` keyword would silently turn all of them into a different kind. That is the class of surprise principle 2 (§1) rules out, the same one that turns `NO` into `false` in YAML.
> - **Writers type `null`.** JSON, YAML and their tooling, and the people and models that learned from them, spell the empty value `null`. Under a `none` keyword, `x: null` would become the *string* `"null"` without any error.
> - **One spelling.** Accepting both words would keep the first problem and give every value two spellings, against the canonical form (§4.10).
>
> What Rust gained from `Option` is a guarantee at the type level, and NOVA's schemas give the same guarantee: `null` is valid only where a type says so. `T` admits no `null`, and `T?` is the counterpart of `Option<T>` (§6.1). The Rust binding maps `None` to `null` (§11.3). The word stays; what makes it safe is the schema.

### 4.5 Numbers

```
int      = ["-"] ("0" | '1'..'9' digit*)
float    = int ( frac [exp] | exp )
frac     = "." digit+
exp      = ("e" | "E") ["+" | "-"] digit+
rational = int "/" '1'..'9' digit*
```

- No leading `+`, no leading zeros, no leading or trailing `.`, no digit separators, no hexadecimal.
- `-0` is the integer 0; `-0.0` is the float −0.0.
- An `int` outside the implementation's range is an error.
- A `float` literal whose value overflows to infinity is an error. Infinities and NaN are written `@float("inf")`, `@float("-inf")`, `@float("nan")`.
- A `rational` is normalized on parsing (`2/4` reads as `1/2`). `1/0`, `1/02` and `1/-2` do not match the grammar and are therefore strings.

> *Note.* Because `11/17` matches the rational grammar, it is a rational, not a string. Authors who mean the string must quote it; writers quote such strings automatically. This is the same rule that makes `8080` an integer.

### 4.6 Strings

**Quoted strings** use double quotes and the JSON escapes `\" \\ \/ \b \f \n \r \t \uXXXX` (with surrogate pairs), plus `\u{X…}` (1–6 hex digits) and `\$` (a literal `$`). Raw control characters, including line breaks, MUST NOT appear inside quoted strings.

**Block strings** hold multi-line text:

```
script: |               # keep: content plus exactly one final newline
  echo "hello"
    indented line
notes: |-               # strip: no final newline
  first
  second
```

The content lines are indented exactly two spaces more than the line holding `|`; that indentation is removed and everything after it, including further spaces, `#` and quotes, is content. A whitespace-only line shorter than the content indentation is an empty content line. The block ends at the first non-blank line with less indentation. Trailing empty lines are discarded. `|` appends one `\n` to non-empty content; `|-` appends nothing.

Strings that cannot be represented this way — for example, ones with several trailing newlines — are written quoted.

### 4.7 Flow values

Flow values can appear anywhere a value can. Inside brackets, newlines and comments are whitespace, so flow values can span lines. Every continuation line of a multi-line flow value MUST be indented deeper than the line on which the value starts. The only exceptions are lines that begin with a closing bracket (`]`, `}`, `)`) and comment lines.

```
[1, two, "three"]              list          (trailing comma allowed)
{id: auth, "odd key": 1}       record
(1, 2)  (1,)  ()               tuples        ((x) without a comma is an error)
@set[a, b]                     set
@map{1 => one, (1, 2) => pair} map           (keys are any flow value)
!active  !failed("disk full")  variants      (payload in parentheses)
```

A **flow word** is a bare token in flow context. It ends at whitespace, at any of `, [ ] { } ( ) "`, or at a `:` that is followed by whitespace, a delimiter or the end of input. It MUST NOT begin with a reserved character (§4.4) or with `...`. Flow words are classified as in §4.4; for example `ghcr.io/example/auth:v2` is a single string.

Record keys in flow context are identifiers or quoted strings, followed by `:`.

### 4.8 Typed literals

| Literal | Kind | Argument |
| --- | --- | --- |
| `@timestamp("2026-11-17T16:00:00Z")` | timestamp | RFC 3339 date-time: `YYYY-MM-DDTHH:MM:SS[.F{1,9}](Z\|±HH:MM)`. Uppercase `T` and `Z`. |
| `@duration("1h30m")`, `@duration("PT1H30M")` | duration | NOVA notation `-?(Nd)?(Nh)?(Nm)?(N[.F{1,9}]s)?` — at least one component, units in this order — or ISO 8601 notation (below). |
| `@decimal("12.50")` | decimal | `-?D+(.D+)?([eE][+-]?D+)?` |
| `@rational("22/7")` | rational | as §4.5 |
| `@bytes("AP8H")` | bytes | Standard base64 with padding (RFC 4648 §4). |
| `@float("nan")` | float | `nan`, `inf`, `-inf`, or a number. |

The argument MUST be a quoted string literal.

**ISO 8601 durations.** Wherever a duration is parsed — typed literals, schema resolution (§6.3), language bindings — implementations MUST also accept the ISO 8601 form restricted to exact units:

```
iso-duration = ["-"] "P" [n "W"] [n "D"] ["T" [n "H"] [n "M"] [n [("." | ",") F{1,9}] "S"]]
```

- At least one component MUST be present. `T` MUST be followed by at least one time component.
- Only seconds may carry a fraction.
- Designators are uppercase.
- `W` is 7 days and `D` is 86 400 seconds.
- Years (`Y`) and months (`M` before `T`) MUST be rejected, because their length depends on the calendar and a NOVA duration is exact. (Calendar periods such as "1 month" are a different concept from durations; a schema can model them as a record.)

Examples: `PT1H30M` = `1h30m`, `P30D` = `30d`, `P1W` = `7d`, `PT0.5S` = `0.5s`, `-PT90M` = `-1h30m`.

Writers always emit the canonical NOVA notation (§4.10). The reference implementation also offers an ISO rendering (`Duration::to_iso8601`) for interoperability.

### 4.9 Tables

A list of records can be written as a table. Cells are flow values, so a field may hold any value, including lists, records and variants; the compact profile (§4.10) uses tables only for scalar fields. This is the core of the compact profile, and is also allowed in human text.

```
services[2]{id,image,port,replicas,enabled}:
  auth, ghcr.io/example/auth:v2, 8080, 3, true
  api,  ghcr.io/example/api:v5,  3000, 5, true
```

- The header is `key[N]{col, …}:` where `N` is the exact row count. Columns are identifiers or quoted strings and MUST be unique.
- Rows follow, indented two spaces past the header. There MUST be exactly `N` rows; a missing or extra row is an error, which catches truncated LLM output.
- Each row is a comma-separated sequence of cells, one per column. A cell is a flow value, so commas, quotes and newlines in text require quoting, exactly as elsewhere. **Rows are never split on raw commas.**
- An **empty cell** means the field is *absent* from that row's record. Write `null` for a present null field.
- Each row denotes a record whose fields are the non-empty cells, in column order.
- At the top level, the header is `[N]{col, …}:`.

### 4.10 Writer profiles

Writers MUST produce text that parses to a value equal to the input. The reference writer defines three profiles.

- **human** — block layout; fields in stored order; short scalar lists in flow form; multi-line strings as block strings; no tables.
- **compact** — like *human*, but a list of at least two records whose field values are all scalars, and that is at least half dense, is written as a table; flow lists use `,` without a space.
- **canonical** — *human* applied after sorting record keys by UTF-8 bytes and ordering set elements and map keys canonically (§2.12). Two equal values have byte-identical canonical text.

Canonical scalar spellings, which all writers SHOULD use:

| Kind | Canonical text |
| --- | --- |
| int | Decimal digits, `-` for negatives. |
| float | The shortest digit string that round-trips. Scientific notation (`1e300`, `1e-7`) when the decimal exponent is < −4 or ≥ 16, otherwise positional; the output always contains `.` or `e` (`1.0`). Non-finite values as `@float(...)`. |
| decimal | Positional when 0 ≤ e ≤ 6 (`1500`), or when e < 0 and at most five zeros follow the point (`0.0001`); otherwise `<coefficient>e<exponent>` (`12e-21`). |
| rational | `n/d` in lowest terms (`-22/7`, `2/1`). |
| timestamp | UTC with `Z`; the fraction is omitted when zero, otherwise trailing zeros are trimmed. |
| duration | Largest units first (`d h m s`), zero components omitted, `0s` for zero, fraction trimmed. |
| bytes | Standard base64 with padding. |
| string | A plain scalar / flow word if that spelling re-parses to the same string; otherwise quoted, with the minimal escapes. |

### 4.11 Text streams

A text stream is a sequence of documents separated by lines consisting exactly of `---`. Because block content is indented, and flow continuation lines are indented (§4.7), a `---` line at column 1 can never be part of a document, so streams can be split without parsing. Each document is parsed independently; an error in one document does not prevent reading the others.

### 4.12 Positional profile

The positional profile is an opt-in transport form for peers that share a schema. It omits field names. A positional document is **ordinary NOVA text** — the grammar, escaping and tokenization are exactly those of §4 — whose *meaning* is defined by a schema:

```
@schema infrastructure@1.0.0#baf8ad5c15586601
@mode positional
- production
- eu-central-1
- @timestamp("2026-11-17T16:00:00Z")
- !active
-
  - (auth,ghcr.io/example/auth:v2,8080,3,true,!_)
  - (api,ghcr.io/example/api:v5,3000,5,true,@set[public,edge])
```

- The header MUST contain `@mode positional` and `@schema name@version#fingerprint` (§6.6).
- A reader MUST hold a schema with exactly that fingerprint, and MUST reject the document otherwise. Field order is the whole contract, so even a compatible schema version is not enough.
- The value is first resolved against the schema's `@root` type (§6.3). Then every value of a named record type becomes a tuple of its fields' values in declared order.
- An absent field is written as the reserved unit variant `!_`. The variant tag `_` MUST NOT otherwise appear in a positional document.
- Records of `@open` types that contain unknown fields cannot be written positionally.
- When the root is a record, its tuple is written as a block list (one field per line).
- All other kinds are unchanged.
- Decoding inverts the mapping and MUST validate the result against the schema.

Positional text saves the field names that the compact profile (§4.10) writes once per table, and it also saves them for nested records. The cost is self-description, so it SHOULD NOT be used for storage or for documents that people read.

---

## 5. Binary encoding

### 5.1 Value encoding

Every value is encoded as a one-byte **type tag** followed by a payload.

Notation:

- `varint(u)` — unsigned LEB128, minimal length. Decoders MUST reject non-minimal encodings, for example a trailing `0x00` continuation byte.
- `zigzag(i)` — `(i << 1) XOR (i >> 127)`, which maps signed integers to unsigned ones (0, −1, 1, −2, …).
- `str` — a string payload (§5.3).

| Tag | Kind | Payload |
| --- | --- | --- |
| `0x00` | null | — |
| `0x01` | false | — |
| `0x02` | true | — |
| `0x03` | int | `varint(zigzag(i))` |
| `0x04` | float | 8 bytes, IEEE 754 binary64, big-endian; NaN as `7FF8000000000000` |
| `0x05` | decimal | `varint(zigzag(c))` `varint(zigzag(e))`, normalized (§2.3) |
| `0x06` | string | `str` |
| `0x07` | bytes | `varint(len)` bytes |
| `0x08` | timestamp | `varint(zigzag(seconds))` `varint(nanos)` |
| `0x09` | duration | `varint(zigzag(nanoseconds))` |
| `0x0A` | list | `varint(n)` value×n |
| `0x0B` | tuple | `varint(n)` value×n |
| `0x0C` | set | `varint(n)` value×n |
| `0x0D` | record | `varint(n)` (`str` key, value)×n |
| `0x0E` | map | `varint(n)` (key value, value)×n |
| `0x0F` | unit variant | `str` tag |
| `0x10` | variant with payload | `str` tag, value |
| `0x11` | rational | `varint(zigzag(n))` `varint(d)`, normalized (§2.4) |
| `0x12` | *(reserved for tensors)* | see [proposals/0001-tensors.md](proposals/0001-tensors.md) |
| `0x13` | list of records (record list) | `varint(n)` `varint(k)` `str`×k field names, mode byte, then n rows (§5.3) |

Decoders MUST reject:

- unknown tags;
- truncated input;
- element counts that exceed the remaining input;
- invalid UTF-8;
- duplicate record keys, set elements or map keys;
- non-normalized decimals or rationals;
- out-of-range timestamps or durations;
- nesting deeper than their limit (at least 64; the reference implementation uses 128).

### 5.2 Canonical encoding

The **canonical encoding** of a value is the encoding above with:

- record fields sorted by the UTF-8 bytes of their keys;
- set elements, and map entries by key, sorted by the bytewise order of their canonical encodings;
- no string back-references (§5.3) and no record lists (§5.3a);
- NaN canonicalized.

It is the basis of equality, ordering and revisions (§2.12–2.13).

### 5.3 String payloads and back-references

A string payload starts with `h = varint(...)`:

- if `h` is even, a literal of `h >> 1` UTF-8 bytes follows;
- if `h` is odd, the string is entry `h >> 1` of the **string table**.

The string table is empty at the start of each top-level value. Every **literal** string payload — record keys, string values and variant tags — is appended to it in encoding order, by encoders and decoders alike. An encoder MAY replace any later occurrence of a string with a back-reference, and SHOULD do so only when the reference is shorter than the literal. Repeated record keys in lists of records therefore cost one or two bytes each. Decoders MAY bound the table size; the reference implementation allows 2^20 entries.

### 5.3a Record lists

A list whose elements are all records may be encoded with tag `0x13`. The field names are written once, and each row then carries only its values:

```
record-list = 0x13 varint(n) varint(k) str×k mode row×n
mode        = 0x00 (dense: every row has all k fields)
            | 0x01 (sparse: each row starts with a presence bitmap)
row         = [bitmap: ceil(k/8) bytes] value×(fields present)
```

- Bit *i* of the bitmap (byte `i/8`, bit `i%8`, least-significant first) is set if field *i* is present. Unused high bits MUST be zero.
- Values appear in field-header order. Each value is a full tagged value (§5.1), so a column may mix kinds and may contain nested record lists.
- Field names MUST be unique. They take part in the string table (§5.3) like any other string.
- The decoded value is a `list` of `record`s. Each record's fields are in field-header order.
- Like back-references, record lists are an **encoder choice and never part of the canonical encoding** (§5.2).

The reference encoder uses a record list only when doing so preserves each record's field order — every record's keys follow the shared field order — and when the table is at least half dense. Decoders MUST accept any valid record list.

### 5.4 Frames

A frame wraps one value for transport or storage:

```
frame = magic  "NOVA" (4E 4F 56 41)
        version 0x01
        flags   u8
        [schema: varint(len) UTF-8]        if flags & 0x01
        length  varint
        payload length bytes               (one §5.1 value, exactly)
        [crc32: u32 big-endian]            if flags & 0x04
```

| Flag bit | Meaning |
| --- | --- |
| `0x01` SCHEMA | A schema reference follows (`name@version[#fingerprint]`, §6.7). On a negotiated connection it MAY be omitted. |
| `0x02` CANONICAL | The payload is in canonical form; the receiver can hash it directly. |
| `0x04` CRC32 | A CRC-32 (IEEE 802.3, reflected polynomial `0xEDB88320`) of the payload follows it. |
| `0x08` DEDUPE | The payload may contain back-references. Informational. |
| `0x10` TABLES | The payload may contain record lists (§5.3a). Informational. |

Unknown flag bits and unknown versions MUST be rejected.

### 5.5 Binary streams

A binary stream is a concatenation of frames. A reader in **recovering** mode that encounters a malformed frame MUST report it, then resume at the next occurrence of the magic bytes after the start of the bad frame. Writers that need reliable recovery SHOULD set the CRC32 flag.

---

## 6. Schemas

Schemas are **optional**. Schema-free documents are fully self-describing. A schema adds types, constraints, defaults, stable field identities and evolution rules.

### 6.1 Schema language

Schemas are written in their own small line-oriented language (file extension `.novs`):

```
@schema infrastructure@1.0.0          # name and SemVer 2.0.0 version (§6.7)
@root Infrastructure               # the type of a whole document

type Port = u16 @range(1..65535)   # alias

record Service:
  id: string @key @id(1)
  image: string @len(1..) @id(2)
  port: Port @id(3)
  replicas: u16 @range(0..100) @id(4)
  enabled: bool @id(5) = true      # default
  tags?: set<string> @id(6)        # optional field

enum Status:                       # also: enum Status = active | draining | failed(string)
  active
  draining
  failed(string)                   # variant with a payload

enum Phase:                        # variants may carry stable ids
  pending @id(1)
  running @id(2)
  done(timestamp) @id(3)

record Infrastructure:
  environment: string
  deployed_at: timestamp
  status: Status = !active
  services: Service[]
```

- Definition names start with an uppercase letter. Fields are indented exactly two spaces.
- A field name is an identifier or a quoted string (§4.6), exactly like a record key in a document (§4.3): `"at start": Formula`, `">="?: (Term, Term)`. A field whose name is not an identifier MUST NOT carry `@key`, because keyed selectors (§7.1) name key fields by identifier. Enum variant names remain identifiers, since variant tags are identifiers in the value model (§2.11).
- `@root` takes any type from the table below, for example a definition (`@root Infrastructure`) or a list (`@root Service[]`).
- A field line is `name[?]: type attributes* [= default]`, where the default is a flow value.
- A variant is `name[(type)] attributes*`, on its own line or separated by `|` in the inline form: `enum Phase = pending @id(1) | done(timestamp) @id(2)`. An attribute after the parentheses belongs to the variant; one inside them belongs to the payload type, as in `failed(u8 @range(1..)) @id(3)`.
- `#` starts a comment when it is at the start of a line or preceded by a space, outside quotes.

**Types**

| Syntax | Meaning |
| --- | --- |
| `any` | any value |
| `null` `bool` `float` `decimal` `rational` `string` `bytes` `timestamp` `duration` | the corresponding kind |
| `int` `i8` `i16` `i32` `i64` `u8` `u16` `u32` `u64` | integers, range-limited by name |
| `list<T>`, `T[]` | list |
| `set<T>` | set |
| `map<K, V>` | map |
| `(A, B, …)` | tuple |
| `T?` | `T` or `null` (nullable) |
| `A \| B \| …` | a union: a value of any of the member types (below) |
| `Name` | a `record`, `enum` or `type` definition |

`name?:` (an optional field, which may be absent) and `T?` (a nullable type, where the field is present but may be `null`) are independent. Together they describe the four shapes a field can take, including the three states JSON can express:

| Declaration | Absent | `null` | A value |
| --- | --- | --- | --- |
| `x: T` | no | no | yes |
| `x?: T` | yes | no | yes |
| `x: T?` | no | yes | yes |
| `x?: T?` | yes | yes | yes |

A binding whose native type has only two states (Rust's `Option<T>`) maps to `x?: T?` and chooses one spelling when writing; a binding that must keep all three needs a three-state type.

**Unions.** A union lists two or more member types separated by `|`. It may appear wherever a type may: as a field type, an alias (`type Entry = string | string[]`), a type argument (`list<int | string>`), a tuple element or a variant payload (`failed(string | int)`).
- `|` binds more loosely than everything else in a type: `A | B[]` is `A | list<B>`, and `A | B?` is `A | B` where only `B` is nullable. A list of a union is written `list<A | B>`. Parentheses do not group types; they always denote a tuple.
- A type attribute that follows a member belongs to that member: in `u8 @range(1..) | string @len(1..)` each member has its own constraint. A union as a whole takes no type attributes; field attributes (`@id`, `@deprecated`) on a field line still belong to the field.
- Members are **ordered**: resolution tries them from left to right (§6.3). They are positional and carry no `@id` (§6.5).
- A member that is itself a union (through an alias) behaves as if its members were listed in its place.
- Definitions may refer to each other recursively. An alias that reaches itself without passing through a `list`, `set`, `map`, tuple, `record` or `enum` is a cycle and makes the schema invalid: `type T = list<T> | string` is valid, `type A = B | int` together with `type B = A` is not.

For example, an s-expression-like formula language, where an atom is a list and an operator is a record with one field:

```
type Formula = Atom | And | Not | Eq | AtStart
type Atom = list<string | int>

record And:
  and: Formula[]

record Not:
  not: Formula

record Eq:
  "=": (string | int, string | int)

record AtStart:
  "at start": Formula
```

Records are closed by default, so each single-field record accepts only its own key and the members never overlap.

**Type arguments may carry type attributes**, e.g. `list<u16 @range(1..1024)>` or `map<string @len(1..8), int>`.

**Attributes**

**Numeric comparison** (used by `@range` and by query filters, §7.1) is exact across `int`, `float`, `decimal` and `rational`. Each value is compared as the exact number it denotes — a float as its exact binary fraction — never via binary64 conversion. For example, the float `0.1` (exactly 0.1000000000000000055511151231257827…) is *above* the decimal bound `0.1`, and `9007199254740993` is greater than the float `9007199254740992.0`. NaN satisfies no range. Implementations SHOULD compare orders of magnitude first, so that decimals with extreme exponents do not require huge intermediate integers.

| Attribute | Applies to | Meaning |
| --- | --- | --- |
| `@range(lo..hi)` | numeric types | Inclusive bounds; either side may be omitted. Bounds are exact literals: an integer, a decimal (`0.1`, `1e3`) or a rational (`1/3`). |
| `@len(lo..hi[, unit])` | string, bytes, list, set, map, record | Inclusive length bounds. For strings, `unit` selects what is counted: `scalars` (Unicode scalar values, the default), `utf8` (bytes of the UTF-8 encoding), `utf16` (UTF-16 code units) or `graphemes` (extended grapheme clusters, Unicode UAX #29). Other kinds count bytes or elements and take no unit. |
| `@key` | field | Part of the record's identity: values of this record in the same list MUST differ in their key fields. Key fields MUST be required and non-nullable. |
| `@id(n)` | field, enum variant | Stable numeric identity (n ≥ 1) for evolution checks and positional encodings. Unique per record, or per enum. Either every variant of an enum carries `@id` or none does; a schema where only some do is invalid. |
| `@deprecated` | field | Informational. |
| `@open` | record (after the name) | Unknown fields are accepted and preserved. Records are **closed** by default. |

### 6.2 `@key` and selectors

`@key` guarantees that a selector such as `services[id=api]` (§7.1) identifies at most one element of any valid document. This is what makes keyed patches safe.

### 6.3 Schema-directed resolution

**Resolution** checks a value against a type and applies a fixed set of **lossless conversions**. These exist so that human documents can stay free of type markers when a schema is available. Resolution MUST perform no conversions other than those listed:

| Target type | Accepted input | Rule |
| --- | --- | --- |
| `timestamp` | string | RFC 3339 (§4.8). |
| `duration` | string | Duration syntax (§4.8). |
| `decimal` | string, int, float, rational | Decimal syntax; an int exactly; a finite float via its shortest round-trip digits; a rational only if its denominator has no prime factors other than 2 and 5. |
| `rational` | string, int, decimal | Rational syntax; `n` becomes `n/1`; a decimal exactly. |
| `float` | int | Only if \|i\| ≤ 2^53. |
| `bytes` | string | Base64 (§4.8). |
| `set<T>` | list | Only if there are no duplicates. |
| `(A, …)` | list | Only if the lengths match. |
| `map<K, V>` | record | Keys become strings. |
| enum type | string | Only if the string names a variant without a payload: `active` becomes `!active`. |
| enum type | record with one field | Only if the field names a variant with a payload: `{failed: oom}` becomes `!failed(oom)`. This is how JSON and the other formats spell variants (§11). |
| union `A \| B \| …` | anything | Resolved against each member in order; the result is that of the **first** member against which resolution succeeds (below). |

A union member succeeds only if resolving the value against it reports no issue at all, including `@range` and `@len` violations inside the value. Conversions take part as usual, so the order of members can change the result: under `timestamp | string` an RFC 3339 string becomes a timestamp, under `string | timestamp` it stays a string, and the `timestamp` member is unreachable. `@key` uniqueness is a property of the enclosing list and does not take part in choosing a member; it is checked on the resolved list. `T?` resolves like `null | T`. Absence is not a value and is never a union member: whether a field may be absent is decided only by `name?:` (§6.1).

Notably, resolution never converts a float to a rational or integer, a rational to a float, a number to a string, or a string to a number or boolean.

### 6.4 Validation

Resolving a value against a record type:

1. Every present field is resolved against its declared type.
2. A missing field with a default receives the default, during resolution only. A field that is present with the value `null` is not missing: it never receives the default, and it is valid only if its type admits `null`.
3. A missing optional field stays absent.
4. Any other missing field is an error.
5. Unknown fields are errors unless the record is `@open`.
6. `@range`, `@len` and `@key` constraints are checked.

Implementations SHOULD report **all** violations, each with the path (§7.1) of the offending value, rather than stopping at the first.

A value that resolves against no member of a union is **one** issue, at the path of that value. The issue SHOULD name the union and SHOULD include, as detail, the issues of the member that came closest (for example, for a record, the member whose field names match its keys; otherwise the first member whose kind accepts the input). Those member issues are not reported as issues of their own.

**Validate** checks the same rules without producing a resolved value. **Resolve** returns the value with conversions and defaults applied. The revision of a document is computed from the document as stored, not from its resolution.

### 6.5 Evolution

A new schema version is **backward compatible** with an old one if every value valid under the old schema resolves under the new one, and every value that passes through a union resolves through the member at the same position as before (§6.3) — in other words, new readers can read old data, and read it the same way. A type that becomes a union counts as its first member: `string` → `string | int` keeps every string at position 1, `string` → `timestamp | string` moves them to position 2. Position, not overlap, is what counts, so reordering `int | string` is breaking even though no value could match both. Tools SHOULD report changes as compatible or breaking. The rules:

| Change | Classification |
| --- | --- |
| Add an optional field, or a field with a default | compatible |
| Add a required field without a default | breaking |
| Remove a field | breaking (old data contains it), unless the record is `@open` |
| Close an `@open` record | breaking |
| Widen a type: integer to wider integer, integer to `decimal`/`rational`, `decimal` to `rational`, small integer to `float`, `T` to `T?`, `T` to `any`, wider `@range`/`@len` (with the same `@len` unit) | compatible |
| Narrow or change a type | breaking |
| Make an optional field required (without a default) | breaking |
| Add a variant | compatible (old readers reject the new variant: this is a forward-compatibility concern). In an enum without `@id`, only appending is compatible: a variant inserted before others moves them (below) |
| Remove a variant, or change its payload incompatibly | breaking |
| Reorder the variants of an enum whose variants carry `@id` | compatible |
| Widen `T` to a union whose first member is `T`, or append a member to a union | compatible |
| Insert a member before an existing one, reorder members, or remove a member | breaking: an earlier member can capture values that used to resolve to a later one, and values that matched the removed member may match nothing |
| Widen a union member | compatible for the last member; breaking for any other, which can capture values that used to resolve to a later member |
| Change the `@id` of a variant that is kept | breaking |
| Move a variant of an enum without `@id` to another position | breaking (Protobuf numbers such variants by position, §11.2) |
| Add `@key` | breaking (existing data may contain duplicates) |
| Rename a field that keeps the same `@id` | breaking for name-based representations (all text forms); compatible only for positional or ID-based encodings |

A removal from an enum without `@id` also moves every later variant. Tools SHOULD report that shift once per enum, not once per moved variant. Union members (`type T = A | B`, §6.1) are positional and carry no `@id`; their order decides resolution (§6.3).

Tools SHOULD also warn, in `nvf schema check` and the language server, about union members that an earlier member makes unreachable (`string | timestamp`) and about members whose conversions capture values a later member was probably meant for (`timestamp | string`).

### 6.6 Fingerprints

The **canonical schema text** renders:

1. `@schema name@version`;
2. `@root`, with its type in long form (`@root list<Service>`);
3. every definition, sorted by name, with fields in declared order and types in their long form (`list<T>`, not `T[]`).

Field names are written bare when they are identifiers, otherwise as canonical quoted strings (§4.10). Union members keep their declared order and are separated by ` | `; a member that is an alias to a union is not expanded.

The **fingerprint** is the first 16 hexadecimal digits of the revision (§2.13) of the canonical text, taken as a NOVA string value. A full **schema reference with fingerprint** is written `name@version#fingerprint`, for example `infrastructure@1.2.0#8c21a0f3d5e6b7c8`. Fingerprints are unaffected by comments and formatting.

### 6.7 Versioning

Schema versions are **Semantic Versioning 2.0.0** (<https://semver.org>) versions, and this is enforced, not advisory:

- A named schema MUST declare `@schema name@MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]`. The version MUST conform exactly to the SemVer 2.0.0 grammar: no leading zeros, no `v` prefix, all three components present. Schema names consist of lowercase ASCII letters, digits and `-_./`, and start with a letter.
- A schema without a `@schema` line is **anonymous**. It can validate documents, but it cannot be referenced, and it cannot take part in evolution checks.
- Version precedence follows SemVer §11. Build metadata is ignored for precedence and compatibility.

**Compatibility contract.** A reader holding schema version **R** can read data written against version **W** of the same schema if and only if:

| Case | Condition |
| --- | --- |
| R or W is a pre-release, or either is `0.0.z` | R and W have equal precedence (pre-releases and `0.0.z` promise nothing) |
| R and W are `0.y.z` | same `y`, and R ≥ W |
| otherwise | same MAJOR, and R ≥ W |

A validator given both a document's `@schema` reference and a schema MUST reject the document if the names differ, if the contract above does not hold, or if the reference carries a fingerprint and the versions are equal but the fingerprints differ.

**Release rules.** Moving a schema from version *old* to version *new* MUST obey the change classification of §6.5:

| Changes between old and new | Minimum new version (old ≥ 1.0.0) | Minimum for old = 0.y.z | Minimum for old = 0.0.z |
| --- | --- | --- | --- |
| None: canonical text without the `@schema` line is identical | PATCH + 1 | PATCH + 1 | PATCH + 1 |
| Backward-compatible only | MINOR + 1 | PATCH + 1 | PATCH + 1 |
| At least one breaking change | MAJOR + 1 | MINOR + 1 | PATCH + 1 |

In every case *new* MUST have greater precedence than *old*. A breaking release MUST leave the old compatibility range: per the contract above, *new* must not be able to read data written for *old*. Pre-release versions MAY contain any change. Tools SHOULD reject a release that violates these rules; `nvf schema check old.novs new.novs` does, exiting non-zero.

> *Rationale (non-normative).* Because compatibility is decided by the schema diff (§6.5), a version number is a *checked claim*, not a convention. A consumer that pins `infrastructure@1.4.0` can rely on every `1.x` release at or above it to read its data.

### 6.8 Schemas as data

Every schema has a **descriptor**: an ordinary NOVA value described by the meta-schema `nova-schema@0.3.1`. The meta-schema is itself written in the schema language, and its own descriptor validates against it. Descriptors let every data tool work on schemas: queries, conditional patches, diffs, templates, binary frames and the language server.

```
@schema nova-schema@0.3.1
name: infrastructure
version: 1.0.0
root: {kind: !named, ref: Infrastructure}
defs:
  - name: Port
    alias: {kind: !u16, range: {min: 1, max: 65535}}
  - name: Service
    record:
      fields:
        - {name: id, type: {kind: !string}, key: true, id: 1}
        - {name: port, type: {kind: !named, ref: Port}, id: 3}
        - {name: enabled, type: {kind: !bool}, default: true, id: 5}
  - name: Status
    enum: [{name: active}, {name: failed, payload: {kind: !string}}]
```

**Structure of a descriptor:**
- `root` is a type, written like a field's type.
- Definitions are listed in name order, keyed by `name`. Each has exactly one of `record`, `enum` or `alias`.
- A type is a record with a `kind` and the parts that kind needs:
  - `ref` for `named`;
  - `item` for `list` and `set`;
  - `key` and `value` for `map`;
  - `items` for `tuple`, and for `union`, where it lists the members in order.
- A variant has a `name`, and optionally a `payload` type and an `id` (its `@id`), like a field.
- A type can also carry `nullable`, `range` (exact bounds) and `len` (with an optional `unit`).
- Boolean flags that are false, and absent optional parts, are omitted.

**Conversion:**
- A schema and its descriptor convert into each other without loss: the fingerprint (§6.6) of the converted schema is unchanged.
- An implementation MUST validate a descriptor against the meta-schema, and then apply every rule that applies to schema text: names, references, alias cycles, `@id` uniqueness and defaults.
- The meta-schema can't express "exactly one of `record`, `enum`, `alias`"; that rule is enforced when converting a descriptor back to a schema. Likewise a `union` MUST have at least two `items` and carries no `nullable`, `range` or `len`; those belong to its members.

**Tooling.** Tools SHOULD accept a descriptor wherever a schema is accepted. The reference CLI also loads `.novs` files as their descriptors for `get`, `diff`, `hash` and `convert`. A patched `.novs` file is written back in the schema language.

---

## 7. Paths, queries and patches

### 7.1 Paths

A **path** addresses a location within a value. The path language is deliberately small and **not Turing-complete**: it has no expressions beyond equality, no functions, and no recursion.

```
path       = "" | "." | first ( "." name | "." projection | "[" selector "]" )*
first      = name | "[" selector "]"
name       = identifier | quoted-string
selector   = "*" | int | identifier "=" flow-value | flow-value
           | "?" path cmp flow-value                    ; filter
           | "?" path | "?!" path                       ; exists / absent
           | "?" path "in" list                         ; membership
cmp        = "=" | "!=" | "<" | "<=" | ">" | ">="
projection = "{" name ("," name)* "}"
```

| Segment | Applied to | Selects |
| --- | --- | --- |
| `.name` | record | That field. |
| | map | The entry whose key is that string. |
| `[n]` | list, tuple | Element `n`; negative values count from the end. |
| | map | The entry whose key is the int `n`. |
| `[field=v]` | list of records | The unique element whose `field` equals `v`. Zero matches is *not found*; more than one is *ambiguous*; both are errors. |
| `[v]` | map | The entry with key `v`. |
| | set | The element `v`. |
| | list | The unique element equal to `v`. |
| | record (`v` is a string) | That field. |
| `[*]` | list, tuple, set, record, map | Every element or value. Queries only. |
| `[?p op v]`, `[?p]`, `[?!p]`, `[?p in [..]]` | list, tuple, set, map (values) | Every element for which the condition on the relative singular path `p` holds. Queries only. Consecutive filters combine with AND. |
| `.{a,b}` | record, or list of records | Only these fields (missing fields are omitted). Last segment only; queries only. |

The root path is written `.` or as the empty string. A path without `[*]`, filters or a projection is **singular**: it addresses at most one location.

**Filter comparisons.**

- Numbers (`int`, `float`, `decimal`, `rational`) compare exactly by numeric value across kinds (§6.1), so `[?replicas=3.0]` matches `3`.
- Strings compare by code point.
- Timestamps and durations compare chronologically. A string operand is parsed as the other side's kind: `[?at>"2026-01-01T00:00:00Z"]`.
- Booleans order `false < true`.
- Other values support only `=` and `!=`, which use value equality (§2.12); ordering comparisons on them are false.
- `[?p]` keeps elements where `p` resolves, and `[?!p]` keeps those where it does not.
- `[?p in [a, b]]` keeps elements whose value at `p` equals (as with `=`) one of the listed values.
- Apart from `[?!p]`, an element where `p` does not resolve never matches. In particular, `[?p!=v]` does not select elements that lack `p`; combine it with `[?!p]` when that is wanted.

Filters are the only comparison the path language has. There are still no functions, arithmetic or recursion.

### 7.2 Path errors

Resolving a path fails with one of these errors, each naming the path prefix at which it occurred:

- **not found**;
- **ambiguous** (a `[field=v]` or `[v]` selector matched more than one element);
- **type mismatch** (for example, `.name` applied to a list);
- **not singular** (`[*]` or a projection used where a single location is required).

### 7.3 Queries

A **query document** is a single line, `@get <path>` (`@select` is a synonym). Its **response** is a text document:

```
@revision sha256:91cf16db…        # revision of the whole queried document
@scope services[id=api]           # only when the path, without a final projection, is singular
replicas: 5
port: 3000
```

The body is the selected value: with `[*]` it is a list of the results, and with a projection only the named fields are kept. Responses SHOULD use the compact profile, so a projected list of uniform records becomes a table:

```
@get services[*].{id,replicas}
→
@revision sha256:91cf16db…
[2]{id,replicas}:
  auth,3
  api,5
```

Responses MUST be valid NOVA documents. Hosts SHOULD offer queries so that agents never need to load whole documents into context.

*Command line (non-normative).* `nvf get FILE PATH` answers queries. FILE may be `-` for stdin; JSON and JSON Lines input are detected automatically. Output options:

- `-r` prints raw strings, one line per result for `[*]` and filters, like `jq -r`;
- `--to json` / `--to json-compact` prints JSON;
- `--bare` omits the header;
- `-e` exits with status 1 on `null`, `false` or an empty result.

Example: `curl … | nvf get - 'items[?price<10].name' -r`.

### 7.4 Patch documents

```
patch     = "@patch" [SP schema-ref] [SP base] NL
            ("@base" SP revision NL)?
            ("@scope" SP path NL)?
            op*
op        = path ":" SP old SP "->" SP new NL    ; replace, only if current = old
          | "=" SP path ":" SP value NL           ; set
          | "+" SP path ":" SP value NL           ; add
          | "-" SP path [":" SP old] NL           ; remove (optionally only if current = old)
          | "?" SP path [":" SP value] NL         ; test
```

- Values are flow values and may span lines inside brackets.
- Paths in operations MUST be singular.
- A `@patch` argument beginning with `sha256:` is the base revision; any other argument is the schema reference.
- `#` comments and blank lines are allowed between operations.
- Directives MUST precede operations.

Example:

```
@patch infrastructure@1.0.0 sha256:91cf16db2f4a
@scope services[id=api]
replicas: 5 -> 8
+ tags: canary
? enabled: true
```

### 7.5 Patch semantics

Applying a patch `P` to a document `D`:

1. **Base check.** If `P` has a base revision, `revision(D)` MUST match it (prefix match per §2.13). Otherwise the patch fails with a *stale base* conflict.
2. **Scope.** If `P` has a scope `S`, then `S` MUST be singular and MUST resolve in `D`. Every operation path is interpreted as `S` followed by that path, so operations **cannot address anything outside the scope**. A host MAY additionally bind a scope out of band, for example per tool call; the patch's scope MUST then lie within the bound scope.
3. **Operations** are applied in order to a working copy. Each operation sees the results of the operations before it.
4. **Validation.** If the host has a schema for `D`, the result MUST validate (§6.4).
5. **Atomicity.** If any step fails, the patch is rejected as a whole and `D` is unchanged. The error MUST identify the failing operation (its index and line) and the reason.
6. On success, the host returns the new document and its revision.

Operation semantics, for target path `T` with parent `P` and last segment `s`:

| Operation | Semantics |
| --- | --- |
| `T: old -> new` | `T` MUST exist and equal `old` (§2.12); it becomes `new`. Otherwise a *conflict* reporting the expected and actual values. |
| `= T: v` | If `T` is the root, the document becomes `v`. If `P` is a record or map, field or key `s` is inserted or replaced. If `s` is an index or selector into a list or tuple, the existing element is replaced; `=` never appends. |
| `+ T: v` | If `P` is a list and `s` is `[n]`, `v` is inserted before index `n` (`n` = length appends; negative `n` counts from the end). Otherwise: if `T` exists and is a list, `v` is appended; if `T` exists and is a set, `v` is inserted (an error if already present); if `T` exists otherwise, it is an error (use `=`). If `T` does not exist: when `P` is a record, field `s` is added; when `P` is a map, the entry is added. |
| `- T` | Removes the field, list element, set element or map entry. It is an error if `T` does not exist or is a tuple element. With `: old`, `T` MUST equal `old` first. |
| `? T` | `T` MUST exist. With `: v`, it MUST also equal `v`. Changes nothing. |

> *Rationale (non-normative).* Replace-with-expected-value (`old -> new`) is the default spelling because it makes every edit a compare-and-swap. An LLM that misremembers a value produces a conflict instead of silently overwriting it, and a reviewer sees both the before and the after.

### 7.6 Diffs

Tools MAY generate patches by diffing two values. The reference implementation:

- recurses into records;
- matches list elements by a unique `id`, `key` or `name` field when present and when the change consists only of removals and appends;
- otherwise diffs equal-length lists by index;
- otherwise replaces the list.

Every change is emitted as conditional (`old -> new` or `- path: old`), and the patch carries the base revision.

---

## 8. The agent interaction model

### 8.1 Read a projection, write a conditional patch

NOVA's intended interaction for agents:

```
AGENT     @get services[id=api].{replicas,port}

TOOL      @revision sha256:91cf16db…
          @scope services[id=api]
          replicas: 5
          port: 3000

AGENT     @patch sha256:91cf16db
          @scope services[id=api]
          replicas: 5 -> 8

TOOL      ok sha256:0f1267cd…            (or: conflict / invalid, with reasons)
```

Properties:

- **Small context.** The agent sees only the fields it asked for.
- **Small output.** The agent emits a single short line rather than regenerating the document.
- **Bounded blast radius.** The scope makes edits outside `services[id=api]` impossible, and `@key` (§6.2) makes the selector unambiguous.
- **Concurrency safety.** The base revision and the expected old value detect concurrent changes.
- **Reviewability.** The patch is a precise, human-readable change.

Hosts SHOULD expose `get` and `patch` as tools. Where constrained decoding is available, the schema (§6) and the patch grammar (§7.4) SHOULD be used to constrain generation. Semantic validation (§7.5 step 4) is still required afterwards: a grammar can ensure that `replicas` is a `u16`, but not that 8 is a sensible number of replicas.

### 8.2 Result envelopes (provenance)

A tool result whose domain data must be kept separate from facts *about* that data uses an envelope document:

```
@envelope result
value:
  status: completed
meta:
  source: deployment-api
  observed_at: @timestamp("2026-11-17T16:00:00Z")
  verified: true
```

The body MUST be a record with a required field `value` (the domain value) and an optional field `meta`, a record. These `meta` fields have defined meanings when present:

| Field | Type | Meaning |
| --- | --- | --- |
| `source` | string | Where the value came from. |
| `observed_at` | timestamp | When it was observed. |
| `verified` | bool | Whether the tool verified it, rather than inferring it. |
| `revision` | string | Revision of the source document. |
| `schema` | string | Schema reference for `value`. |
| `confidence` | float in [0, 1] | The *producer's* confidence in its interpretation, never a property of the domain object. |

Consumers MUST NOT merge `meta` into `value`. An envelope cannot establish truth; it lets verifiable provenance travel without being confused with domain data.

---

## 9. Templates and composition

### 9.1 Motivation

YAML's anchors, aliases and merge keys let authors reuse structure, and that reuse is valuable. Its problems come from where it lives:

- reuse is mixed into the data layer, so every consumer has to understand it;
- aliases make the value a graph (and enable "billion laughs" expansion);
- tools such as Helm then template YAML as **text**, which means generating indentation-sensitive syntax with string functions (`nindent`, `toYaml`, `quote`).

NOVA separates the two concerns. A **template** is a different kind of document. It is **rendered** to a plain value before anything else sees it: schemas, hashing, binary encoding, patches and queries operate only on rendered values. Templates operate on **values, not text**, so indentation and escaping cannot go wrong. The template language is **total**: every render terminates, and its output is bounded.

### 9.2 Template documents

A template is a text document whose **first** directive (after an optional `@nova`) is `@template`, optionally followed by the template-language version: `@template 0.1` (§13.1). It may then declare:

```
@template
@param env: string                       # required parameter, typed in schema syntax (§6.1)
@param replicas: u16 @range(1..50) = 2   # with a default
@param owner?: string                    # optional: binds null when not given
@import "base.nova" as base              # another document, rendered and bound to $base
@let registry = "ghcr.io/example"        # a reusable value (flow form)
@let defaults:                           # a reusable value (block form)
  enabled: true
  replicas: $replicas
```

The body is ordinary NOVA text plus the constructs below. In template documents only:

- a token beginning with `$` is a reference;
- `${` inside a quoted or block string begins an interpolation;
- the control lines `@if`, `@else` and `@for` are recognized.

In data documents, `$` MUST NOT begin a token (it is a reserved character, §4.4), so a data document can never be misread as a template.

### 9.3 Constructs

**References.** `$name` followed by an optional path (§7.1), such as `$base.registry` or `$svc.ports[0]`, is replaced by the referenced value. Undefined names and failed paths are errors.

**Interpolation.** In quoted and block strings, `${path}` inserts the canonical text (§4.10) of a scalar: a string, number, bool, timestamp, duration, or unit variant (its tag). Interpolating `null` or a container is an error. `$${` and `\$` produce a literal `$`.

**Spreads.** `...$x` inserts the fields of a record into a record, or the elements of a list, tuple or set into a list:

```
- ...$defaults          # a list item that is a record starting with the fields of $defaults
  id: auth              # later entries win over earlier ones
```

Within one record, entries are applied in order and later entries replace earlier ones, **except** that two explicitly written fields with the same key are an error. Spreads are shallow. Deep edits are done with overlays (§9.6).

**Conditionals.** In block records and block lists:

```
@if $metrics and $env == production:
  - id: metrics
@else if $env == staging:
  - id: metrics-lite
@else:
  - id: noop
```

The bodies are indented two spaces and contribute entries or items to the enclosing record or list.

Conditions combine `==`, `!=`, `not`, `and`, `or` and parentheses over flow values and references. A condition that is a single operand MUST evaluate to a `bool`: there is no truthiness, so `$owner` alone is an error — write `$owner != null`.

**Loops.** `@for x in $xs:` or `@for i, x in $xs:` repeats its body once per element of a list, tuple or set (with `i` bound to the index), or per entry of a record or map (with `i` bound to the key). Loop variables are scoped to the body. Records produced by loop bodies merge into the enclosing record, and duplicate keys are an error. Keys may be interpolated: `"app-${name}": $name`.

### 9.4 Evaluation

1. Parameters are bound from the caller's arguments. Unknown arguments are errors. A missing parameter takes its default if it has one, `null` if it is optional, and is otherwise an error. Each value is then **resolved** against its declared type (§6.3), so `--set when=2026-11-17T16:00:00Z` becomes a timestamp when the parameter is typed `timestamp`. Named types come from a schema supplied by the host.
2. Imports are rendered (without arguments) and bound.
3. `@let` bindings are evaluated in order; each may use parameters, imports and earlier bindings. Rebinding a name is an error.
4. The body is evaluated.

The result is a plain value. Hosts SHOULD validate it against the target schema.

### 9.5 Totality and limits

The language has no user-defined functions, no recursion, no arithmetic, no I/O other than host-mediated imports, and iteration only over finite values. Every render therefore terminates. Because `@let` values can be referenced repeatedly, output can still grow exponentially, so implementations MUST enforce an **output budget** with two limits, both counting every copy made by a reference:

- the number of value nodes produced (reference default: 10^6), which defeats "billion laughs" constructions;
- the total bytes of string and bytes content produced (reference default: 64 MiB, 67108864 bytes), which defeats nested interpolation (§9.3), where a few nodes can carry exponentially long strings.

Exceeding either limit is an error. Implementations MUST also bound the import depth (reference: 16) and MUST reject import cycles.

The nesting-depth bound of §12 applies to templates, but only real nesting counts: the arms of an `@if … @else if … @else` chain are siblings, so a long chain is not a deep one.

**Imports** are resolved by the host. A host MUST NOT fetch from the network unless the user has configured it to. The reference file loader accepts only relative paths beneath the root template's directory and rejects absolute paths, URLs and `..` escapes.

### 9.6 Overlays

Kustomize-style overlays need no new mechanism: an overlay is a **patch** (§7.4) applied to a rendered base. Overlays get the same conditional operations, atomicity and validation as agent edits:

```
nvf render base.tpl.nova --set env=prod > base.nova
nvf patch base.nova prod-overlay.patch --schema infra.novs
```

### 9.7 Why this is not "YAML as a programming language" (non-normative)

- **Opt-in and visible.** Only documents that start with `@template` can contain template constructs. Data documents reject them.
- **One-way.** Templates render to values. Nothing downstream evaluates anything.
- **Typed at the boundary.** Parameters are declared and resolved against schema types before evaluation.
- **Total.** Templates have no recursion or user functions, have a bounded output, and terminate by construction.
- **Value-level.** There is no string pasting of syntax, so the Helm class of indentation and quoting bugs cannot occur.

---

## 10. Token-aware representation selection

*This section is non-normative.*

There is no universal relationship between characters, tokens and LLM task performance. Tokenizers differ, and fewer input tokens do not always mean fewer total tokens or more successful tasks. Tables shine on uniform record lists and lose their advantage on irregular, deeply nested data.

A **token-aware serializer** chooses among value-preserving representations `E` to minimize:

  T_input(E) + 𝔼[T_output(E)] + λ · P_failure(E)

where `λ` prices task failures (including retries and repair loops). Only representations that preserve the semantics the task needs are eligible. `T_input` can be measured exactly with the target model's tokenizer. `T_output` and `P_failure` require empirical evaluation per model and task.

The reference implementation provides a `TokenCounter` trait, a deterministic `HeuristicCounter` that approximates subword tokenizers, and `rank_profiles`, which renders the human and compact profiles and ranks them by count. Production systems should plug in the real tokenizer and re-rank with measured `T_output` and `P_failure`.

Recommended evaluation workloads:

1. reading heterogeneous nested data;
2. reading large homogeneous record collections;
3. generating complete structured objects;
4. editing a small part of an existing document;
5. following references across a collection of documents.

Measure parser throughput, allocations, bytes, tokenizer-specific token counts, round-trip fidelity, schema adherence, task accuracy, and — for agents — **total tokens and wall-clock time to a correct, validated result**, including retries.

---

## 11. Interoperability mappings

### 11.1 JSON and JSON Lines

**JSON → NOVA** (lossless)

- object → record (duplicate keys are an error)
- array → list
- string → string
- `true`/`false`/`null` → bool/null
- a number with neither fraction nor exponent → `int` (exact, never via binary64)
- any other number → `float`

JSON Lines maps to a list of the values on its non-empty lines.

**NOVA → JSON** (lossless for the JSON subset). Other kinds map as follows, and **every such mapping MUST be reported** to the caller, who MAY refuse it ("strict" conversion):

| NOVA | JSON |
| --- | --- |
| int beyond ±2^53 | number (with a warning about precision in common readers) |
| non-finite float | string |
| decimal, rational, timestamp, duration | canonical text as a string |
| bytes | base64 string |
| tuple, set | array |
| map | array of `[key, value]` arrays |
| unit variant | string (the tag) |
| variant with payload | `{"tag": payload}` |

### 11.2 Other formats

Adapters for other formats SHOULD follow the same discipline: lossless where the target can represent the kind, and an explicit report where it cannot. The reference adapters (`novafile-formats`, `novafile-proto`) implement the following.

**YAML.**
- *Reading:*
  - YAML 1.2 core schema, applied to plain scalars only. YAML 1.1 surprises (`yes`, `on`, `0777`) stay strings.
  - Integers are read exactly, including beyond 64 bits.
  - Quoted and block scalars are strings.
  - Aliases are expanded under the output budget of §9.5 (both its node and its byte limit), which defeats "billion laughs" documents.
  - Merge keys (`<<`) and tags other than the core tags and `!!binary` MUST be rejected (use templates, §9, instead).
  - A mapping with only string keys becomes a record; any other mapping becomes a map.
- *Writing:*
  - A string is quoted whenever a YAML 1.1 or 1.2 reader could resolve it to another type.
  - Decimals, rationals, timestamps, durations, tuples, sets and variants are written with loss warnings.
  - Bytes are written as `!!binary`.

**TOML.**
- *Reading:* an offset date-time becomes a timestamp. Local dates and times become strings.
- *Writing:*
  - The root MUST be a record.
  - `null`, and integers outside 64 bits, are errors.
  - Timestamps are written as offset date-times.
  - A list of records becomes an array of tables.
  - NOVA-only kinds are written with loss warnings.

**CBOR (RFC 8949).**
- Tags:

  | Kind | Tag |
  | --- | --- |
  | timestamp | 0 (RFC 3339 text; reading also accepts tag 1) |
  | big integers | 2 and 3 |
  | decimal | 4 (decimal fraction) |
  | rational | 30 |
  | set | 258 |
  | map whose keys are all strings | 259, so it does not read back as a record |

- Durations, tuples and variants have no registered tag and are written with loss warnings.
- A deterministic mode implements RFC 8949 §4.2.1.

**Protobuf (proto3).** Protobuf requires a schema; `novafile-proto` derives it from a NOVA schema:
- `@root` MUST name a record type, which becomes the top-level message;
- every record field MUST carry `@id(n)`, which becomes its field number;
- records become messages;
- enums with only unit variants become proto enums with a zero `…_UNSPECIFIED` value;
- enums with payloads become messages with a `oneof`;
- a variant's `@id` becomes its proto enum value number or its `oneof` field number; without `@id`, variants are numbered by position starting at 1;
- timestamps and durations use the well-known types; decimals and rationals are strings;
- optional fields, nullable types and fields with defaults become `optional`.

Values are resolved against the schema before encoding and validated after decoding. Features Protobuf cannot express are rejected with an error naming the definition and field: tuples, `any`, unions, nested repeated values, nullable collections, non-scalar map keys and so on.

### 11.3 Language bindings

Bindings map NOVA kinds to native types. They SHOULD follow these rules:

- **The native type acts as a schema.** When the target type is known — a timestamp, a decimal, an enum — a binding SHOULD accept the string spellings that §6.3 would resolve, and nothing else. So a schema-free document with `at: 2026-11-17T16:00:00Z` deserializes into a timestamp field.
- **Enums map to variants.** A binding SHOULD accept the variant itself, a string naming a unit variant, or a single-entry record `{tag: payload}`. The last form lets data that passed through JSON still deserialize.
- **No lossy narrowing.** A rational, decimal or out-of-range integer MUST NOT be silently converted to a float or a narrower integer. Bindings MAY offer explicit, opt-in adapters.
- **Errors carry paths.** Errors SHOULD report the path (§7.1) of the offending value, e.g. `services[1].port: invalid value: integer 70000, expected u16`.

**Rust / Serde (reference binding, `novafile-serde`):**

| Serde data model | NOVA |
| --- | --- |
| bool, i8…i128, u8…u128, f32/f64, char, str, bytes | bool, int, float, string (char), string, bytes |
| `None`, unit, unit struct | null |
| `Some(x)`, newtype struct | `x` |
| seq | list |
| tuple, tuple struct | tuple |
| struct, map with string keys | record |
| map with other keys | map (when deserializing, numeric keys also accept their string form, as in JSON objects) |
| unit / newtype / tuple / struct variant | `!Tag`, `!Tag(x)`, `!Tag((a, b))`, `!Tag({…})` |
| `novafile_value::{Timestamp, Duration, Decimal, Rational}` | the corresponding kind |
| `novafile_value::Value` | itself, losslessly |
| `#[serde(with = "novafile_serde::with::set")]` | set |
| `with::duration` (`std::time::Duration`), `with::system_time` (`SystemTime`) | duration, timestamp |

Serde has no data-model slots for NOVA's extra kinds. The binding therefore uses reserved newtype-struct names (`$nova::timestamp`, `$nova::decimal`, `$nova::set`, `$nova::value`, …). With other serde formats these degrade to natural forms: a timestamp becomes its canonical text, a set becomes a sequence, and a variant becomes a string or `{tag: payload}`. This means the same Rust types can also be serialized to JSON with the usual JSON conventions.

**Rust schema derivation.** `#[derive(NovaSchema)]` (crate `novafile-derive`, re-exported by `novafile-schema` with feature `derive`) generates the NOVA schema of a Rust type.
- Mapping: structs become records, enums become variants (struct variants get a record of their own), and newtype structs become aliases. `Option<T>` becomes an optional, nullable field, and collections, maps and tuples map as in the table above.
- `#[nova(...)]` attributes carry what Rust types cannot express:
  - `name` and `version` produce the `@schema` line;
  - `key`, `id`, `range`, `len`, `default`, `deprecated` and `open` map to the schema attributes of the same names.
- Serde attributes (`rename`, `rename_all`, `default`, `skip`) are honoured, so values produced by `novafile-serde` resolve against the derived schema. Internally tagged and untagged enums, `flatten` and generic types are rejected at compile time.

**Rust / facet (`novafile-facet`).** A reflection-based binding built on `facet` (`#[derive(Facet)]`), with the same mapping and API as `novafile-serde`. It needs no reserved names: the NOVA types are recognised by their shapes. Its differences from the Serde binding are:
- sets map to `set` natively, without an adapter;
- `Vec<u8>` and byte arrays map to `bytes`;
- fixed-size arrays map to `list`;
- enums must declare a `repr`.

Both bindings read each other's output.

---

## 12. Security considerations

- **No implicit execution.** Data documents contain no code, references or includes. Templates (§9) are a separate document kind with total semantics and host-mediated imports.
- **Resource limits.** Parsers and decoders MUST bound nesting depth and SHOULD bound input size, the string-table size (§5.3) and template output (§9.5). Element counts in binary input are checked against the remaining length before any allocation.
- **Duplicate keys** are rejected everywhere, which prevents parser-differential attacks in which two components see different values.
- **Canonicalization** gives one revision per value, so signatures and hashes over the canonical encoding are not malleable by reordering or re-spelling.
- **Schemas are never fetched** automatically from `@schema` references.
- **Patch scope** limits what an automated agent can change. Hosts SHOULD bind scopes per tool call for untrusted agents.
- **Unicode.** NOVA does not normalize strings. Applications that compare identifiers from different sources SHOULD normalize them (for example to NFC) themselves, and SHOULD be aware of confusable characters in keys.

---

## 13. Conformance

### 13.1 Versioning of the languages

NOVA has three versioned layers, which evolve independently:

| Layer | Version | Declared by |
| --- | --- | --- |
| The NOVA language: value model, text syntax, binary encoding, path, patch and schema syntax | `MAJOR.MINOR`; this document is 0.1 | `@nova 0.1` as the first directive of any document, patch, query or `.novs` file; the version byte of binary frames (§5.4) |
| The template language (§9) | `MAJOR.MINOR`, currently 0.1 | `@template 0.1` |
| Each schema | SemVer 2.0.0 | `@schema name@X.Y.Z` (§6.7) |

- Language versions are written `MAJOR.MINOR`: decimal, with no leading zeros.
- An implementation of version X.Y MUST accept documents declaring X.y for every y ≤ Y. It MUST reject a different major version, and a minor version newer than its own.
- While the major version is 0, minor versions MUST match exactly.
- A document without a declaration is read as the newest version the reader implements. Documents meant to outlive tooling generations SHOULD declare their version.
- Within a major version, minor versions may only *add* syntax. A valid document of version X.y keeps its meaning under X.(y+1).
- A change to the meaning of existing syntax, or a removal, requires a new major version.
- Writers SHOULD NOT emit `@nova` unless they use features newer than X.0, so that output stays readable by the widest range of readers.

| Class | Requirements |
| --- | --- |
| **Value implementation** | §2 and §5.1–5.3: model, equality, canonical encoding, revisions. |
| **Text reader** | §4 parsing, including every error condition marked MUST. |
| **Text writer** | §4.10: output re-parses to an equal value; canonical spellings for the canonical profile. |
| **Binary implementation** | §5. |
| **Schema implementation** | §6.1–6.4 (resolution performs exactly the listed conversions) and §6.7 (SemVer versions and the compatibility contract). §6.5–6.6 are RECOMMENDED. |
| **Patch host** | §7.1–7.5, including atomicity and conflict reporting. |
| **Template renderer** | §9, including the output budget and import restrictions. |
| **Editor** | Document-preserving fidelity (§3) for regions it does not intend to change. |

---

## 14. Reference implementation

The Rust reference implementation lives at <https://github.com/novafile/nova>. It consists of a Cargo workspace whose crates are published as `novafile-*`; the command-line tool is `nvf` and the language server `nvf-lsp`. Editor support lives in <https://github.com/novafile/vscode-novafile> and <https://github.com/novafile/tree-sitter-nova>. The conformance suite in this repository (`conformance/`) is the cross-implementation test of the specification.

| Crate | Implements |
| --- | --- |
| `novafile-value` | §2, §5.1–5.3: value model, decimals, rationals, time types, canonical encoding, decoding, revisions |
| `novafile-binary` | §5.4–5.5: frames, CRC-32, recovering stream reader |
| `novafile-text` | §4, §7.1: parser, writer profiles, paths, template syntax tree, source spans, token heuristics (§10); `miette` diagnostics behind a feature |
| `novafile-schema` | §6: schema parser, resolution and validation, compatibility checks, fingerprints |
| `novafile-patch` | §7: queries and projections, the patch language, atomic application, diffs |
| `novafile-template` | §9: rendering, sandboxed file loader, limits |
| `novafile-json` | §11.1: JSON and JSON Lines mapping with loss reporting |
| `novafile-formats` | §11.2: YAML, TOML and CBOR adapters with loss reporting |
| `novafile-proto` | §11.2: `.proto` generation and Protobuf wire encoding/decoding from NOVA schemas |
| `novafile-serde` | §11.3: Serde serializer/deserializer, text and binary helpers, `with::` adapters |
| `novafile-derive` | `#[derive(NovaSchema)]`: NOVA schemas from Rust types |
| `novafile-schemars` | NOVA schemas from Rust types via schemars, and NOVA schema ↔ JSON Schema (2020-12, draft-07 input) |
| `novafile-facet` | §11.3: facet (reflection) binding with the same mapping and API |
| `novafile-lsp` | Language server: diagnostics (syntax, patches, schemas, §6.7 schema lookup), outline, hover, completion, comment-safe formatting |
| `novafile-cli` | The `nvf` command: `fmt`, `convert`, `hash`, `validate`, `get`, `patch`, `diff`, `render`, `stats`, `schema {fmt,fingerprint,check}` |

**Known gaps in version 0.1:**

- **Fidelity.** The reference implementation is document-preserving without a separate concrete syntax tree. Instead, the parser records the source span of every value and every comment (`parse_with_spans`). `nvf fmt` (`format_preserving`) re-renders with comments, blank lines and the author's spellings carried over. `nvf patch` on text (`apply_to_source`) edits the source surgically and reports whether any part had to be re-rendered. Whitespace *inside* a line (for example, alignment after `key:`) is normalised whenever that line is re-rendered.
- **Envelopes.** `@envelope` (§8.2) is accepted as a directive, but its body structure is not yet checked.

---

## Appendix A — Grammar summary

```
document    = [BOM] (blank | directive)* body blank*
directive   = "@" name [SP rest-of-line] NL
body        = ε | block-record(0) | block-list(0) | top-table | flow-value NL

block-record(n) = (indent(n) entry)+
entry       = key ":" (SP inline-value | NL block(n+2) | ws-comment NL block(n+2))
            | key table-head ":" NL table-rows(n+2)
            | template-line(n)                          ; templates only
block-list(n)   = (indent(n) "-" (SP item-value | NL block(n+2)))+
item-value  = key ":" … (first entry of a record at n+2) | inline-value
inline-value = flow-value | plain-scalar | block-string | variant-block
block-string = "|" ["-"] NL content-lines(n+2)
table-head  = "[" digit+ "]" "{" key ("," key)* "}"
table-rows(n) = (indent(n) [cell] ("," [cell])* NL){N}
cell        = flow-value

flow-value  = quoted | word | "[" items "]" | "{" fields "}" | "(" tuple ")"
            | "@set[" items "]" | "@map{" (flow-value "=>" flow-value),* "}"
            | "@" name "(" quoted ")" | "!" name ["(" flow-value ")"]
            | "$" path                                  ; templates only
key         = identifier | quoted
identifier  = ('A'..'Z' | 'a'..'z' | "_") ('A'..'Z' | 'a'..'z' | '0'..'9' | "_" | "-")*

template-line(n) = "@if" SP cond ":" NL body(n+2) [indent(n) "@else" (":" | SP "if" …) NL body(n+2)]
                 | "@for" SP [identifier ","] identifier SP "in" SP flow-value ":" NL body(n+2)
                 | "..." flow-value NL
cond        = or ; or = and ("or" and)* ; and = unary ("and" unary)*
unary       = "not" unary | "(" cond ")" | flow-value [("==" | "!=") flow-value]
```

---

## Appendix B — Comparison with existing formats

*Non-normative.* What NOVA takes from each format, and what it avoids:

| Format | Adopted | Avoided |
| --- | --- | --- |
| JSON / JSONL | Strict number grammar, escapes, record streams | Limited types, no comments, silently accepted duplicate keys |
| JSON5 | Comments, trailing commas, unquoted keys | — |
| YAML | Block layout, comments, reuse (moved into §9) | Implicit typing, flexible indentation, aliases in data, tag semantics |
| TOML | Explicit types, predictability | Awkward deep nesting and arrays of tables |
| RON | Tuples, enums and variants, typed values | Rust-specific conventions |
| Protobuf | Varints, zigzag, numeric field identities (`@id`), evolution rules | Schema-dependent wire format |
| MessagePack / CBOR | Self-describing binary, tagged types | Tag semantics that need out-of-band agreement |
| TOON | Tables with declared columns and row counts | Applying tables where data is irregular |
| JSON Patch | Patch operations, `test` | Opaque JSON Pointer paths, no keyed selectors, no base revision |

---

## Appendix C — Open questions and future work

1. **Positional binary.** The positional idea (§4.12) applied to the binary encoding: records as field values in declared order, i.e. Protobuf-like compactness without a separate wire format.
2. **References.** Explicit references to independently identified records (`@ref(services, api)`) across documents, without general cyclic graphs.
3. **Lossless syntax tree.** A full concrete syntax tree, which would also preserve intra-line whitespace and comments inside flow values, for refactoring tools and schema migrations.
4. **Adapters and bindings:** MessagePack, and bindings for languages other than Rust.
5. **Constrained decoding.** Generate tokenizer-level grammars from schemas and the patch grammar.
6. **Empirical evaluation** of the §10 objective across models, using the five workloads.
7. **Scale-preserving decimals.** Should `1.50` and `1.5` be distinguishable? Version 0.1 says no; schemas can constrain scale.
8. **Rational shorthand.** Is a bare `11/17` being a rational the right trade-off, or should rationals require `@rational(...)`? Version 0.1 treats bare `n/d` as a number, consistent with integers.
9. **Tensors.** A `tensor` kind for vectors, matrices and n-dimensional arrays (dtype, shape and row-major data, e.g. `@tensor<f32>[2,3](1, 2, 3; 4, 5, 6)`, binary tag `0x12`, schema types such as `vector<f32, 1536>`) is proposed in [proposals/0001-tensors.md](proposals/0001-tensors.md).
10. **Labels and annotations.** Conventions for selectable labels and owner-namespaced annotations, plus small filter additions (`[?p]`, `[?!p]`, `[?p in […]]`), are proposed in [proposals/0003-labels-and-annotations.md](proposals/0003-labels-and-annotations.md).
11. **Streaming, massive documents and a TUI.** These are proposed in [proposals/0002-streaming-massive-documents-tui.md](proposals/0002-streaming-massive-documents-tui.md):
    - NOVA Lines (`.novl`), with streaming tables and an `@end` trailer;
    - binary control frames and shared dictionaries, and sized (skippable) containers;
    - pull-event and lazy APIs, and streaming query evaluation;
    - `tree:` Merkle revisions and scoped `@expect` preconditions;
    - sidecar patch logs;
    - a TUI browser and editor.
12. **Quoted variant tags.** Variant tags are identifiers (§2.11), so an enum cannot model keys such as `=`, `>=` or `at start` as variants; a union of single-field records (§6.1) is the current way to express them. Allowing quoted tags (`!"at start"(…)`) in the value model would let such operators become enum variants with `@id`s. The binary encoding (§5.1) and the JSON mapping (§11.1) already carry tags as strings; the text syntax, interpolation (§9.3) and the conventions (Appendix E) would change.

---

## Appendix E — Conventions and lints

*Non-normative, but recommended.* JSON never acquired naming conventions, so every project invents its own. NOVA recommends one set of conventions, and the reference tooling (`nvf lint`, the language server) checks them.

| Element | Convention |
| --- | --- |
| Record keys and schema field names | `snake_case` |
| Enum variant tags | `snake_case` (`!active`, `!failed(…)`) |
| Schema definition names | `PascalCase` (enforced by the schema grammar, §6.1) |
| Schema names | lowercase with `-_./` (enforced, §6.7) |
| Field identities | every field of a record has `@id`, or none does (for enum variants this is a schema rule, §6.1) |

Exceptions are explicit:
- `@compat json|yaml|toml` (§4.2) marks data whose names belong to an external contract;
- `@x-lint case=camel` (or `kebab`) selects another convention for a document;
- `@x-lint allow=rule,…` turns individual rules off.

Documents that declare `@schema` take their names from the schema, so naming rules apply to the schema rather than to the document.

| Rule | Level | Checks | Fix |
| --- | --- | --- | --- |
| `key-case` | warning | keys follow the convention (not in `@compat` documents, nor in documents with `@schema`) | rename, unless the new name already exists |
| `key-collision` | warning | keys in one record that differ only in case or separators (`userId` / `user_id`) | — |
| `quoted-key` | hint | keys that need quotes | — |
| `untyped-timestamp` | hint | plain strings that are RFC 3339 timestamps, in documents without a schema | wrap in `@timestamp(…)` |
| `mixed-list` | hint | lists that mix scalar kinds | — |
| `compat-loss` | warning | in `@compat F` documents, values that F cannot represent | — |
| `field-case` / `variant-case` | warning | schema field and variant names; quoted field names are exempt, since they exist for external contracts | — |
| `partial-ids` | warning | records where only some fields have `@id`. An enum where only some variants have `@id` is not linted: it is an invalid schema (attribute table, §6.1) | — |

Fixes are text edits at source spans, so comments and layout are preserved. `nvf convert` from JSON, YAML or TOML into NOVA text adds the matching `@compat` directive.

