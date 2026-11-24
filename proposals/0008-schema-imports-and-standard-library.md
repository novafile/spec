# NOVA Proposal 0008: Schema imports and a standard library

| | |
| --- | --- |
| Status | Draft proposal for discussion. Not normative until merged into SPEC.md. |
| Targets | §6.1 (imports, attributes on alias references), §6.4 (validation messages), §6.5 (evolution), §6.6 (canonical text, fingerprints), §6.7 (reserved names), §6.8 and `meta/schema.novs` (descriptors), §6.9 (bundled schemas), §11.2 (JSON Schema), §11.3 (bindings), Appendix C.14, Appendix E (lints), new `meta/std.novs`, conformance suite |
| New kinds / tags / directives | none in the value model; schema directive `@import`; bundled schema `novafile.dev/std` |
| Date | 2026-11-24 |
| Reference implementation | nova branch `feature/imports-std-classification` implements everything below except 0008.6 and the `vendored-drift` and `windows-reserved-path` lints |

---

## 0008.0 Summary

`@pattern` (§6.1) lets a schema say which strings a type accepts. It cannot say what those strings *are*. Every schema that holds UUIDs, URIs, e-mail addresses or phone numbers copies its own regex. Schemas have no imports (Appendix C.14, 0003 OQ 8, 0005 OQ 4), so nothing ties the copies together, and code generators and the JSON Schema mapping cannot tell a UUID field from any other patterned string.

An earlier draft of this proposal added `@format(name)`, a string constraint whose meaning is a pattern fixed by the specification. This version replaces it with two things the specification already points towards:

1. **Schema imports**: `@import name@version[#fingerprint] as alias`, resolved with the lookup order of §6.9.
2. **A standard library**: an ordinary schema, `novafile.dev/std`, that implementations bundle the way they bundle the meta-schemas. `novafile.dev/…` is already reserved for "schemas this specification defines" (§6.7).

The standard library holds **types**, not functions. It is unrelated to the template function library of proposal 0006.

```
@schema acme.example/crm@1.0.0
@import novafile.dev/std@0.1.0 as std

type Email = std.Email @personal          # classification stays the user's policy (0009)

record Contact:
  id: std.Uuid @key @id(1)
  name: std.Name @len(..200) @id(2)
  email?: Email @id(3)
  phone?: std.E164 @id(4)
  attachments?: list<std.PortablePath> @id(5)
```

| Facet | Recommendation |
| --- | --- |
| Import syntax | `@import name@version[#fingerprint] as alias`, after `@schema`; references are `alias.Name` |
| Prelude | None. Every use of std is an explicit, versioned import |
| Canonical text | Keeps the import with its fingerprint; tools fill the fingerprint in. Imported definitions are not expanded |
| Evolution | `nvf schema check` resolves imports on both sides and compares the effective types (§6.5) |
| Refinement | Attributes on a reference to an alias intersect with the alias's own, along the whole alias chain: all constraints hold. Relaxes "at most one `@pattern` per type" |
| Bundling | Implementations bundle every released std version. Never fetched. The first version is `0.1.0` |
| Std contents | Fixed, regular, widely needed, registry-free, policy-free types (0008.3.3) |
| Fixing a std type | A MAJOR version of std, never a renamed type |
| JSON Schema | std types map to `"format"` where JSON Schema has one, always with `"pattern"`; or to a `$ref` into the published std JSON Schema |
| Rejected | `@format(name)`, an implicit prelude, new value kinds, normalizing resolution, semantic checks |

## 0008.1 Motivation

