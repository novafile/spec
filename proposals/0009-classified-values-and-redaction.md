# NOVA Proposal 0009: Classified values and redaction

| | |
| --- | --- |
| Status | Draft proposal for discussion. Not normative until merged into SPEC.md. |
| Targets | §6.1 (attributes), §6.4 (validation messages), §6.5 (evolution), §6.6 (canonical text), §6.8 (descriptors), §7.1 (filters), §7.3 (query responses), §7.5 (patch semantics, conflict reports), §7.6 (diffs), §8 (agent model), §9 and proposal 0006 (templates), §11.2 (JSON Schema, Protobuf), §12 (security), Appendix E (lints) |
| New kinds / tags / directives | none in the value model; schema attributes `@secret` and `@personal`; a response-only literal `@redacted` |
| Date | 2026-11-24 |
| Reference implementation | nova branch `feature/imports-std-classification`: schema language, resolution, redaction, CLI, query, patch, diff, templates, language server, JSON Schema, Protobuf and lints. Not done: a parse mode for redacted documents, binding types (0009.9) |

---

## 0009.0 Summary

Agents read NOVA documents through `@get` (§8.1), and so do CLI pipelines and language servers. None of them can currently tell that a field holds a credential or personal data. One `@get services[id=api]` puts a database password into a model's context, a log or a transcript.

This proposal lets **schemas classify values**, and makes **every egress path redact classified values by default**. Revealing them is an explicit act by a human or the host, never a parameter the agent controls.

| Facet | Recommendation |
| --- | --- |
| Where classification lives | In the schema, as type attributes `@secret` and `@personal` (also on record definitions). Never in the document |
| Classes | `secret`: credentials and keys; never needed to reason about. `personal`: data about people; often needed for correlation, rarely in clear |
| What redaction is | A property of *reading*. Storage, canonical encoding, revisions of stored documents and binary frames are unchanged |
| Placeholder | `@redacted` (secret) / `@redacted("p:…")` (personal, keyed pseudonym). Valid only in output; rejected by parsers of data documents and by patch application |
| Default | Redact in every tool that emits values: `nvf get`, `nvf convert`, `nvf fmt --to …`, `nvf hash`, `nvf stats`, diffs, validation messages, LSP, template rendering to stdout |
| Reveal | CLI flag for humans (`--reveal`, `--reveal=personal`, `--reveal=PATH`); for agent hosts, host policy bound per tool call (like §7.5 scopes), never a request parameter |
| Side channels closed | Filters as oracles, `@key` and set/map-key positions, validation and conflict messages, revisions over low-entropy secrets, placeholders written back, template derivations |
| Threat model | Tier 1: preventing accidental exposure (CLI, LSP, agents with a shell). Tier 2: a boundary for hosts that mediate all access. Only tier 2 claims anything against a deliberate adversary |
| Rejected | In-document markers, encryption, heuristic detection by field name, classification in annotations (0003 already says "not for secrets") |

## 0009.1 Motivation

