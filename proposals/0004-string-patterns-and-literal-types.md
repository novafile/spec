# NOVA Proposal 0004: String patterns and literal types

| | |
| --- | --- |
| Status | Draft proposal for discussion. Not normative until merged into SPEC.md. |
| Targets | §6.1 (types and attributes), §6.3 (resolution), §6.4 (validation), §6.5 (evolution), §6.6 (canonical text), §6.8 and `meta/nova-schema.novs` (descriptors), §11.2 (JSON Schema, Protobuf), §12 (security), Appendix E (lints), conformance suite |
| New kinds / tags / directives | none in the value model; schema attribute `@pattern`, schema literal types, schema directives `@x-…` |
| Date | 2026-11-19 |

---

## 0004.0 Summary

Numbers can be narrowed with `@range`, and strings, bytes and collections with `@len`, but a string type cannot say *which* strings it accepts. This proposal adds two small, independent features that close that gap, plus a separable lint fix:

1. **`@pattern("…")`**, a string constraint next to `@range` and `@len`. The pattern is an **I-Regexp** (RFC 9485), always matched against the **whole** string.
2. **String literal types**: a quoted string in type position, such as `"total-time"`, is a type whose only value is that string.
3. **Schema-level lint settings** (§0004.7, separable): schemas accept `@x-…` directives, and `@x-lint case=… allow=…` configures the schema lints, so a schema that mirrors an external vocabulary (PDDL's `scale-up`, `at-most-once`, `is-violated`) can turn `field-case` off or select `kebab`.

| Facet | Recommendation |
| --- | --- |
| Pattern dialect | I-Regexp (RFC 9485): XSD-style regexps without backreferences, lookaround, anchors or multi-character escapes. Regular, so linear-time matching is always possible |
| Match semantics | Whole-string match. No anchors are needed, and `^`/`$` are literal characters in I-Regexp (linted) |
| What a pattern applies to | `string`, including type arguments (`map<string @pattern(…), V>`) and union members. Not `bytes`, not record field names |
| Literal types | Strings only, for now. `"x"` matches exactly the string `x`, scalar by scalar, with no normalization and no conversion |
| Effect on unions | Members become disjoint where they used to overlap: `Variable \| Name`, `"undefined" \| Name` |
| Evolution | Removing `@pattern` is compatible. Adding or changing one is breaking. Classification is by pattern text, never by language inclusion, so every tool agrees |
| Canonical form | `@pattern("…")` with the pattern as a canonical quoted string, after `@range` and `@len`; a literal type is its canonical quoted string |
| Descriptor | `Type.pattern`, `Type.literal`, and a new `Kind` variant `literal`. Meta-schema `nova-schema@0.3.2` (compatible) |
| JSON Schema | `@pattern(p)` ↔ `"pattern"` via RFC 9485 §5.3; literal ↔ `"const"`; a union of literals may become `"enum"` |
| Protobuf | Both map to `string`; the constraint is enforced on encode and after decode, as `@len` is today |
| Rejected | A choice of dialects, partial (search) matching, `@pattern` on `bytes`, flags such as case-insensitivity, multiple patterns per type, proving regex inclusion during evolution checks |

---

## 0004.1 Motivation

The PDDL 3.1 schema (`schema/pddl.novs`) that came out of the unions work (§6.1) follows the grammar all the way down: goals, preconditions with preferences and `forall`, effects, numeric expressions, duration constraints, timed goals, durative effects, constraint goals, init elements and metrics. Unions removed the old "formulas are `any`" limitation, and quoted field names let every PDDL keyword become a one-field record. Its remaining gaps are all about strings:

| Gap | Why it exists today |
| --- | --- |
| `?x` variables and names are the same type | Both are `string`. Nothing can say "starts with `?`" |
| `?duration`, `#t`, `total-time`, `undefined` are accepted as any name | Nothing can pin a string to one exact value |
| An atom's first element isn't checked to be a symbol | `list<string \| int>` constrains every element alike |

The same need shows up well beyond PDDL: identifiers and slugs, semantic versions, ISO codes, DNS names and label keys (proposal 0003 fixes the key syntax `[prefix/]name` but cannot check it), and every JSON Schema that uses `pattern` or `const`. `novafile-schemars` reads those keywords today and reports them as "not enforced".

Enums do not cover the exact-value case:

- **Enums convert.** Under an enum type the string `undefined` resolves to the variant `!undefined` (§6.3). A schema that mirrors an external format usually wants the value to stay the string it is, so that `nvf convert` back to JSON writes what it read.
- **Variant tags are identifiers** (§2.11). `#t`, `?duration`, `=` or `at start` cannot be variants (Appendix C item 12).

---

## 0004.2 `@pattern`

### 0004.2.1 Syntax

`@pattern` is a type attribute, like `@range` and `@len`. Its single argument is a quoted string (§4.6) whose content is the pattern:

```
type Slug     = string @len(1..63) @pattern("[a-z0-9]([a-z0-9-]*[a-z0-9])?")
type SemVer   = string @pattern("(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)")
type Variable = string @pattern("[?][A-Za-z][A-Za-z0-9_-]*")

record Labels:
  labels?: map<string @pattern("([a-z0-9.-]+/)?[A-Za-z0-9]([A-Za-z0-9_.-]*[A-Za-z0-9])?"), string>
```

Proposed addition to the attribute table (§6.1):

| Attribute | Applies to | Meaning |
| --- | --- | --- |
| `@pattern("p")` | string | The string MUST match the I-Regexp `p` (RFC 9485) as a whole. At most one per type. An argument that is not a valid I-Regexp makes the schema invalid. |

The pattern goes through two layers of syntax: NOVA string escapes first (§4.6), then I-Regexp. A regex backslash is therefore written `\\` inside the quotes. Character classes avoid most of that: `[?]` instead of `\\?`, `[.]` instead of `\\.`, and `-` placed first or last in a class (`[A-Za-z0-9_-]`) needs no escape.

### 0004.2.2 Dialect

The dialect is **I-Regexp (RFC 9485)**, and only that. Reasons:

- **Portable by design.** I-Regexp is the subset of XSD regexps that maps mechanically to ECMAScript, PCRE, RE2, Go, Ruby, Rust's `regex` and XSD itself (RFC 9485 §5). A schema means the same thing in every binding.
- **Safe by construction.** No backreferences and no lookaround, so every I-Regexp is a true regular expression and can be matched in time linear in the input (§0004.6). There is no catastrophic backtracking to guard against.
- **Already the interop choice.** JSONPath (RFC 9535) uses it for `match()` and `search()`, and JSON Schema's guidance for interoperable `pattern`s points the same way.
- **Unicode-aware.** It operates on Unicode scalar values, the unit NOVA strings are made of (§2.8), and supports `\p{…}` and `\P{…}` categories.

What authors coming from PCRE or ECMAScript should know:

| Construct | I-Regexp |
| --- | --- |
| `^`, `$` | **literal characters**, not anchors. The match is always whole-string, so anchors are never needed. A pattern that starts with `^` or ends with `$` is linted (§0004.5) |
| `\d`, `\w`, `\s` | not available. Use `[0-9]`, `[A-Za-z0-9_]`, `[ \t\n\r]` (RFC 9485 §5.1) |
| `.` | any scalar except `\n` and `\r` (XSD semantics) |
| `(?:…)`, `(?i)`, lazy quantifiers, backreferences, lookaround | not available |
| `{n}`, `{n,}`, `{n,m}` | available; `{,m}` is not |

There are no flags. Case-insensitive matching is spelled out with classes (`[Aa]`), which keeps the meaning of a pattern in the pattern text, where fingerprints see it.

### 0004.2.3 Semantics

- A string value **satisfies** `@pattern(p)` if and only if the whole string, as a sequence of Unicode scalar values, matches `p` under the semantics of RFC 9485 §4. There is no partial ("search") mode; `.*p.*` expresses one where it is wanted, with `(.|\n|\r)*` when line breaks must be crossed.
- No normalization is applied, as everywhere in NOVA (§12).
- `@pattern` applies to values of kind `string` after resolution. It is not valid on types that a string resolves *into* (`timestamp`, `decimal`, enums, …): their syntax is already fixed by §6.3.
- `@pattern` combines with `@len`. Both must hold, and the order in which they are written does not matter.
- `\p{…}` follows the Unicode version of the implementation. Implementations SHOULD use a current version and SHOULD document it. A schema that needs identical results everywhere avoids categories that newly assigned characters can join.

### 0004.2.4 Resolution and validation

§6.4 rule 6 becomes: "`@range`, `@len`, `@pattern` and `@key` constraints are checked." A violation is reported at the path of the string, and the message SHOULD include the pattern:

```
services[2].name: "Api_1" does not match @pattern("[a-z0-9]([a-z0-9-]*[a-z0-9])?")
```

In unions, `@pattern` takes part in choosing a member exactly like `@range` and `@len` do (§6.3): a member succeeds only if resolving the value against it reports no issue at all, so a pattern violation moves resolution on to the next member.

---

## 0004.3 String literal types

### 0004.3.1 Syntax

A quoted string (§4.6) in type position is a **literal type**. It appears wherever a type may, and is most useful as a union member:

```
type MetricExp  = "total-time" | IsViolated | FExp
type AssignExp  = "undefined" | FExp
type Comparator = "<" | "<=" | "=" | ">=" | ">"
```

Proposed addition to the types table (§6.1):

| Syntax | Meaning |
| --- | --- |
| `"text"` | a string literal type: exactly the string `text` |

Rules:

- A literal type takes no type attributes. `@range`, `@len` and `@pattern` on a literal are an error, since the value is already fixed.
- `"text"?` is valid and means `"text" | null`, as for every `T?`.
- A literal may appear inside type arguments (`list<"a" | "b">`), tuples (`("=", Term, Term)`) and variant payloads.
- Bare words remain type names. `total-time` in type position is a reference to a definition (and an invalid one, since definition names are PascalCase); the quotes are what make a literal.
- Two literals in one union that are equal make the later one unreachable; this is linted, not an error (§0004.5).

### 0004.3.2 Semantics

- Resolving a value against `"text"` succeeds if and only if the value is a string equal to `text`, scalar by scalar (§2.12). No conversion applies: the number `5` does not match `"5"`, and the string `!active` does not match a variant.
- The resolved value is the string itself. Literal types never change what a value is, only which values are accepted.
- Literals are strings only in this proposal. Integer, boolean and `null` literals are an obvious extension (§0004.10); `int @range(3..3)`, `bool` and `null` cover those cases today.

### 0004.3.3 Literals or enums

Both fix a set of values. They differ in the resolved value:

| | Enum `enum Agg = sum \| max` | Literals `type Agg = "sum" \| "max"` |
| --- | --- | --- |
| Input `sum` resolves to | the variant `!sum` | the string `sum` |
| Tags | identifiers only | any string: `"#t"`, `">="`, `"at start"` |
| Payloads, `@id` | yes | no |
| Natural mapping | Rust/Protobuf enum | TypeScript string-literal union, JSON Schema `const`/`enum` |

The guidance for schema authors: use an enum for a closed vocabulary that the program itself owns, and literals when the strings belong to an external contract and must survive round trips unchanged.

---

## 0004.4 How both sharpen unions: PDDL

The PDDL schema's gaps, with the proposal applied. This excerpt is illustrative; the real schema has more members per union.

```
# PDDL names: a letter, then letters, digits, '-' and '_'. Variables: '?' and a name.
type Name     = string @pattern("[A-Za-z][A-Za-z0-9_-]*")
type Variable = string @pattern("[?][A-Za-z][A-Za-z0-9_-]*")
type Term     = Variable | Name                  # disjoint: they differ in the first character

# Exact values that used to be "any name".
type FExp      = int | float | "?duration" | "#t" | FHead | BinaryOp | Minus
type MetricExp = "total-time" | IsViolated | FExp
type AssignExp = "undefined" | FExp

# The head of an atom is a name, never a variable or number.
type Atom = list<Term>                           # closer than list<string | int>; see below
```

What each gap becomes:

| Gap | With this proposal |
| --- | --- |
| Variables vs names | Closed. `Variable \| Name` are disjoint, so `(at ?x home)` and `(at truck home)` resolve differently, and a variable where only names are allowed (in `:init`, say) is an error |
| `?duration`, `#t`, `total-time`, `undefined` | Closed. Each is a literal in exactly the positions PDDL allows it. Elsewhere `#t` matches neither `Name` nor `Variable` and is rejected, and `total-time` or `undefined` are ordinary names again |
| The atom's head is a symbol | Narrowed, not closed. `list<Term>` rules out numbers but still lets a variable stand at the head. A typed head needs a tuple with a rest element (`(Name, Term...)`), which is out of scope (§0004.10). Until then, a bounded arity can be spelled as a union of tuples, `(Name) \| (Name, Term) \| (Name, Term, Term) \| …`, since a list resolves to a tuple only when the lengths match (§6.3) |

Order still matters. `Name` accepts the string `total-time`, so the literal must come first: in `Name | "total-time"` the literal is unreachable, and the union-order lint (§0004.5) says so. Because a literal is a single string, a tool can check that case exactly, by matching it against the earlier members.

---

## 0004.5 Lints

Additions to Appendix E:

| Rule | Level | Checks |
| --- | --- | --- |
| `pattern-anchor` | warning | a `@pattern` that starts with `^` or ends with `$`. In I-Regexp these are literal characters, so `"^[a-z]+$"` only matches strings that begin with `^`. Fix: drop them |
| `union-order` (extended) | warning | also: a literal that an earlier member of the same union accepts (`string \| "x"`, `Name \| "total-time"`, a repeated literal). Decided exactly, by resolving the literal against each earlier member |

Overlap between two *patterns* is not linted: deciding it means intersecting automata, which is possible but costly, and of little use for a warning. A tool MAY report it.

---

## 0004.6 Normative text for §6

### 0004.6.1 §6.5 Evolution

Add to the change table:

| Change | Classification |
| --- | --- |
| Remove `@pattern` | compatible: a widening |
| Add `@pattern`, or change its pattern text in any way | breaking |
| Widen a literal type to `string`, or to a `string` whose `@len` and `@pattern` the literal satisfies | compatible: a widening |
| Change a literal, or narrow a type to a literal | breaking |
| Widen `"a"` to `"a" \| "b"`, or append a literal to a union | compatible (existing rules for unions) |

Two clarifications:

- **Widening a union member is still governed by the union rule.** Removing a `@pattern` from a member that is not the last one can capture values that used to resolve to a later member, so it is breaking: `Variable | Name` → `string | Name` moves every name from position 2 to position 1. The existing "Widen a union member" row already says this; the new rows do not override it.
- **Pattern changes are classified by text.** Two patterns are the same if their texts are equal as strings. Equivalent spellings (`[a-z]` and `[a-z]{1}`) count as a change, and so does a strict widening (`[a-z]+` → `[a-z0-9]+`). Language inclusion between regular expressions is decidable, but it is PSPACE-complete and implementations would disagree on which proofs they attempt. Since §6.7 makes version numbers *checked claims*, every tool must reach the same verdict, so classification MUST NOT depend on such proofs. Tools MAY add an informational note when a change can be shown to be a widening. The literal rows are different: whether one string satisfies `@len` and `@pattern` is a plain match, so every tool gets the same answer.

### 0004.6.2 §6.6 Canonical schema text

Add: "Type attributes are written in the order `@range`, `@len`, `@pattern`. The argument of `@pattern` and a literal type are written as canonical quoted strings (§4.10)."

Consequently the fingerprint changes whenever a pattern's text changes, and does not change when only the escaping of its NOVA string changes (`"[?]"` and `"[\u003F]"` are the same pattern).

### 0004.6.3 §6.8 Descriptors and the meta-schema

`Type` gains two optional fields, and `Kind` gains one variant, appended:

```diff
-enum Kind = any | null | bool | int | i8 | i16 | i32 | i64 | u8 | u16 | u32 | u64 | float | decimal | rational | string | bytes | timestamp | duration | list | set | map | tuple | named | union
+enum Kind = any | null | bool | int | i8 | i16 | i32 | i64 | u8 | u16 | u32 | u64 | float | decimal | rational | string | bytes | timestamp | duration | list | set | map | tuple | named | union | literal

 record Type:
   ...
   range?: Range @id(8)
   len?: Len @id(9)
+  pattern?: string @id(10)    # an I-Regexp; only on `string`
+  literal?: string @id(11)    # the value of a `literal` type
```

Descriptor examples:

```
- {kind: !string, len: {min: 1, max: 63}, pattern: "[a-z0-9]([a-z0-9-]*[a-z0-9])?"}
- {kind: !literal, literal: "total-time"}
- {kind: !union, items: [{kind: !literal, literal: "undefined"}, {kind: !named, ref: FExp}]}
```

Rules the meta-schema cannot express, enforced when converting a descriptor to a schema (as today for `union`):

- `pattern` is present only when `kind` is `string`, and is a valid I-Regexp.
- `literal` is present if and only if `kind` is `literal`; such a type carries no `range`, `len` or `pattern`.

**Meta-schema version.** Both changes are compatible under §6.5 (optional fields and an appended variant), so the release rules of §6.7 require at least `0.3.2`, and `0.3.2` is also the right choice: under the `0.y.z` contract a `0.4.0` reader would be declared unable to read `0.3.1` descriptors, which is false. Old tools that read a new descriptor with a literal or a pattern reject it, which is the forward-compatibility behaviour §6.5 already describes for added variants.

### 0004.6.4 §12 Security

Add: "**Patterns.** Implementations MUST evaluate `@pattern` in time linear in the length of the string for a given pattern (for example with an automaton-based matcher), and MUST NOT pass schema patterns to a backtracking engine without such a guarantee. They SHOULD bound the size of a pattern and of its compiled form, and reject schemas that exceed the bound."

---

## 0004.7 Lint settings in schemas (separable)

### 0004.7.1 Problem

`nvf lint` on the PDDL schema now warns only about `field-case`. PDDL's keywords are kebab-case: besides `durative-actions`, there are `scale-up`, `at-most-once`, `is-violated` and others. They are identifiers (`[A-Za-z_][A-Za-z0-9_-]*`, Appendix A), so they are written bare, and `field-case` checks them against `snake_case`. A schema has no way to turn the rule off; today the PDDL schema carries a comment explaining the warnings.

The existing exemption does not help. Quoted field names are exempt only when they *need* quotes; writing `"scale-up":` changes nothing, because the canonical text (§6.6) and the descriptor write identifiers bare. Making the exemption depend on how a name was spelled would make presentation significant, and it would be lost in every round trip.

Documents already have the right mechanism: `@x-lint case=… allow=…` (Appendix E). Schemas only lack it.

### 0004.7.2 Proposal

1. **Schemas accept extension directives.** Before the first definition, a schema MAY contain directives whose names begin with `x-`, with the same rule as data documents (§4.2): implementations that do not understand one MUST ignore it. Any other unknown directive stays an error. Extension directives are not part of the canonical text, so they do not affect the fingerprint (§6.6), and they are not part of the descriptor (§6.8). Tools that write a `.novs` file back after patching it SHOULD keep them.
2. **`@x-lint` configures schema lints.** In a schema it takes the same settings as in a document and applies to the schema's own rules: `case=` selects the convention for `field-case` and `variant-case`, and `allow=` turns rules off.

For PDDL, the precise fix is to declare the convention the schema actually follows, since PDDL's vocabulary is kebab-case throughout and single words satisfy every convention:

```
@schema pddl@0.1.0
@x-lint case=kebab            # PDDL's own spelling: durative-actions, scale-up, is-violated
@root Domain
```

`@x-lint allow=field-case` remains available for schemas whose names follow no single convention.

### 0004.7.3 Alternatives considered

- **A per-definition attribute** (`record ScaleUp @x-lint(allow=field-case):`). More precise, but it adds attribute syntax for a non-normative concern. Deferred until a schema needs mixed conventions in one file.
- **Exempting quoted spellings.** Rejected above: canonicalization erases the quotes.
- **A lint configuration file next to the schema.** Splits one schema's meaning across two files that travel separately. Rejected.

---

## 0004.8 Interoperability (§11.2)

### 0004.8.1 JSON Schema

Proposed text for a new §11.2 entry, covering only the two features:

- **Writing.** `@pattern(p)` becomes `"pattern"` with `p` translated per RFC 9485 §5.3: every unescaped `.` outside a class becomes `[^\n\r]`, and the result is wrapped in `^(?:` and `)$`. Writers SHOULD also emit `"x-nova-pattern": p`, so that reading the JSON Schema back restores the exact pattern text (and thus the fingerprint). A literal becomes `{"type": "string", "const": "text"}`. A union whose members are all literals MAY become `{"type": "string", "enum": [...]}`, in member order.
- **Reading.**
  - `"x-nova-pattern"` wins when present.
  - Otherwise a `"pattern"` of the form `^(?:q)$` or `^q$`, where `q` is a valid I-Regexp that uses no anchors inside, becomes `@pattern(q)`, with every `[^\n\r]` turned back into `.`.
  - A pattern that is not anchored at both ends is a *search*, and becomes `@pattern("(.|\n|\r)*(q)(.|\n|\r)*")`, with the corresponding end dropped if only one end is anchored.
  - Anything outside I-Regexp (`\d`, lookahead, backreferences, flags) is reported as "not enforced", as today.
  - A string `"const"` becomes a literal. A string `"enum"` keeps today's mapping to an enum when every value is an identifier, and otherwise becomes a union of literals instead of being reported.

### 0004.8.2 Protobuf

Protobuf has no string constraints. A pattern-constrained string and a literal type both map to `string`. As with `@len` today, `novafile-proto` checks them when resolving values before encoding and when validating after decoding (§11.2). Unions remain rejected by the Protobuf adapter, so a union of literals is rejected with them; a single-literal field is unusual but valid.

### 0004.8.3 Bindings (§11.3)

- **TypeScript** maps literals to string-literal types and unions of literals to unions of them.
- **Rust** has no string-literal types. A binding maps a union of literals to a string-carrying enum with `#[serde(rename = "…")]` variants that serializes as the string, and a pattern-constrained string to a newtype that checks the pattern on construction and deserialization.

### 0004.8.4 Unaffected

The value model, the text syntax of data documents, the binary encoding (values stay plain strings), NOVA Lines, patches, queries and templates. A `~` match operator for query filters (§7.1) would be a natural follow-up, but it is not part of this proposal.

---

## 0004.9 Conformance cases

New and changed cases, in the existing layout (`conformance/README.md`). Expectations are generated by the reference implementation once it supports the proposal.

**`schema/patterns/`**

```
@schema patterns@1.0.0
@root R

type Name = string @pattern("[A-Za-z][A-Za-z0-9_-]*")
type Variable = string @pattern("[?][A-Za-z][A-Za-z0-9_-]*")

record R:
  term?: Variable | Name
  slug?: string @len(..8) @pattern("[a-z0-9]([a-z0-9-]*[a-z0-9])?")
  caret?: string @pattern("^[a-z]+")
  dot?: string @pattern("a.c")
  greek?: string @pattern("\\p{Lu}\\p{Ll}*")
  keys?: map<string @pattern("[a-z]+"), int>
```

| Case | Input | Expectation |
| --- | --- | --- |
| `valid/variable` | `term: "?x"` | resolves through `Variable` (position 1) |
| `valid/name` | `term: truck-1` | resolves through `Name` |
| `invalid/term-neither` | `term: "#t"` | one issue at `term`, "matches no member" |
| `invalid/partial-match` | `slug: ab_c` | issue at `slug`: the prefix `ab` matches, but the match is whole-string |
| `invalid/pattern-and-len` | `slug: abcdefghi` | issue at `slug`: matches the pattern, fails `@len(..8)` |
| `invalid/trailing-hyphen` | `slug: abc-` | issue at `slug` |
| `valid/caret-literal` | `caret: "^abc"` | valid: `^` is a literal character |
| `invalid/caret-not-anchor` | `caret: abc` | issue at `caret` |
| `invalid/dot-newline` | `dot: "a\nc"` | issue at `dot`: `.` excludes `\n` |
| `valid/dot` | `dot: "a☃c"` | valid: `.` matches any other scalar |
| `valid/unicode-category` | `greek: Αθήνα` | valid |
| `invalid/map-key` | `keys: {Ab: 1}` | issue at `keys` (the key) |

**`schema/literals/`**

```
@schema literals@1.0.0
@root R

type Name = string @pattern("[A-Za-z][A-Za-z0-9_-]*")
enum Agg = sum | max

record R:
  metric?: "total-time" | Name
  assign?: "undefined" | int
  op?: ("=" | ">=", int, int)
  both?: Agg | "sum" | "#t"
  maybe?: "x"?
```

| Case | Input | Expectation |
| --- | --- | --- |
| `valid/literal-first` | `metric: total-time` | the string `total-time`, through member 1 |
| `valid/name-second` | `metric: fuel-used` | through `Name` |
| `valid/assign-literal` | `assign: undefined` | the string `undefined` |
| `invalid/no-number-conversion` | `assign: "5"` | one issue at `assign`: a string is not an `int`, and not the literal |
| `valid/tuple-literal` | `op: [">=", 1, 2]` | resolves to a tuple |
| `invalid/tuple-literal` | `op: ["<", 1, 2]` | issue at `op` |
| `valid/enum-before-literal` | `both: sum` | resolves to the variant `!sum`: the enum member comes first |
| `valid/hash-t` | `both: "#t"` | the string `#t` |
| `valid/nullable-literal` | `maybe: null` | valid |
| `invalid/literal-case` | `assign: Undefined` | issue at `assign`: comparison is exact |

**`schema-invalid/`**

| Case | Schema line | Reason |
| --- | --- | --- |
| `pattern-invalid-regexp` | `x: string @pattern("(a")` | not an I-Regexp |
| `pattern-backreference` | `x: string @pattern("(a)\\1")` | outside I-Regexp |
| `pattern-multichar-escape` | `x: string @pattern("\\d+")` | outside I-Regexp |
| `pattern-on-int` | `x: int @pattern("[0-9]+")` | `@pattern` applies to strings only |
| `pattern-on-timestamp` | `x: timestamp @pattern("2026.*")` | not on types that strings resolve into |
| `pattern-twice` | `x: string @pattern("a") @pattern("b")` | at most one per type |
| `literal-with-attribute` | `x: "a" @len(1..)` | literals take no attributes |
| `schema-unknown-directive` | `@lint case=kebab` | unknown directive without `x-` |

**`schema-versions/`**

| Case | Old → new | `kind` |
| --- | --- | --- |
| `pattern-add` | `string` → `string @pattern("[a-z]+")` | breaking |
| `pattern-remove` | `string @pattern("[a-z]+")` → `string` | compatible |
| `pattern-change-wider` | `@pattern("[a-z]+")` → `@pattern("[a-z0-9]+")` | breaking (classified by text) |
| `pattern-respelled` | `@pattern("[?]x")` → `@pattern("\\?x")` | breaking (different pattern text) |
| `pattern-reescaped` | `@pattern("[?]")` → `@pattern("[\u003F]")` | none (same pattern, same canonical text) |
| `pattern-remove-first-member` | `Variable \| Name` → `string \| Name` | breaking (union position) |
| `pattern-remove-last-member` | `"total-time" \| Name` → `"total-time" \| string` | compatible |
| `literal-to-string` | `"a"` → `string` | compatible |
| `literal-to-matching-pattern` | `"total-time"` → `string @pattern("[a-z-]+")` | compatible |
| `literal-to-nonmatching-pattern` | `"#t"` → `string @pattern("[a-z-]+")` | breaking |
| `literal-change` | `"a"` → `"b"` | breaking |
| `string-to-literal` | `string` → `"a"` | breaking |
| `literal-append` | `"a"` → `"a" \| "b"` | compatible |
| `literal-prepend` | `Name` → `"total-time" \| Name` | breaking (captures a value that resolved to `Name`) |
| `x-directive-ignored` | old without, new with `@x-lint case=kebab` | none |

**Descriptors and fingerprints.** Round-trip cases (schema → descriptor → schema keeps the fingerprint) for a pattern, a literal, a union of literals and a schema with `@x-lint`. The `@x-lint` case also checks that adding the directive leaves the fingerprint unchanged.

**Lints** (reference tooling, not part of the normative suite): `pattern-anchor` on `"^[a-z]+$"`; `union-order` on `Name | "total-time"` and on `"a" | "a"`; no `field-case` finding for `scale-up` under `@x-lint case=kebab`.

---

## 0004.10 Open questions and future work

1. **Other literal kinds.** Integer, boolean and `null` literals (`3`, `true`) in type position. Cheap to add, but they would make `null` both a kind name and a literal, and `int @range(3..3)` already exists. Deferred until there is a use.
2. **Tuples with a rest element** (`(Name, Term...)`), which would close the last PDDL gap: a typed head followed by any number of terms. JSON Schema calls this `prefixItems` plus `items`.
3. **Pattern inclusion as a tool feature.** An informational "this pattern change only widens" note in `nvf schema check`, never affecting the classification.
4. **Query filters.** A `[?name ~ "pattern"]` filter operator (§7.1), using the same dialect.
5. **Bytes patterns.** Matching over bytes needs a byte-oriented dialect that I-Regexp does not define. Out of scope.