1. **Duplication.** `type Uuid = string @pattern("[0-9a-f]{8}-…")` gets rewritten per schema, with small differences. Uppercase is sometimes allowed and sometimes not, and the nil UUID is sometimes excluded. Two schemas that "both hold UUIDs" then disagree on validity.
2. **Lost intent.** A pattern is opaque to tools. A code generator cannot map it to `uuid::Uuid`, and the language server cannot offer a type-aware hover.
3. **JSON Schema interop.** `novafile-schemars` reads `"format"` today and reports it as "is not enforced" (`from_json.rs`). Round trips lose the information.
4. **Conventions that live in prose.** 0003's label and annotation conventions (`QualifiedKey`, `Labels`, `Annotations`) must be copied into every schema that follows them. 0003 OQ 8 asks for well-known types such as `nova.QualifiedKey`.

A standard library would solve the first and fourth points by itself, but only imports give its types an identity (`novafile.dev/std.Uuid`) that tools can recognise, which is what the second and third points need.

## 0008.2 Prior art

| System | Approach | Lesson |
| --- | --- | --- |
| JSON Schema 2020-12 `format` ○ | Named formats; annotation-only by default, assertion opt-in | Implementations disagreed on what `email` and `uri` mean, so the spec stopped requiring enforcement. A format without one fixed definition is not a checked claim |
| OpenAPI `format` ○ | Open set (`password`, `byte`, `binary`, vendor values) | An open registry mixes validation (`uuid`) with UI hints (`password`). See 0009 for the second |
| XSD built-in types (`anyURI`, …) ○ | Fixed lexical spaces in the spec | Fixed definitions work; `anyURI` was later loosened in place, which broke validators that had relied on it |
| Protobuf well-known types ○ | `google.protobuf.Timestamp` etc. as ordinary imported messages; no UUID or URI type | Well-known types as ordinary, imported definitions work. Where none exists, every ecosystem invents its own |
| HTML "valid e-mail address" ○ | A deliberately simplified grammar, given as a regex | A *willful* simplification that is precise beats an "RFC 5322 compliant" claim that no two implementations meet |

Entries marked ○ are from background knowledge and were not re-read for this draft, as in 0003.

The lesson is that a named string type is useful exactly to the extent that its definition is fixed and identical across implementations, and that a fix must not change the meaning of existing schemas in place. NOVA already has the tools for both: I-Regexp (§6.1) and versioned, fingerprinted schema references (§6.7).

## 0008.3 Design

### 0008.3.1 Imports

```
@schema acme.example/crm@1.0.0
@import novafile.dev/std@0.1.0 as std
@import acme.example/common@2.3.0#sha256:… as common
```

- `@import` directives follow `@schema` and precede all definitions. Each names an exact version, never a range (§6.7), and binds an alias, which is an identifier. Aliases are unique within the schema and MUST NOT collide with a definition name.
- Imported definitions are referenced as `alias.Name` anywhere a type name may appear. Qualified references are never ambiguous with local names, since local names contain no `.`.
- Imports are resolved with the lookup order of §6.9, but for **exactly** the named version. A document's `@schema` lookup may pick the newest readable version (§6.7); an import never does, since the importing schema's fingerprint pins the imported content. A reference with a fingerprint MUST match it. An unresolvable import makes the schema invalid.
- Only definitions are imported. Inside the importing schema, the definitions an imported schema itself imports stay reachable as `alias.inner.Name`, since the imported definitions refer to them. Whether the importing schema may name them directly is OQ 2.
- Import cycles are an error. Implementations MAY bound the import depth and the number of imported definitions (each alias copies the definitions below it, so the count can grow exponentially); the reference implementation allows depth 16 and 10 000 definitions.
- `@pattern` on a reference requires the alias to be a `string` alias. Since the alias may be imported, this check runs once imports are resolved, not while parsing.

### 0008.3.2 Decisions imports force

**Explicit import, not an implicit prelude.** A prelude ties a schema's meaning to whichever implementation reads it. That is the same objection that rules out redefining a named format in place. An explicit, versioned import pins the meaning.

**Canonical text keeps the reference, with its fingerprint.** The alternative is expanding the imported definitions into the canonical text (§6.6). Keeping the reference has two advantages:

- The user schema's fingerprint transitively pins the imported schema's content.
- The qualified identity `novafile.dev/std.Uuid` survives, so code generators and the JSON Schema writer can recognise it.

Tools fill in the fingerprint, so authors can write the import without one. Canonical text writes imports in the order `@import` lines appear, each with its fingerprint.

**Evolution compares resolved types.** `nvf schema check` resolves imports on both sides and classifies the effective definitions per §6.5. Bumping `std@1.0.0` to `1.1.0` is not breaking in itself. It is breaking only if a type the schema actually uses changed incompatibly.

**Refinement of alias references.** `std.Name @len(..200)` has to mean "the alias plus this constraint", and the specification does not say that today. Attributes on a reference to an alias (local or imported) are an **intersection**: every constraint of the alias and every constraint of the reference must hold. This applies to every link of an alias chain: for `type A = B @len(..10)` and `type B = string @pattern("[a-z]*")`, a value of `A` satisfies both. §6.3 MUST say so. Before this proposal the reference implementation applied only the use site and the end of the chain and dropped the middle links, which a refinement of an imported alias relies on; fixing that makes some documents that validated before invalid. This relaxes "at most one `@pattern` per type" (§6.1): a refinement may add a second pattern, and both must match. Within one type expression, at most one `@pattern` remains the rule. Without this, std types cannot be narrowed, and people will copy them instead.

**Bundled, never fetched.** Implementations ship every released std version, since it is a few kilobytes. Schemas using std then validate offline, and the §6.9 fetch rules never come into play. This changes two places:

- §6.7, reserved names table, `novafile.dev/…` row, "Fetched" column: "the meta-schemas and `novafile.dev/std` never, since implementations bundle them; others like any qualified name".
- §6.9 step 2: implementations MUST bundle `novafile.dev/std` in every released version up to the newest they implement. A catalog source MUST NOT shadow a bundled version, as for the meta-schemas.

**Fingerprints are computed on linked schemas.** Before linking, an import may lack its fingerprint, so the canonical text, and with it the fingerprint and every revision derived from it, exists only once imports are resolved.

