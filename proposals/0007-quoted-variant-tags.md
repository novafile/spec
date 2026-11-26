# NOVA Proposal 0007: Quoted variant tags

| | |
| --- | --- |
| Status | Merged into SPEC.md (§2.11, §4.7, §4.10, §5.1, §6.1, §6.6, §11.2, Appendices A, C and E) on 2026-11-26, within language version 0.1. This document keeps the rationale; SPEC.md is normative. |
| Targets | §2.11 (variants), §4.7 and §4.10 (text syntax, canonical text), §5.1 (decoder rejections), §6.1 (enum syntax), §6.6 (canonical schema text), §11.2 (Protobuf), §11.3 (bindings), Appendices A, C and E, conformance suite |
| New kinds / tags / directives | none. The set of valid variant tags grows from identifiers to every non-empty string |
| Depends on | nothing. Resolves the rest of [issue #1](https://github.com/novafile/spec/issues/1) |
| Date | 2026-11-19 |

---

## 0007.0 Summary

A variant tag is an identifier today (§2.11), so `=`, `>=`, `at start` or `?t` cannot be enum variants. Record keys and schema field names have the same restriction lifted already: they are identifiers or quoted strings. This proposal does the same for variant tags.

```
!active                       # unchanged
!"at start"([at, "?t", depot])
!"="(("?duration", 2))
```

| Facet | Recommendation |
| --- | --- |
| Valid tags | every non-empty string, compared as strings without normalization, like record keys |
| Text | `!` followed by an identifier or a quoted string; the canonical writer quotes only tags that are not identifiers |
| Binary, JSON, revisions | no change. Both encodings already carry tags as strings, and every value that is valid today keeps its encoding and revision |
| Schemas | `enum Op = and(Formula[]) \| "="((Term, Term)) \| "at start"(Formula)`, by the rule that already applies to quoted field names |
| Empty tag | still invalid in every representation |
| Protobuf | quoted tags are rejected, as quoted field names are |
| Bindings | a renamed variant (`#[serde(rename = "at start")]`) maps to that tag instead of being an error |
| Compatibility | purely additive. Documents that are valid today keep their meaning; documents with non-identifier tags, invalid today, become valid |

---

## 0007.1 Motivation

[pddl-rs](https://github.com/sunsided/pddl-rs) serializes PDDL with serde, and its formulas have the shape of many s-expression and JSON-AST encodings: a keyword maps to its arguments, and keywords include operators and phrases.

```
precondition:
  and:
    - [at, "?t", "?from"]
    - not: ["=", "?from", "?to"]
condition:
  "at start": [at, "?t", depot]
duration:
  "=": ["?duration", 2]
```

Issue #1 asked for two things to type this data. Unions and quoted field names are in the specification now (§6.1). Quoted variant tags are not, so the operator vocabulary has to be modelled as a union of single-field records:

```
type Formula = Atom | And | Not | Eq | AtStart
type Atom = list<Term>
record And:
  and: list<Formula>
record Eq:
  "=": (Term, Term)
record AtStart:
  "at start": Formula
```

That works, because records are closed and each one accepts only its own key, but it has costs:

- **The vocabulary is not one type.** It is a union of as many records as there are operators, each one a definition with a made-up name. An enum states the closed set directly.
- **No `@id`s per operator.** Enum variants carry `@id` for evolution checks and Protobuf numbering (§6.5, §11.2). Union members are positional and carry none, so reordering the union is breaking.
- **Bindings disagree with the data.** In Rust, the natural model is an enum with `#[serde(rename = "at start")] AtStart(Formula)`. §2.11 requires a binding to report an error for that rename, so the Rust type and the NOVA type have different shapes.
- **Other formats already carry such tags.** JSON spells a variant with a payload as `{"tag": payload}`, where any string is a valid key. A tag such as `"at start"` round-trips through JSON as data, but cannot become a NOVA variant.

The restriction buys little. Binary encodes a tag as a string payload, JSON as a string or an object key, and the text syntax already has quoted strings everywhere a key appears. The identifier rule exists only in the value model and in the `!name` text form.

---

## 0007.2 The value model (§2.11)

A variant is a **tag**, which is a non-empty string, and an optional payload value. Tags are compared as strings: `!"active"` and `!active` are the same value. No normalization is applied (§2.8).

The empty string stays invalid in every representation: parsers and decoders MUST reject it, and implementations MUST NOT produce it. `!""` reads as a mistake, not as a value anyone means, and every other format that NOVA maps to has a non-empty spelling for every tag it can express.

All other rules stay: a schema's `enum` constrains which tags and payloads are permitted, and in a positional document (§4.12) the tag `_` is reserved, however it is written (`!_` and `!"_"` are the same tag).

## 0007.3 Text (§4.7, §4.10, Appendix A)

```
flow-value = … | "!" (name | quoted) ["(" flow-value ")"]
```

- A tag is written bare when it is an identifier, and quoted otherwise, exactly as a record key (§4.3): `!"at start"`, `!"="(1)`, `!"a\"b"`.
- The `(` of a payload follows the closing quote directly: `!"at start"(x)`. A space in between is an error, as it is after a bare tag.
- The block form of a variant payload (`variant-block`) takes the same tag syntax.
- **Canonical text** writes a tag bare if and only if it is an identifier, and otherwise as a canonical quoted string (§4.10). So `!"active"` and `!active` have the same canonical text.

## 0007.4 Binary (§5.1) and revisions

A variant's tag is already a `str` payload (tags `0x0F`, `0x10`). The encoding does not change. Decoders stop rejecting non-identifier tags and keep rejecting the empty tag:

> - ~~variant tags that are not identifiers (§2.11), such as the empty string;~~ the empty variant tag (§2.11);

Every value that is valid today has an identifier tag, so its canonical encoding and its revision are unchanged.

## 0007.5 JSON and other mappings (§11)

No change. A unit variant maps to its tag as a JSON string, and a variant with a payload to `{"tag": payload}`, for any tag: `!"at start"(x)` becomes `{"at start": x}`. In the other direction, a schema resolves such a record to the variant (§6.3).

Formats that write variants with loss warnings (YAML, TOML, CBOR) are unaffected.

## 0007.6 Schemas (§6.1, §6.3, §6.6, §6.8)

**Syntax.** A variant name is an identifier or a quoted string, by the rule that already governs field names:

```
enum Op:
  and(Formula[]) @id(1)
  not(Formula) @id(2)
  "="((Term, Term)) @id(3)
  "at start"(Formula) @id(4)

enum Cmp = "<" | "<=" | "=" | ">=" | ">"
```

The sentence "Enum variant names remain identifiers, since variant tags are identifiers in the value model (§2.11)" is removed from §6.1, and so is "tags are identifiers" in the comparison of literals and enums. That comparison still holds: an enum resolves a string to a variant, and a union of literals keeps the string.

**Resolution (§6.3)** is unchanged: a string that names a unit variant becomes that variant, and a single-field record whose key names a variant with a payload becomes that variant. `"="` resolves to `!"="` under `enum Cmp`.

**Canonical schema text (§6.6)** writes variant names bare when they are identifiers and otherwise as canonical quoted strings, as for field names. Fingerprints of existing schemas are unchanged.

**Descriptors (§6.8).** `VariantDef.name` is already a string, so the meta-schema does not change. Converting a descriptor back to a schema accepts any non-empty name.

**Evolution (§6.5)** needs no new rules. Renaming `"at start"` to `at_start` is renaming a variant, which is breaking.

**Literals and enums together.** A union can hold both: in `type T = "=" | Cmp`, the string `"="` resolves through the literal, because union members are tried in order (§6.3). The existing `union-order` lint reports the enum's `"="` as unreachable.

## 0007.7 Templates (§9)

Unchanged. Interpolating a unit variant inserts its tag (`${op}` with `!"at start"` inserts `at start`), and a template writes a quoted tag as a flow value like any other.

## 0007.8 Protobuf (§11.2)

Proto enum value names and `oneof` field names must be Protobuf identifiers. A schema whose enum has a quoted variant name that is not an identifier is rejected by `.proto` generation, with an error naming the enum and the variant, as a quoted field name is today. A quoted name that is an identifier (`"active"`) is the identifier.

## 0007.9 Language bindings (§11.3)

The requirement that a binding report an error when it could write a non-identifier tag, "for example after a binding-level rename to `at start`", is replaced by: "a binding writes the renamed tag; it MUST report an error for an empty one". In Rust:

```rust
#[derive(Serialize, Deserialize)]
enum Op {
    #[serde(rename = "and")]
    And(Vec<Formula>),
    #[serde(rename = "=")]
    Eq(Term, Term),
    #[serde(rename = "at start")]
    AtStart(Box<Formula>),
}
```

maps to `enum Op = and(Formula[]) | "="((Term, Term)) | "at start"(Formula)`, with no union of wrapper records.

## 0007.10 Lints (Appendix E)

`variant-case` exempts quoted variant names, as `field-case` exempts quoted field names: they exist for external vocabularies. No new lint is needed.

---

## 0007.11 Compatibility

- **Additive.** Every document, schema and binary value that is valid today is still valid, with the same value, canonical text and revision. Only inputs that are rejected today, because of a non-identifier tag, become valid.
- **Version.** Merged within 0.1, as the additive schema syntax of 0004 and 0010 was. A minor version would have been the textbook choice (§13.1), but while the major version is 0, minor versions must match exactly, so 0.2 readers would have rejected every document and binary frame declaring 0.1. A reader that predates the change rejects a quoted tag as a syntax error rather than misreading it.
- **It reverts a recent tightening.** §2.11 was just made explicit that non-identifier tags are invalid in every representation, and nova was changed to check tags wherever they enter a value. That change made the rule consistent; this one changes the rule. Implementations keep the single check point and change what it accepts: a non-empty string.
- **Reserved `@` tags.** Identifier-only tags guaranteed that no input could produce an implementation marker, such as the redaction placeholder `@redacted` (0009) or a template's classification wrapper. Allowing every non-empty string would have let `!"@redacted"` forge one, and an enum variant named `"@redacted"` would have let resolution turn a string into one. Tags beginning with `@` therefore stay invalid in data, the namespace text already uses for typed literals (`@set`, `@float(…)`).

---

## 0007.12 Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Keep the union of single-field records** (status quo) | Works, but needs a definition per operator, has no `@id`s, and disagrees with the natural binding type (§0007.1). Stays available |
| **Quoted names in schemas only**, mapped to identifier tags in values (`"at start"` stored as `!at_start`) | The value would differ from the data it came from, round trips through JSON would change keys, and the mapping rule (which characters become what) would be a new normalization |
| **A `@tag("at start")` attribute** on an identifier variant | Same problem: two names for one variant, one in the schema and one in the data |
| **`map<Op, V>` with `@len(1..1)`** | Loses the per-variant payload type: every operator would share one value type |
| **Allow the empty tag too** | No format needs it, and `!""` is far more likely a mistake than a value |
| **Restrict tags to "printable" strings** | Record keys have no such restriction, and the quoted form already escapes control characters. A second string class for tags would only be one more rule to implement |

---

## 0007.13 Conformance cases

| Directory | Case | Expected |
| --- | --- | --- |
| `text/valid/` | `quoted-variant-tags`: `!"at start"([at, "?t", depot])`, `!"="(1)`, `!"a\"b"`, and `!"active"` next to `!active` | the values; `!"active"` and `!active` have the same revision, and canonical text writes `!active` |
| `text/invalid/` | `empty-variant-tag`: `!""` | error |
| `text/invalid/` | `quoted-tag-space-before-payload`: `!"at start" (x)` | error |
| `binary/valid/` | `non-identifier-variant-tag`, moved from `binary/invalid/` (the tag `at start`) | the value |
| `binary/invalid/` | `empty-variant-tag` stays | error |
| `schema/quoted-variants/` | `enum Op` and `enum Cmp` above; valid documents with `{"at start": …}`, `"="`, `{"=": [a, b]}`; an invalid document with an undeclared operator | the resolved variants; the issue path |
| `schema-invalid/` | `enum-empty-variant-name`: `enum E = ""` | error |

---

## 0007.14 Normative text

The proposed changes to SPEC.md, in summary:

- **§2.11**: "A `variant` is a tag — a non-empty string — and an optional payload value." The paragraph on invalid tags keeps its MUSTs for the empty tag only, and binding renames to a non-empty tag become valid.
- **§4.7**: variants `!active`, `!"at start"(x)`; the tag is an identifier or a quoted string, as a key is (§4.3).
- **§4.10**: canonical text writes a tag bare if and only if it is an identifier.
- **§5.1**: decoders reject the empty variant tag (instead of "variant tags that are not identifiers").
- **§6.1**: variant names are identifiers or quoted strings, like field names; the two sentences that say otherwise are removed.
- **§6.6**: variant names are written like field names in canonical schema text.
- **§11.2** (Protobuf): enums with a variant name that is not an identifier are rejected.
- **§11.3**: renamed variants map to their tags; only the empty tag is an error.
- **Appendix A**: `"!" (name | quoted) ["(" flow-value ")"]`.
- **Appendix C**: item 12 is marked resolved.
- **Appendix E**: `variant-case` exempts quoted variant names.

---

## 0007.15 Open questions

1. **Paths and queries.** A path cannot name a variant's payload today; if it gains a segment for that, it needs the quoted form as well, as `name` already allows for fields (§7.1).
2. **Language bindings without rename attributes.** Languages whose enum names must be identifiers and that have no rename mechanism would need a generated name for `"at start"`. That is a binding concern, like quoted field names in such languages, and needs no rule in the format.