- **Agents are the new log file.** Values sent to a model end up in prompts, provider logs, transcripts and fine-tuning sets. Usually the agent needs the *shape* of the data, the fact that a password is set, or that two records share an owner, and not the value itself.
- **Transformations defeat string masking.** GitHub Actions masks secrets by substring replacement in logs ○. Base64-encode the secret or print it in reverse and the mask fails. jq/yq-style pipelines do such transformations all the time. Redaction has to happen *before* values leave the trusted reader, and derived values have to inherit the classification.
- **Personal data is the bigger volume.** E-mail addresses and phone numbers (0008's `std.Email` and `std.E164`) are rarely secrets, but GDPR-relevant processing should not happen by accident just because an agent asked for a projection.

## 0009.2 Prior art

| System | Mechanism | Lesson |
| --- | --- | --- |
| Terraform `sensitive = true` ○ | Redacted in plan output; propagates through expressions (≥ 0.15); **stored in clear in state** | Redaction is a display property, so say so. Propagation through expressions is feasible and expected |
| JSON Schema / OpenAPI `writeOnly` ○ | "May be sent, not returned" | Closest existing semantics for `secret`; a natural mapping target |
| OpenAPI `format: password` ○ | UI hint inside `format` | Mixing sensitivity into `format` is a category error (cf. 0008) |
| Protobuf `debug_redact` field option ○ | Redacts in text and debug output, not on the wire | Same split: classify in the schema, redact at egress |
| Rust `secrecy::SecretString`, Pydantic `SecretStr` ○ | `Debug`/`repr` prints a placeholder; explicit `expose_secret()` | Reveal must be a visible, deliberate call |
| Kubernetes `Secret` ○ | Separate object kind; base64, not encryption; RBAC on the kind | Granularity by kind is too coarse (a Deployment's env still leaks); base64 is routinely mistaken for protection |
| GitHub Actions masking ○ | Substring replacement in logs | Fails under transformation, so redaction must be structural |
| CloudEvents ✔ (via 0003) | "Sensitive information SHOULD NOT be carried in context attributes" | Classification belongs with the data's type, not in a side channel |

Entries marked ○ are from background knowledge and were not re-read for this draft, as in 0003.

## 0009.3 Threat model

Two tiers, and the specification states which properties hold in which.

- **Tier 1: accident prevention.** The reader has access to the stored document (a developer, a CLI pipeline, an agent with a shell). Redaction prevents values from being *emitted by NOVA tools without intent*. It does not stop `cat file.nova`. Everything in 0009.4 to 0009.6 applies.
- **Tier 2: mediated access.** The agent's only access is through a host that exposes `get` and `patch` (§8.1). Here redaction is a boundary. The host must also close the revision channel (0009.6.5) and enforce reveal policy itself.

Out of scope: encryption at rest, key management, and protecting values from the host.

## 0009.4 Schema language

```
@schema acme.example/ops@1.0.0
@import novafile.dev/std@0.1.0 as std

type ApiToken = string @secret
type Email    = std.Email @personal

record Credentials @secret:          # whole record, like @open
  user: string
  password: string

record Service:
  id: string @key @id(1)
  db_url: std.Uri @secret @id(2)
  owner?: Email @id(3)
  env?: map<string, string @secret> @id(4)
  admin?: Credentials @id(5)
```

- `@secret` and `@personal` are **type attributes**. They apply to any type, including type arguments, union members, aliases and references to imported types (0008), and they may be placed after a record or enum name. At most one class per type. `secret` dominates `personal`.
- **std types never carry a class** (0008.3.5). Classification is the user's policy, added on top: `type Email = std.Email @personal`.
- **The class of a value** is the strongest class on any type through which it was resolved, including those of enclosing values. Everything below a classified value is classified. For unions, the class comes from the member the value resolved through (§6.3). Classification is therefore decided by resolution, and **only for documents that are resolved against a schema**.
- **Paths.** Resolution records each classified value at its path in the *stored* value. Some stored paths differ from paths in the resolved value: record-as-map fields, map keys before conversion, set elements before canonical sorting. A reader that redacts a resolved value must map the paths; if a path cannot be mapped, it MUST redact the nearest enclosing value that it can find (fail closed).
- **Forbidden positions** (the schema is invalid):
  - a classified type on a `@key` field. Keyed selectors put the value into paths, `@scope` headers and error locations (§6.2, §7.2);
  - a classified type as a map key type or set element type. Map keys and set elements are addressed by value in paths (`[v]`, §7.1).
- **Lints (Appendix E):**
  - `classified-default`: a default on a field whose own type is classified puts the value in the schema (error). Appendix E gains an `error` level for it;
  - `classified-hint`: fields named `password`, `secret`, `token`, `api_key` or `private_key` without a class (warning). Fields of a classified record are exempt, since the record's class covers them.

## 0009.5 Reading: redaction

### 0009.5.1 Reader modes

Every operation that emits values runs in one of these modes:

| Mode | Effect |
| --- | --- |
| `redact` (default) | Every classified value is replaced by its placeholder |
| `reveal=personal` | Personal values in clear; secrets redacted |
| `reveal` | Everything in clear |
| `reveal=PATH,…` | Only values at or below the given singular paths in clear (classes still apply elsewhere) |

These operations are covered: query responses (§7.3), conversions (`nvf convert`, `nvf fmt --to …`, `--to json`), diffs (§7.6), validation and resolution diagnostics (§6.4), patch conflict reports (§7.5) and printed patch results, template output (§9), and every editor feature that shows values: hovers, inlay hints, completions, the document outline.

- **Editors.** A document being edited is often invalid, so resolution cannot classify it. A language server classifies by the declared type at each position, and treats a value whose type it cannot tell (an unknown field, an unresolved union) as secret. It has no reveal switch; a missing schema hides all values.
- **Bindings.** A `Value` carries no link to a schema, so its `Debug` and `Display` cannot know the class. Bindings protect classified values through their types (0009.9).

### 0009.5.2 The placeholder

```
@get services[id=api]
→
@revision k:4be1a07c…
@scope services[id=api]
id: api
db_url: @redacted
owner: @redacted("p:7c1e93")
env: {DATABASE_PASSWORD: @redacted, LOG_LEVEL: @redacted}
admin: @redacted
```

- `@redacted` is a **redaction literal**. It is not a value of any kind (the reference implementation represents it as a variant whose tag, `@redacted`, is not an identifier, so no parsed document can produce it, wrapped in an output-only type), and it is valid only in documents that a reader produced in `redact` mode: query responses, envelopes (§8.2) and diff reports. §7.3's "responses MUST be valid NOVA documents" is amended: such documents are valid *redacted documents*, a document class that parsers accept only when asked to.
- A parser reading a data document, schema, template or patch MUST reject `@redacted`. Patch application (§7.5) MUST reject any operation whose value, old value or test value contains it, with the reason "redacted placeholder cannot be written".
- A classified **container** is replaced whole (`admin` above), not field by field. Its fields and its length are classified too. Whether an optional classified value is **present** is not classified: `owner: @redacted("p:…")` shows that `owner` is set, and filters and template conditions may test presence (0009.6.1).
- For `@personal`, the default placeholder carries a **pseudonym**: `p:` followed by the first 12 hex digits of HMAC-SHA-256(k, canonical encoding of the value), where `k` is a key held by the reader and rotated at least per session or per host-defined scope. Equal values get equal pseudonyms within one key, so an agent can correlate ("both services have the same owner") without seeing the value. Hosts MAY turn pseudonyms off.
- **Key storage.** Pseudonyms and revision tokens (0009.6.5) must be stable between invocations, or a `k:` token from one `nvf get` cannot be the base of the next `nvf patch`. The reference implementation reads the key from `NOVA_REDACT_KEY`, else from a `redact.key` file next to the user schema cache, created on first use with mode 0600; without either it uses a key for one process, whose tokens cannot serve as patch bases.
- `@secret` placeholders carry no pseudonym by default. Equality between secrets (reused passwords) is itself sensitive.
- **JSON export:** `{"$redacted": null}` or `{"$redacted": "p:7c1e93"}`. Conversion reports the loss as with other lossy mappings.
- **`-r` raw output:** `@redacted` or `@redacted(p:7c1e93)`, one per line.

### 0009.5.3 Schema-free and unresolvable documents

- A document without `@schema` has no classified values. Tools SHOULD say so once when running in `redact` mode against a host-configured policy that expects classification ("no schema: nothing is classified").
- A document whose `@schema` reference **cannot be resolved** (§6.9), including one whose schema has an unresolvable import (0008): in tier 2, the host MUST refuse to answer queries. In tier 1, tools in agent mode (`--agent`, or a detected coding agent) MUST refuse unless `--reveal` or `--no-schema` is given. **Failing closed is the point.** Otherwise a missing catalog entry quietly sends values to an agent. A human at a terminal gets a warning and the values, since they can read the file anyway. The same applies to a document that is invalid against its schema, since resolution then decides no classes.

## 0009.6 Side channels

### 0009.6.1 Filters

In `redact` mode, a filter comparison (`=`, `!=`, `<`, `<=`, `>`, `>=`) or `in` whose relative path reaches a classified value, or traverses one, is an **error** ("filter on classified value"), not a non-match. Otherwise `[?pin<5000]` becomes a binary search over the secret. Existence and absence (`[?p]`, `[?!p]`) remain allowed, since presence is not classified (0009.5.2). The same holds for template conditions that compare with `null` (`@if $db.admin != null`). Projections are allowed and yield placeholders. A pattern filter (`[?p ~ "…"]`, Appendix C.13), if added, falls under the same rule.

### 0009.6.2 Diagnostics

Validation messages for classified values MUST NOT include the value. §6.4's example becomes `services[2].db_url: value is not a std.Uri`. The same applies to resolution errors, union "closest member" details, and patch conflicts (`expected: @redacted, actual: @redacted`). Conflict reports MAY say whether the values were equal ("old value did not match") without either value.

### 0009.6.3 Patches

- Writing a classified location is allowed: `= services[id=api].db_url: "postgres://…"`. Rotation is a legitimate agent task.
- Printed patch results (a patch applied without writing the file back) are redacted like any other output.
- `old -> new` cannot be written in `redact` mode, since the old value is unknown. Writers use `=` with the base revision, or `? path` for existence.
- Hosts MAY bind a policy that forbids writes to classified locations per tool call, alongside the bound scope (§7.5 step 2).
- The `old` and `new` values of an applied patch are not echoed in the host's response.

### 0009.6.4 Diffs

In `redact` mode, a diff (§7.6) that touches a classified location emits `= path: @redacted`. The result is a report, not an applicable patch: application rejects it (0009.5.2). Whether a classified value changed is visible. Its contents are not.

### 0009.6.5 Revisions

This is the subtle one. A redacted response carries `@revision`, the SHA-256 of the **whole stored document** (§2.13). An agent that sees everything except a low-entropy secret (a PIN, a short password, a known-format token) can enumerate candidates and recompute the revision offline. For a 4-digit PIN that is 10⁴ hashes. Merkle revisions (proposal 0002, `tree:`) make this worse, because the hash of a subtree containing only the secret field is a direct oracle.

- In tier 2, a host serving a redacted view of a document that contains classified values MUST NOT expose its revision, or any subtree revision, in clear. It exposes an **opaque revision token** instead: `k:` followed by HMAC-SHA-256(host key, revision), truncated as §2.13 allows. Patches whose `@patch`/`@base` carries a `k:` token are mapped back by the host. The token is stable for one revision and key, so compare-and-swap (§7.5 step 1) works unchanged.
- In tier 1, tools MUST do the same whenever a printed view hides values: `nvf get`, `nvf diff` and `nvf hash` print `k:` tokens, and `nvf patch` accepts a `k:` base. `--reveal` prints the revision.
- The template function `revision` (0006) applied to a classified value returns a classified value (0009.7).

## 0009.7 Templates and derived values

Templates (§9, and expressions per 0006) are total and value-level, so **taint propagation** is tractable.

- A value obtained from an imported document through a classified type is classified, with the same class.
- The result of any operator, interpolation or built-in function whose operands include a classified value, at any depth, inherits the strongest class among them. This covers `join`, `replace`, `slice`, `len`, `to_json`, `revision`, `sha256` and comparisons. There are deliberately no exceptions for "one-way" functions: hashing a low-entropy secret does not protect it (0009.6.5).
- One exception keeps whole records from being classified because one field is: built-ins that only move values without reading them (`get`, `default`, `keys`, `values`, `concat`, `merge`, `len`) keep each value's own class when no argument is classified as a whole. `get($db, "host", "")` stays in clear while `get($db, "password", "")` is classified.
- A value missing from a classified container is a classified `null`, not an error, so a template cannot tell which fields a classified record holds or how long a classified list is.
- An operation that fails on a classified operand (`int($db.password)`, `$db.password + 1`) yields a classified `null` instead of an error: whether it fails tells something about the value, so failure must render like success. Only exhausting the render budget stays an error.
- A `@def` call passes classified arguments on with their class. Parameter and result types are checked against the clear value; a classified value that does not match makes the call a classified `null`, for the same reason.
- Rendering in `redact` mode splices placeholders. Rendering for deployment reveals, and the rendered output is then the user's responsibility. `nvf render` redacts on stdout and reveals when it writes a file (`-o`), unless `--reveal` says otherwise. `--reveal=PATHS` names paths in the *output*.
- Anything that branches on a classified value is an error in `redact` mode, for the same reason as filters: classified conditions and comprehension filters (`@if $x.password == ""`), a classified left operand of `and` or `or` (it decides whether the right one runs), `@for` loops, comprehensions and spreads over classified containers, interpolated record keys, comprehension keys, set elements and map keys (uniqueness would compare them), and selectors that compare classified values.
- `$x == null` and `$x != null` test presence. They are allowed on a classified value, since presence is not classified, and a field missing from a record counts as absent rather than an error. A presence test *inside* a classified container (`$db.admin.mfa`, `$db.tokens[3]`) is an error.

## 0009.8 Canonical text, descriptor, evolution

- **Canonical text (§6.6).** The class attribute follows the other type attributes: `@range`, `@len`, `@pattern`, then `@personal`/`@secret`. On definitions it follows the name, like `@open`.
- **Descriptor (§6.8).** `Type` and record/enum definitions gain `class?: Class`, with `enum Class = personal | secret`. Together with 0008's imports, the meta-schema becomes `novafile.dev/meta/schema@0.3.4`.
- **Evolution (§6.5).** Classification does not change the set of valid values, so the value-based rules do not decide it. Proposed rows:

  | Change | Classification |
  | --- | --- |
  | Add a class, or raise `personal` to `secret` | compatible |
  | Remove a class, or lower `secret` to `personal` | **breaking** (declassification) |

  Rationale: a consumer pinned to `1.4.0` relies on `1.x` not to start emitting a value it used to redact. A version is a checked claim (§6.7), and declassification breaks that claim even though old data still validates. `nvf schema check` names declassifications explicitly. Under 0008, a class on an imported type comes only from the importing schema, so bumping an import never declassifies.

## 0009.9 Interoperability

- **JSON Schema.** `@secret` → `"writeOnly": true` plus `"x-nova-class": "secret"`. `@personal` → `"x-nova-class": "personal"`. On a record or enum, the keyword goes on its `$defs` entry. Reading takes the class **only** from `"x-nova-class"`. `"writeOnly"` is ignored: it marks request-only fields (and schemars sets it for every `#[serde(skip_serializing)]` field), not secret ones, and a wrong `@secret` could only be removed with a breaking change (0009.8). The `classified-hint` lint flags password-like fields that arrive without a class. A class in a position NOVA forbids (set elements, map keys, key fields) is dropped with a warning.
- **Protobuf.** `@secret` and `@personal` → `[debug_redact = true]` on the field, which needs protobuf 22 or newer. A classified list element maps too, since `repeated` fields carry the option. Only a classified map value is reported as not representable. This affects code generation only; encoding and decoding ignore classes.
- **Bindings (non-normative).** `novafile-serde`/`novafile-derive`: `#[nova(secret)]`, and mapping `@secret` strings to `secrecy::SecretString` behind a feature, so `Debug` never prints them. A plain `Value` cannot honour classes (0009.5.1).

## 0009.10 YAGNI / rejected

- **In-document markers** (`password: @secret("…")`). These would put classification under the writer's control and in the value model, and they would change revisions when a field is reclassified. The schema owns meaning.
- **Encryption, envelopes for ciphertext, key references.** These are storage concerns. A `@secret` string can hold a reference (`vault:…`) by convention.
- **Heuristic detection** of secrets by name or entropy in redact mode. Lints suggest classification; redaction never guesses.
- **Classification in annotations** (0003). Annotations are part of the value and writable by third parties, so anyone could declassify.
- **Classification in std** (0008). A classified std type could not be declassified by its users.
- **Finer classes** (`confidential`, `restricted`, GDPR Art. 9 categories). Two classes map onto two behaviours, "never needed" and "needed only pseudonymously". More classes without more behaviours are labels, and labels already exist.

## 0009.11 Open questions

1. **Placeholder syntax.** A response-only literal (`@redacted`) or a reserved variant (`!redacted`)? The literal cannot collide with user data; the variant would need no parser change but could collide with an enum.
2. **Pseudonym scope.** Per session, per host, or per document? Longer scopes help correlation across tasks and also help re-identification.
3. **Should `personal` filters be allowed on pseudonyms** (`[?owner=@redacted("p:7c1e93")]`)? Useful for agents, safe given a keyed HMAC, but it adds grammar.
4. **Declassification as breaking.** Is it acceptable that a pure policy change forces a MAJOR release, or should it be a separate "policy" classification that tools report without affecting SemVer?
5. **Classified template parameters.** A `@param` with a classified type, and a template imported with its own `@schema`, classify nothing today, since classification starts from a root type. Should parameters be classified by their declared types?
6. **Length leakage.** Should `@redacted` hide the shape of containers only, or also make redacted strings indistinguishable by length in binary-encoded responses (§5)?
7. **Schemas-as-data.** Descriptors (§6.8) contain defaults. Should a classified default be redacted when a descriptor is queried, or is `classified-default` as an error sufficient?
8. **Values of type `any`.** Once 0003 lands, `annotations: map<QualifiedKey, any>` can hold anything, but `any` carries no class. Should a classified value written into an `any` position be an error, keep the class of the type it came from (impossible without a schema path), or is "annotations are not for secrets" (0003) enough?