**Pattern size.** The literal `URI / relative-ref` translation of RFC 3986 is about 5 700 characters; regrouped so the authority appears once, `UriReference` is 3 001. Implementations MUST accept I-Regexp patterns of at least 4 096 characters (the reference implementation's limit), or std cannot be loaded.

**Validation messages** name the type, not the pattern: `people[2].phone: "030 1234567" is not a std.E164`. The pattern MAY follow as detail.

### 0008.3.3 What belongs in std

Admission criteria:

1. One fixed, regular definition.
2. Widely needed.
3. No dependency on a registry that changes over time.
4. No policy.

Where a standard is case-insensitive or allows several spellings, the std type accepts **only the canonical spelling**. This follows §6.3's rule that resolution performs no conversions besides those listed, and it keeps equality (§2.12) meaningful: two equal UUIDs are equal strings.

| Type | Source | Definition (I-Regexp as NOVA string content, or range) | Notes |
| --- | --- | --- | --- |
| `Uuid` | RFC 9562 §4 | `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}` | Lowercase only, since RFC 9562 recommends lowercase output. Any version and variant, including nil and max. No braces, no `urn:uuid:` prefix |
| `Urn` | RFC 8141 §2 (assigned-name only) | `urn:[A-Za-z0-9][A-Za-z0-9-]{0,30}[A-Za-z0-9]:([A-Za-z0-9._~!$&'()*+,;=:@-]\|%[0-9A-Fa-f]{2})([A-Za-z0-9._~!$&'()*+,;=:@/-]\|%[0-9A-Fa-f]{2})*` | Lowercase `urn:` only. No r-, q- or f-components (OQ 5) |
| `Uri` | RFC 3986 §3 `URI` | *(generated mechanically from the RFC 3986 ABNF; see 0008.3.5)* | Absolute URI. Not a WHATWG URL: no whitespace stripping, no backslash rewriting, no IDNs in Unicode form |
| `UriReference` | RFC 3986 §4.1 `URI-reference` | *(generated as above)* | Absolute or relative |
| `Email` | HTML Living Standard, "valid e-mail address" ○ | `[A-Za-z0-9.!#$%&'*+/=?^_\`{\|}~-]+@[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?([.][A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*` | ASCII only; internationalized addresses (RFC 6531) are out of scope. Case is preserved, since local parts are case-sensitive (RFC 5321). Applications that compare addresses normalize themselves (§12) |
| `E164` | ITU-T E.164 | `[+][1-9][0-9]{1,14}` | Syntax only: at most 15 digits and no leading zero. Says nothing about whether a country code is assigned or a number is reachable |
| `NonBlank` | — | `(.\|\n\|\r)*[^\p{Z}\p{Cc}\p{Cf}](.\|\n\|\r)*` | At least one visible character, may span lines. See 0008.3.4 |
| `Name` | — | `[^\p{Z}\p{Cc}\p{Cf}](.*[^\p{Z}\p{Cc}\p{Cf}])?` | Trimmed and single-line: no leading or trailing whitespace, so `"admin"` and `"admin "` cannot both appear |
| `PortablePath` | POSIX portable filename set | `[.]?[A-Za-z0-9_]([A-Za-z0-9._-]*[A-Za-z0-9_-])?(/[.]?[A-Za-z0-9_]([A-Za-z0-9._-]*[A-Za-z0-9_-])?)*` plus `@len(1..1024, utf8)` | Relative, `/`-separated. See 0008.3.4 for what it does and does not rule out |
| `Slug`, `QualifiedKey`, `Labels`, `Annotations` | 0003 conventions | as defined in 0003 | Replaces copying 0003's conventions into each schema. Not in `0.1.0`: 0003 has no fixed definitions yet |
| `Port` | — | `int @range(0..65535)` | |
| `SemVer` | SemVer 2.0.0 | the official regular expression, translated to I-Regexp | The official expression is regular, so it translates directly |
| `Hostname` | RFC 1123 | to be written (OQ 3) | Not in `0.1.0` |
| `Sha256Hex` | — | `[0-9a-f]{64}` | Lowercase only |
| `CurrencyCode`, `CountryCode` | ISO 4217, ISO 3166-1 alpha-2 | `[A-Z]{3}`, `[A-Z]{2}` | Shape only. The ISO lists change, so std must not enumerate them |

(The `\|` in the table is Markdown escaping; the patterns contain plain `|`. The backtick in the `Email` class is literal. As in §6.1, `\n`, `\r` and `\p{…}` are written as `\\n`, `\\r`, `\\p{…}` inside a NOVA string.)

### 0008.3.4 Notes on the text and path types

**`NonBlank` and `Name`.** Non-empty alone is `@len(1..)`. "Not only whitespace" needs a pattern. I-Regexp has no `\s`, and ASCII `\s` would be wrong anyway: NBSP, U+3000 and friends would slip through. `\p{Z}` (space, line and paragraph separators) together with `\p{Cc}` covers the Unicode `White_Space` property plus the other control characters. `\p{Cf}` also catches strings that consist only of invisible characters, such as ZWSP and BOM. `@len(1..)` is redundant on both types, since the patterns require a character.

- `\p{…}` follows the implementation's Unicode version (§6.1). std MUST say so in the types' documentation: these two are the only std types whose meaning is not fully fixed by the std version.
- `\p{Cf}` includes ZWJ, so a lone ZWJ counts as blank. An emoji sequence containing ZWJ still passes, because it contains visible characters.

**`PortablePath`.** Each segment is restricted to the POSIX portable filename set (`A–Z a–z 0–9 . _ -`), with an optional leading dot (`.github`), no `.` or `..` segment, no leading `-`, and no trailing `.` (Win32 strips it). The pattern rules out:

- absolute paths, drive letters (`C:`), UNC and `\\?\` prefixes, and backslashes;
- empty segments (`a//b`) and traversal (`..`), the security-relevant part when a tool joins the value onto a base directory;
- segments starting with `-` (`-rf`), which avoids argument injection;
- `:`, so no NTFS alternate data streams;
- Windows-forbidden characters (`<>:"|?*`, controls) and the trailing dot.

It cannot express, and std documents as unchecked:

- **Windows reserved names.** `CON`, `NUL`, `COM1`, `LPT1` and so on are reserved case-insensitively, *including with an extension* (`nul.txt`). I-Regexp has no lookahead or complement. A complement pattern could be generated mechanically but would be unreadable; this is a lint or an application check.
- **Case collisions.** `README.md` and `readme.md` in the same set are distinct NOVA strings but the same file on default macOS and Windows volumes. That is a property of the collection, not of one string.
- **Per-segment byte limits.** NAME_MAX is 255 bytes. `@len(…, utf8)` bounds the whole string, and `{1,255}` in a pattern counts scalars, not bytes. With an ASCII-only set the two coincide, which is another argument for the conservative character set.

Symlinks, existence and "inside this directory after resolution" stay host checks. No schema can see the filesystem.

### 0008.3.5 What stays out of std

- **Classification.** If `std.Email` carried `@personal` (0009), nobody could declassify it. The user writes `type Email = std.Email @personal`.
- **Domain records with opinions**, such as `Money`, `Address` and `GeoPoint`. Every organization models these differently, and a std record invites the bikeshedding that a small alias library avoids.
- **Anything needing external validity checks**, such as assigned country codes or valid BCP 47 subtags.
- **`Date`, `Time`.** Dates already have `timestamp`.

### 0008.3.6 How std is maintained

- std lives in the spec repository as `meta/std.novs`, an ordinary named schema `novafile.dev/std@x.y.z`, with a doc comment per type that names its source.
- `Uri` and `UriReference` are generated from the RFC 3986 ABNF by a script checked into the spec repository, and the generated pattern is what gets committed.
- The conformance suite contains accept and reject vectors for every std type. The RFC 3986 vectors come from §5.4 (reference resolution examples) and from known edge cases: IPv6 literals, empty authority, percent-encoding.
- std starts at `0.1.0`. A bundled version can never change and never be shadowed, so releasing a draft as `1.0.0` would freeze it; `1.0.0` follows once the definitions have been reviewed.
- **A wrong definition is fixed by a version that §6.5 classifies as breaking**: a MAJOR version from `1.0.0` on, a MINOR version while std is `0.y.z`. A fixed `Email` pattern in `1.x` becomes `std@2.0.0`. Schemas pinned to `1.x` keep their meaning, and `nvf schema check` reports the change when they bump. A schema's meaning never changes because the validator was upgraded, and no `email2`-style names accumulate.
- Adding a type is a MINOR version. Widening a type (accepting uppercase UUIDs, say) is a MINOR version under §6.5, but SHOULD be avoided, since it changes the meaning of the name for every schema that bumps.

### 0008.3.7 Canonical text, descriptor, evolution

- **Canonical text (§6.6).** `@import` lines follow `@schema`, in source order, each with its fingerprint. References are written `alias.Name`. Type attributes keep the order `@range`, `@len`, `@pattern`.
- **Descriptor (§6.8).** Schema descriptors gain `imports?: list<Import>`, with `record Import: alias @key, schema: string`, where `schema` is the full reference `name@version#fingerprint`. Type references need no new field: a qualified name such as `std.Uuid` is an ordinary reference string. The meta-schema becomes `novafile.dev/meta/schema@0.3.4`, which also carries the classes of 0009.
- **Evolution (§6.5)**, new rows:

  | Change | Classification |
  | --- | --- |
  | Add an import | compatible (no type uses it yet) |
  | Bump an import's version | classified by the effective types of every definition that uses it |
  | Replace a local alias with a std type of identical effective definition, or the reverse | compatible; the qualified identity changes, which `nvf schema check` reports as a note |
  | Add an attribute to a reference (refinement) | breaking, as for any added constraint |
  | Rename an import alias | compatible: the effective definitions do not change |

  "Effective definition" means the canonical text of the definition with every reference resolved through imports, compared for the imported definitions the schema actually uses.

### 0008.3.8 Interoperability

**JSON Schema (§11.2).**
- *Writing:* a std string type always becomes `"pattern"` (translated per RFC 9485 §5.3, as for `@pattern`) plus `"x-nova-type": "novafile.dev/std.Uuid"` on its `$defs` entry. Non-string std types (`Port`) get `"x-nova-type"` and their range only. `"x-nova-type"` carries no version; a reader takes the newest std version it bundles. For `Uuid`, `Uri`, `UriReference` and `Email`, the writer also emits `"format"` (`uuid`, `uri`, `uri-reference`, `email`). The JSON Schema definitions are broader than std's (uppercase UUIDs, RFC 5321 mailboxes), so `"pattern"` is what makes a JSON Schema validator agree with NOVA. Writers MAY emit a `$ref` to the published `https://novafile.dev/std/0.1.0.schema.json#/$defs/Uuid` instead, per the 0005 mapping.
- *Reading:* `"x-nova-type"` wins, on a `$defs` entry or inline. Otherwise `"format"` with one of the four names above becomes the std type, with a note that the std definition is narrower, and the schema gains a std import. Any other `"format"` stays "not enforced".

**Protobuf.** Unchanged: `string`. Generators MAY emit the std type name as a comment. An imported definition becomes a message or enum named `alias_Name` in the importing schema's package.

**Bindings (non-normative).** `novafile-derive` MAY map `std.Uuid` to `uuid::Uuid` and `std.Uri` to `url::Url` behind cargo features. A binding type that normalizes, such as `url::Url`, which follows WHATWG, MUST NOT be used for serialization unless it round-trips the canonical spelling. Otherwise documents change when they are rewritten.

### 0008.3.9 Lints (Appendix E)

- `std-hint`: a `string` field named `uuid`, `*_uuid`, `email`, `url`, `uri` or `phone` whose type is not a std type (hint, off by default; switched on with `@x-lint enable=std-hint`). A local alias of a std type counts as a std type.
- `std-restated`: a local alias whose effective definition, ignoring its class, equals a type of the newest bundled std (hint).
- `vendored-drift`: a definition marked `@x-std` that no longer matches the std version it names (warning; 0008.6).
- `windows-reserved-path`: a `PortablePath` value whose segment is a Windows reserved name (warning; document lint, so the linter needs schema resolution).

## 0008.4 Idioms that are not std (non-normative)

**Host-native paths.** Machine-specific config and logged paths cannot be validated portably. Make the platform explicit instead of guessing from the string:

```
type RawPath = string | bytes      # string first: text stays text; @bytes(…) only for non-UTF-8 names

enum HostPath:
  posix(RawPath)
  windows(string @len(1..32767, utf16))
```

- **Linux** paths are arbitrary bytes except NUL. Non-UTF-8 names cannot be NOVA strings, hence the `bytes` member, the same idea as Rust's `OsString`. Union order matters (§6.3): with `string` first, a text path never resolves to bytes.
- **Windows** paths are UTF-16 and may contain unpaired surrogates, which NOVA strings cannot hold. That is rare enough to call out of scope; otherwise it is bytes again, holding WTF-8. `@len(…, utf16)` is the right unit for the 32767 limit, or 260 for legacy MAX_PATH.
- **macOS** (HFS+, default APFS) is normalization-insensitive: `Müller.txt` in NFC and in NFD are two NOVA strings but one file. §12 already says NOVA does not normalize, and NFC-ness is not a pattern. The options are application-side normalization or a future attribute such as `@normalized(nfc)`.

A third option for interchange is `file:` URIs (RFC 8089) as `std.Uri`. Percent-encoding makes non-UTF-8 bytes representable as plain ASCII strings, at the cost of readability and the long-standing ambiguity of Windows drive letters in file URIs.

Use `std.PortablePath` for anything in documents meant to travel between machines, and `HostPath` only where a document genuinely describes one machine.

## 0008.5 YAGNI / rejected

- **`@format(name)`** (the earlier draft of this proposal). A string attribute whose meaning is a pattern fixed in a new Appendix F, with names `uuid`, `uri`, `uri-reference`, `urn`, `email`, `e164`, frozen definitions, and a rename (`email2`) plus a `deprecated-format` lint for fixes. With imports and std, everything it offered comes for free: stable identity (`std.Uuid` is a qualified name), frozen meaning (a fix is a MAJOR version of std, not a rename), and composition (`std.Uri @secret`, given the refinement rule). What `@format` would keep is a slightly terser spelling, which is not worth a second mechanism.
- **An implicit prelude.** See 0008.3.2.
- **New value kinds** (`@uuid("…")`). A typed literal with a 16-byte binary payload would save about 20 bytes per value. It would also add a value kind, a binary tag (§5.1), a JSON mapping and an equality rule, and every binding would have to implement it. Compactness for repeated identifiers already comes from back-references (§5.3) and is a better fit for future positional binary work (Appendix C.1).
- **Normalizing resolution** (uppercase UUID → lowercase). This violates §6.3, and keys and set elements would collide after resolution.
- **Semantic checks** (country-code tables, DNS resolution, MX lookups). These are not functions of the string and not stable over time.
- **`NonBlank` as a frozen format.** `\p{…}` tracks the Unicode version, so it could never be frozen. As a std type it is documented as Unicode-dependent instead.

## 0008.6 Stopgap until imports land

`nvf schema vendor novafile.dev/std@0.1.0 Uuid` copies definitions into the schema, marked with `@x-std novafile.dev/std@0.1.0.Uuid`. The `vendored-drift` lint checks that the copies have not drifted. This gives consistency, but no identity for code generators and no JSON Schema `"format"`.

## 0008.7 Open questions

1. **Import syntax.** `@import name@version as alias`, or a mandatory alias derived from the last name segment (`std`)? Should a schema be able to import single definitions (`@import novafile.dev/std@0.1.0 {Uuid, Email}`)?
2. **Re-exports.** Should a schema be able to re-export what it imports, so that a company-wide `acme.example/common` can wrap std?
3. **Further std types.** `Hostname` (RFC 1123), `Ipv4`, `Ipv6` (RFC 4291 text form, with RFC 5952 as the canonical form), `QualifiedKey` beyond 0003. Which meet the admission criteria?
4. **Windows reserved names** in `PortablePath`: keep them unchecked (lint only), or include a generated complement pattern?
5. **`Urn`**: include the RFC 8141 r-, q- and f-components, or keep assigned-names only?
6. **Uppercase UUIDs.** Should `Uuid` accept uppercase after all, given how much existing data has it? (Recommendation: no. Use `@pattern` for legacy data, or a `UuidAnyCase` type if demand is real.)
7. **Descriptor shape.** Should descriptors (§6.8) carry imports as references only, or also the resolved definitions, so that schema-as-data tools work without a resolver?
8. **Refinement and `@pattern`.** Is intersection the right rule for all attributes, including `@range` and `@len` on references, or only for `@pattern`?
9. **Identity of non-std imports in JSON Schema.** `"x-nova-type"` names std types only. A schema read back from JSON Schema loses the identity of every other imported definition. Should `"x-nova-type"` carry any qualified name, with a version?
10. **Std types behind another import.** A Protobuf comment or JSON Schema `"format"` for `c.std.Uuid` (std reached through `acme.example/common`) needs the model to keep transitive import identities; the reference implementation keeps only direct ones.
