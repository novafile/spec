# NOVA Proposal 0005: Schema names and catalogs

| | |
| --- | --- |
| Status | Draft proposal for discussion. Not normative until merged into SPEC.md. |
| Targets | §4.2 (`@schema`), §6.6–6.8 (names, the meta-schema), §11.2 (JSON Schema `$id`, Protobuf `package`), §12 (security), Appendices C and E, `meta/nova-schema.novs`, conformance suite |
| New kinds / tags / directives | none. Schema name grammar refined; new meta-schema `novafile.dev/meta/catalog`; meta-schema renamed to `novafile.dev/meta/schema` |
| Date | 2026-11-19 |

---

## 0005.0 Summary

A schema reference such as `@schema infrastructure@1.2.0#8c21a0f3d5e6b7c8` (§4.2, §6.7) says exactly *which version* of a schema the data was written against, and the fingerprint (§6.6) says exactly *which text*. What it cannot say is *whose* `infrastructure` it means. Names are a flat space today, and there is no registry to hand them out.

This proposal makes schema names globally unique without a registry, by borrowing DNS ownership the way Go module paths do, and adds a local **catalog** that maps names to files so that nothing ever has to be fetched:

1. **Qualified names.** A name whose first segment is a domain name, such as `acme.example/billing/invoice`, is **qualified**: whoever controls `acme.example` owns every name below it. The name is an identity, not a location.
2. **Local names** stay as they are. `infrastructure` remains valid and means "this project's schema"; it is not globally unique and is not meant to be.
3. **Catalogs** (`nova-catalog.nova`) tell tools where the `.novs` files for a name live: in the repository, in a vendored directory, in a cache. Resolution is offline by default.
4. **Fetching is opt-in.** When the *user* enables it, a qualified name has a conventional location, `https://{name}/{version}.novs`, which a catalog can redirect. Fetched schemas are checked against the reference's fingerprint and against pins.
5. **Reserved namespace.** `novafile.dev/` belongs to the NOVA project. The meta-schema becomes `novafile.dev/meta/schema`.

| Facet | Recommendation |
| --- | --- |
| Form of a name | Scheme-less, DNS-rooted path: `acme.example/billing/invoice`. Not a URL, not a URN, not a `tag:` URI |
| Ownership | Whoever controls the domain (or, for hosting paths such as `github.com/alice/…`, the account) |
| Equality | Plain string equality. The grammar admits exactly one spelling per name, so no URL normalization rules are needed |
| Versions | Unchanged: `name@MAJOR.MINOR.PATCH`, outside the name. The last segment SHOULD NOT be a version (`…/v2`), linted |
| Existing names | Still valid, as local names, except the rare ones with a `.` in their first segment |
| Lookup | Explicit schema, then built-in schemas, then catalogs, then the fetch cache, then (only if enabled) the network |
| Integrity | `#fingerprint` in the reference; full `sha256:` revisions pinned in catalogs |
| Reserved | `novafile.dev/` (project); `example.com`/`.net`/`.org`, `*.example`, `*.test`, `*.invalid`, `*.localhost`, `*.internal` (special use, never fetched) |
| JSON Schema | `$id` becomes `https://{name}/{version}.schema.json` for qualified names, and is omitted for local ones; `x-nova-schema` carries the reference. Replaces the unregistered `urn:nova:` |
| Protobuf | `package` from the reversed domain: `acme.example/billing/invoice@2.1.0` → `example.acme.billing.invoice.v2` |
| Rejected | Full URLs as names, URNs, `tag:` URIs, a central registry, versions in the name, implicit fetching |

---

## 0005.1 Motivation

Three things go wrong with a flat name space as soon as schemas leave the repository they were written in:

- **Collisions.** Two teams publish `infrastructure@1.2.0`. A validator holding the wrong one either rejects valid data, or, worse, accepts it under the wrong rules. The fingerprint catches a mismatch only when the writer recorded it, and then only as "different", never as "whose".
- **No way to find a schema.** Given `@schema invoice@2.1.0` in a file someone sent you, there is nothing to go on. The language server (§14) can only search the workspace for a `.novs` file that declares the same name, and picks the closest one when several do.
- **Shared vocabularies.** A schema for an external standard (PDDL, a Kubernetes resource, an OpenAPI component) is useful to many projects at once, but only if they can agree that they mean the same schema.

The obvious fix is a registry, and NOVA does not want one: someone has to run it, decide disputes, keep it online and keep it trustworthy, and every private schema would either leak into it or need a second mechanism. The name space that already has decentralised ownership, dispute resolution and a working market is DNS. JSON Schema (`$id`), XML namespaces, Java packages and Go modules all lean on it, and Go shows the variant that fits NOVA best: names that look like URLs but carry no scheme, are owned through their domain, and are mapped to content by tooling and verified by hash.

The existing grammar is already most of the way there. Schema names consist of lowercase ASCII letters, digits and `-_./` (§6.7), which is exactly the alphabet of a lowercase host name followed by a path. `acme.example/billing/invoice` is a valid name today; this proposal gives it a meaning.

---

## 0005.2 Names

### 0005.2.1 Grammar

```
schema-name    = qualified-name / local-name          ; at most 255 bytes
qualified-name = host 1*("/" segment)
host           = label 1*("." label)                  ; at most 253 bytes
label          = alnum [*(alnum / "-") alnum]         ; 1 to 63 bytes
local-name     = first *("/" segment)                 ; first segment has no "."
first          = lower *(lower / digit / "-" / "_")
segment        = alnum *(alnum / "-" / "_" / ".")
alnum          = lower / digit
lower          = %x61-7A                              ; a-z
```

- A name is **qualified** if its first `/`-separated segment contains a `.`, and **local** otherwise. A qualified name MUST match `qualified-name`, and a local name MUST match `local-name`.
- In a qualified name, the last label of the host MUST start with a letter, so IP addresses (`10.0.0.1/x`) are not hosts. Labels are lowercase LDH labels (RFC 1123); internationalised domain names are written in their A-label form (`xn--…`).
- A qualified name has at least one path segment: `acme.example` alone is not a schema name. This keeps the domain itself free for a project's overview of its schemas, and keeps `acme.example@1.0.0` from looking like an e-mail address.
- Segments start with a letter or digit, so `.` and `..` segments, empty segments and leading or trailing `/` are impossible.

Valid: `infrastructure`, `acme/order`, `acme.example/billing/invoice`, `github.com/alice/pddl/domain`, `xn--bcher-kva.example/catalog`, `3m.com/parts`.

Invalid: `Acme.example/x` (uppercase), `acme.example` (no path), `my.schema` (qualified, no path), `acme.example/` (trailing slash), `acme.example//x`, `acme.example/./x`, `10.0.0.1/x`, `-acme.example/x`, `acme_corp.example/x` (`_` in a host).

Two names are the same name if and only if they are equal as strings. Because the grammar admits only lowercase, has no scheme, port, query, fragment or percent-encoding, and fixes the separator, there is exactly one way to spell each name, and no normalization is ever needed. This matters because the name is part of the canonical text and therefore of the fingerprint (§6.6), and because the compatibility check (§6.7) starts by comparing names.

### 0005.2.2 What changes for existing names

The rule today is "lowercase ASCII letters, digits and `-_./`, starting with a letter", with no `//` and no trailing `/`. Every name that has no `.` in its first segment, and no segment starting with `-`, `_` or `.`, keeps its meaning as a local name. Names such as `nova.v1` or `acme.config/x` that already have a `.` in the first segment would now have to be valid qualified names. Given that the specification is at 0.1 and such names have not been seen in the wild, this proposal accepts that edge rather than inventing a second marker for qualified names. The reference implementation's `valid_schema_name` changes accordingly.

### 0005.2.3 Ownership

- A qualified name belongs to whoever controls its host. Publishing schemas under a domain you do not control is the same kind of mistake as publishing a Go module or a Java package under it: nothing stops it technically, and nobody will resolve it for you.
- **No domain?** Use a path on a hosting service where you own an account: `github.com/alice/schemas/route`, `codeberg.org/alice/route`. The host owns the domain; the account owns the path below it, which is exactly how Go modules work for people without a domain. The default fetch location (§0005.4) will not work for most such hosts, so these names are normally used with a catalog entry.
- **Subdomains** are fine and often clearer: `schemas.acme.example/invoice` and `acme.example/schemas/invoice` are both valid, and they are different names.
- **Losing a domain** does not invalidate a name. Names are identities: documents written against `acme.example/invoice@2.1.0` keep meaning that schema, and catalogs and caches keep the files. What a new owner of the domain *can* do is publish different content under the same name; fingerprints and pins (§0005.5) are what detect that.

### 0005.2.4 Reserved names

| Names | Reserved for | Fetched |
| --- | --- | --- |
| `novafile.dev/…` | The NOVA project: the meta-schemas and any schemas the specification defines | the meta-schemas never, since implementations bundle them (§0005.4.1); others like any qualified name |
| `example.com/…`, `example.net/…`, `example.org/…`, `*.example/…` | Documentation and examples (RFC 2606) | never |
| `*.test/…` | Test suites (RFC 6761) | never |
| `*.invalid/…`, `*.localhost/…` | Never resolvable (RFC 6761) | never |
| `*.internal/…` | Private networks without a public domain (reserved for private use by ICANN in 2024) | never; such names are expected to be mapped by a catalog |

The conformance suite uses `*.test` names for the cases this proposal adds, and the examples in this document use `acme.example`.

### 0005.2.5 Versions stay outside the name

The coordinates of a schema version are `name@version`, as they are today. A qualified name does not change that, and in particular:

- The version is never part of the name. `acme.example/invoice/v2` is a different schema from `acme.example/invoice`, with its own version history starting wherever its author starts it, not "version 2 of invoice". Go needs `/v2` suffixes because its import paths have no other place for a major version; NOVA has `@2.0.0`, and the compatibility contract of §6.7 already reads across MINOR and PATCH. A new lint, `schema-name-version` (§0005.8), warns when the last segment looks like a version (`v[0-9]+`, or a version number).
- References keep naming the exact version the data was written against. They do not get ranges (`@^1.2`) or partial versions (`@1.2`): which readers may accept the data is decided by the compatibility contract, not by the reference.

---

## 0005.3 Catalogs

A **catalog** is a NOVA document that tells tools where to find schema files. It is the offline answer to "where is `acme.example/invoice@2.1.0`?", in the same role as XML catalogs, import maps and `go.work`/vendor directories.

```
@schema novafile.dev/meta/catalog@0.1.0

# Local sources, searched in order. A directory contributes every .novs file below it.
schemas:
  - path: schemas/
  - path: vendor/acme.example/

# Where to fetch names under a prefix, if the user has enabled fetching (§0005.4.3).
remote:
  - prefix: acme.example/
    url: https://schemas.acme.example/{rest}/{version}.novs
  - prefix: github.com/alice/schemas/
    url: https://raw.githubusercontent.com/alice/schemas/v{version}/{rest}.novs

# Exact content expected for these versions, wherever they come from.
pins:
  - schema: acme.example/billing/invoice@2.1.0
    revision: sha256:8c21a0f3d5e6b7c8a9f0e1d2c3b4a5968778695a4b3c2d1e0f9e8d7c6b5a4938
```

**Meaning.**
- A catalog does not declare names. Each `.novs` file declares its own name and version in its `@schema` line, and a tool reads the files a catalog points to and indexes them by that line. A catalog therefore cannot make a file mean something it does not say.
- `schemas` lists files and directories, relative to the catalog's own directory. Directories are searched recursively. Anonymous schemas found there are ignored.
- `remote` maps a name prefix to a URL template. `{name}` is the whole name, `{rest}` the part after the prefix, and `{version}` the version. The template MUST be an `https:` URL. The longest matching prefix wins. A prefix is a whole number of segments: it ends with `/`, or equals a complete name.
- `pins` record the full revision (§2.13) of the canonical schema text (§6.6) of a version. Wherever that version is found, locally or remotely, its revision MUST equal the pin; otherwise the tool MUST NOT use it and MUST report the mismatch. The fingerprint of a pinned version is the first 16 hexadecimal digits of the pin, so a pin also checks references that carry a fingerprint.

**Finding catalogs.** In order:

1. catalogs named explicitly (`--catalog FILE`, or the `NOVA_CATALOG` environment variable, a path list);
2. the **project catalog**: the nearest file named `nova-catalog.nova` in the directory of the document being processed or any directory above it;
3. the **user catalog**: `nova/catalog.nova` in the platform's user configuration directory (`$XDG_CONFIG_HOME` on Unix-like systems).

A tool given no catalog at all MAY fall back to today's behaviour of scanning the workspace for `.novs` files; the language server does.

**The catalog meta-schema** (`meta/catalog.novs`):

```
@schema novafile.dev/meta/catalog@0.1.0
@root Catalog

type Name = string @len(1..255)
type Revision = string @pattern("sha256:[0-9a-f]{64}")

record Catalog:
  schemas?: list<Source> @id(1)
  remote?: list<Remote> @id(2)
  pins?: list<Pin> @id(3)
  fetch?: bool @id(4)

record Source:
  path: string @len(1..) @id(1)

record Remote:
  prefix: Name @key @id(1)
  url: string @pattern("https://.+") @id(2)

record Pin:
  schema: string @key @id(1)        # name@version, without a fingerprint
  revision: Revision @id(2)
```

`fetch` is honoured only in the user catalog (§0005.4.3). Implementations check the rules the meta-schema cannot express: names and references follow §0005.2.1 and §6.7, and a URL template has no placeholders other than the three above.

---

## 0005.4 Finding a schema

### 0005.4.1 Lookup order

Given a reference `name@W[#fp]` (from `@schema`, a frame header or a NOVA Lines header), a tool looks in these places, in order, and stops at the first place that has a **candidate**: a schema with that name that can read version W under the compatibility contract (§6.7).

1. **An explicit schema.** A schema passed directly (`--schema FILE`, an API argument) is used as it is, and the reference is checked against it as §6.7 already requires. Nothing below applies.
2. **Built-in schemas.** Implementations MUST bundle `novafile.dev/meta/schema` and `novafile.dev/meta/catalog` in the versions they implement. A catalog source MUST NOT shadow a bundled version: a file that declares a bundled `name@version` with a different revision is an error.
3. **Catalog sources**, in the order the catalogs and their `schemas` entries are listed.
4. **The fetch cache**: versions fetched earlier (§0005.4.3).
5. **The network**, only if fetching is enabled, only for qualified names outside the special-use domains of §0005.2.4, and only for exactly version W.

Within one place, if the reference carries a fingerprint and there is a candidate of version W with that fingerprint, it is chosen. Otherwise the candidate with the highest precedence is chosen; build metadata does not take part (§6.7).

The chosen schema is then checked against the reference exactly as today (§6.7): equal names, the compatibility contract, and equal fingerprints when the versions are equal and the reference has one.

**Conflicts.** Two files reachable through steps 2 and 3 that declare the same `name@version` with different canonical text are a **conflict**. A tool MUST report it, naming both files, and MUST NOT silently pick one. This is what turns today's "two schemas called `infrastructure` in the workspace" from a heuristic tie-break into a diagnostic.

### 0005.4.2 Default location

A qualified name has a conventional location for each version:

```
https://{name}/{version}.novs          acme.example/billing/invoice@2.1.0
                                       → https://acme.example/billing/invoice/2.1.0.novs
```

The location is a convention for publishers who want one, not a property of the name. A schema whose author never hosts anything is just as valid, and a catalog `remote` entry overrides the location for any prefix.

Publishers SHOULD serve each version at its default location over HTTPS, MAY serve a human-readable overview at `https://{name}/`, and MUST NOT change the content served for a version once published: a version is immutable (§6.7 release rules already require a new version for every change). Serving the JSON Schema rendering at `https://{name}/{version}.schema.json` (§0005.6.1) is RECOMMENDED where JSON Schema users are expected.

### 0005.4.3 Fetching

The existing rules stay: parsers MUST NOT fetch from `@schema` references, and schemas are never fetched automatically (§4.2, §12). This proposal adds when a tool MAY fetch:

- **Only when the user enabled it**: by a command-line flag (`nvf validate --fetch`), by `NOVA_FETCH=1`, or by `fetch: true` in the user catalog. A project catalog, which arrives with a cloned repository, cannot enable fetching; it can only say *where* to fetch from once the user has.
- **Only qualified names** outside the special-use domains (§0005.2.4), never a bundled version, and only the exact version W.
- **Only over HTTPS**, following redirects only to HTTPS URLs, with a bound on the response size.

A fetched file MUST be a named schema whose `@schema` line declares exactly the requested `name@W`. If the reference carries a fingerprint, or a catalog pins that version, the fetched schema MUST match them. A fetched schema that fails any of these checks MUST be discarded, and the failure reported.

Fetched schemas are stored in a user-level **cache**, keyed by `name@version` and revision. Since versions are immutable, a cached version is never fetched again; a tool that finds a different revision for a version it has cached reports it as a conflict.

Tools SHOULD offer to record the revision of a newly fetched version as a pin in the project catalog (`nvf schema fetch REF --pin`), so that everyone working on the project checks the same content: trust on first use, then pinned.

### 0005.4.4 Command line

| Command | Effect |
| --- | --- |
| `nvf schema resolve REF [--fetch]` | Prints where `REF` resolves from (built-in, catalog file, cache, URL), its version and revision, or why it does not resolve |
| `nvf schema fetch REF [--pin]` | Fetches exactly that version into the cache and, with `--pin`, adds a pin to the project catalog |
| `nvf validate FILE` | Without `--schema`, looks up the document's `@schema` reference as in §0005.4.1 |

---

## 0005.5 Fingerprints and pins

Fingerprints already exist (§6.6): the first 16 hexadecimal digits of the revision of the canonical text, written `name@version#fingerprint`. This proposal keeps them as they are and adds the full revision for pins:

- **In references**, the fingerprint stays short, because references are written into every document and frame header. 64 bits detect accidental mismatches and edits.
- **In catalogs**, pins carry the full `sha256:` revision. A pin is written once per project, so length does not matter, and it protects against deliberate substitution: someone who gains control of a domain would have to find a second preimage of SHA-256, not of a 64-bit prefix.
- Neither is a signature. They say "this is the content I expect", not "the owner of `acme.example` published this". Signed schemas are left to future work (§0005.10).

---

## 0005.6 Interoperability

### 0005.6.1 JSON Schema (§11.2)

`novafile-schemars` currently writes `$id: urn:nova:name@version`. The `nova` URN namespace is not registered (RFC 8141 requires registration with IANA for formal namespaces), so that `$id` is not a valid URN in the strict sense. Proposed:

- *Writing:*
  - A qualified name gets `"$id": "https://{name}/{version}.schema.json"`. The fingerprint is not part of it, since a JSON Schema `$id` must not carry a non-empty fragment.
  - A local name gets no `$id`: it has no global identity to state.
  - Every named schema gets `"x-nova-schema": "name@version"` and, as today, a `title`.
- *Reading:*
  - `"x-nova-schema"` wins when present.
  - Otherwise an `https://` `$id` whose host and path, lowercased, form a valid qualified name gives that name. A trailing `/{version}.schema.json` or `/{version}.json`, where the version is valid SemVer, gives the version; any other trailing `.json` is kept in the name. So `https://json.schemastore.org/package.json` becomes `json.schemastore.org/package.json`, and a third-party schema imported into NOVA gets a qualified name automatically.
  - The legacy `urn:nova:name@version` is still read.
  - Anything else falls back to `title`, then to the names given on the command line, as today.

### 0005.6.2 Protobuf (§11.2)

Today the `package` is the schema name with every character outside `[A-Za-z0-9_]` turned into `_`, plus `.vMAJOR`. For qualified names that produces `acme_example_billing_invoice.v2`. Protobuf's own convention is the reversed domain, so qualified names map to:

```
acme.example/billing/invoice@2.1.0   →   package example.acme.billing.invoice.v2;
```

The host labels are reversed, each path segment becomes a package component, and within a component every character outside `[A-Za-z0-9_]` becomes `_` (a component that starts with a digit gets a leading `_`). Local names keep today's mapping.

### 0005.6.3 Language bindings (§11.3)

`#[nova(name = "…")]` accepts any valid name, qualified or local. Nothing else changes.

### 0005.6.4 Unaffected

The value model, text and binary syntax, the `@schema` reference grammar (`name@version[#fingerprint]`), the SCHEMA frame field (§5.4), schema descriptors (the `name` field stays a string) and the compatibility rules.

---

## 0005.7 The meta-schema moves into the reserved namespace

The meta-schema is the one schema every implementation shares, so it is the first that should have a name nobody else can take. Proposed: `nova-schema@0.3.2` becomes `novafile.dev/meta/schema@0.3.3`.

- The content is unchanged apart from the `@schema` line, so by the release rules (§6.7) this is a PATCH release; the name change itself makes it a different schema for §6.7's name check.
- `meta/nova-schema.novs` is renamed to `meta/schema.novs`, and `meta/catalog.novs` is added. Their default locations, `https://novafile.dev/meta/schema/0.3.3.novs` and `https://novafile.dev/meta/catalog/0.1.0.novs`, SHOULD serve the files, although implementations never fetch them (§0005.4.1).
- **Transition.** Until NOVA 1.0, implementations SHOULD read a descriptor that declares `@schema nova-schema@0.3.z` as if it declared `novafile.dev/meta/schema@0.3.z`, with a deprecation warning. Writers emit the new name.

---

## 0005.8 Lints (Appendix E)

| Rule | Level | Checks | Fix |
| --- | --- | --- | --- |
| `schema-name-version` | warning | the last segment of a schema name looks like a version (`v2`, `2`, `2.1`); versions belong after `@` | — |
| `schema-name-reserved` | warning | a schema declares a `novafile.dev/` name that the specification does not define | — |
| `unpinned-fetch` | hint | the project catalog has `remote` entries, but some version fetched for this project has no pin | add the pin |

---

## 0005.9 Conformance cases

Expectations are generated by the reference implementation once it supports the proposal.

**`schema-invalid/`** (the schema MUST be rejected for its `@schema` line):

| Case | `@schema` line | Reason |
| --- | --- | --- |
| `name-uppercase-host` | `@schema Acme.test/x@1.0.0` | uppercase |
| `name-host-only` | `@schema acme.test@1.0.0` | a qualified name needs a path |
| `name-ip-address` | `@schema 10.0.0.1/x@1.0.0` | the last label must start with a letter |
| `name-underscore-in-host` | `@schema acme_corp.test/x@1.0.0` | `_` is not allowed in a host |
| `name-dot-segment` | `@schema acme.test/./x@1.0.0` | segments start with a letter or digit |
| `name-label-hyphen` | `@schema -acme.test/x@1.0.0` | labels do not start or end with `-` |
| `name-too-long` | a 256-byte name | over 255 bytes |

**`schema-names/`** (new: `names.json`, a list of strings, and `expect.json`, the classification of each as `qualified`, `local` or `invalid`), covering every example in §0005.2.1.

**`schema-lookup/CASE/`** (new: a directory tree with `nova-catalog.nova`, `.novs` files and a `doc.nova`; `expect.json` names the file the document's reference resolves to, or the error):

| Case | Setup | Expectation |
| --- | --- | --- |
| `catalog-directory` | catalog lists `schemas/`; `schemas/a.novs` declares `acme.test/a@1.2.0`; the document references `@1.0.0` | `schemas/a.novs` |
| `newest-readable` | `1.1.0` and `1.3.0` and `2.0.0` available; the reference is `@1.1.0` | `1.3.0` |
| `fingerprint-exact` | `1.1.0` and `1.2.0` available; the reference is `@1.1.0#` with the fingerprint of `1.1.0` | `1.1.0`, although `1.2.0` could read it |
| `conflict` | two files declare `acme.test/a@1.0.0` with different content | error `conflict`, naming both |
| `pin-mismatch` | the catalog pins `acme.test/a@1.0.0` to a different revision | error `pin` |
| `nearest-catalog` | catalogs in the document's directory and its parent | only the nearer one is used |
| `no-fetch` | the reference has no local candidate; a `remote` entry exists | error `not-found` (fetching is never on by default) |
| `legacy-meta-name` | a descriptor declaring `@schema nova-schema@0.3.2` | validates, with a deprecation warning |

---

## 0005.10 Alternatives considered

**Full URLs as names** (`https://acme.example/schemas/invoice`), the way JSON Schema `$id` and XML namespaces do it. Closest to this proposal, and the default location (§0005.4.2) recovers a URL whenever one is wanted. Rejected as the *name* because:
- URLs have many spellings of one resource (scheme and host case, default ports, percent-encoding, trailing slashes, `http` versus `https`). A name that goes into fingerprints and the §6.7 name check needs exactly one spelling, so NOVA would have to adopt and mandate a normalization; a grammar that only admits one spelling is simpler.
- The reference syntax `name@version#fingerprint` would collide with URL syntax: `#` starts a fragment, so generic URL tooling would cut the fingerprint off, and `:` and `?` would need rules in directives, frame headers and NOVA Lines headers.
- A scheme invites the expectation that the name can and will be dereferenced. Making that a separate, opt-in step is the point.
- Every existing name would have to change.

**URNs** (`urn:nova:…`, `urn:acme:…`). A formal URN namespace has to be registered with IANA (RFC 8141), and a NOVA-owned namespace (`urn:nova:`) would make the NOVA project the registry for the part after it, which is what this proposal avoids. Informal namespaces (`urn:x-…`) are deprecated. URNs also carry no ownership: nothing says who may use `urn:nova:invoice`.

**`tag:` URIs** (RFC 4151), such as `tag:alice@example.org,2026:invoice`. They need no registration and are owned through a domain or e-mail address at a date, so they solve uniqueness for people without a domain. But they are unfamiliar, verbose, contain `@`, `:` and `,` (which clash with the reference syntax), and do not lead anywhere. Hosting paths (`github.com/alice/…`) cover the same people with names that look like the rest, and `*.internal` covers private use.

**Reverse-DNS names** (`example.acme.billing.invoice`, as in Java and Protobuf). Equivalent ownership, but they hide where a schema might be found and read backwards from how people write domains. They are still produced where a target expects them (§0005.6.2).

**A central registry** (as crates.io or npm). Gives short names and discovery, at the cost of running a service, settling name disputes, and either exposing private schemas or needing a second mechanism for them. A registry can still be built on top of qualified names later, as an index or a mirror, the way Go's module proxy works, without changing what a name means.

**Versions in the name** (`…/v2`). Discussed in §0005.2.5.

**Fetching by default.** Convenient, but it turns every validation into a network request to a host chosen by whoever wrote the document, which leaks what is being validated, fails offline, and makes results depend on what a server returns today. §12 already rules it out for references; this proposal keeps that.

---

## 0005.11 Normative text

The proposed changes to SPEC.md, in summary:

- **§4.2**, `@schema` row: "…`name@MAJOR.MINOR.PATCH`, where `name` is a qualified or local schema name (§6.7)…". The sentence "Parsers MUST NOT fetch it" stays.
- **§6.7**: the name rule is replaced by the grammar, ownership and reserved names of §0005.2.1–0005.2.4. A new subsection **§6.9 Finding schemas** takes §0005.3, §0005.4.1–0005.4.3 and §0005.5.
- **§6.8**: `nova-schema@0.3.2` becomes `novafile.dev/meta/schema@0.3.3`, with the transition rule of §0005.7.
- **§11.2**: JSON Schema `$id` and Protobuf `package` as in §0005.6.
- **§12**: "Schemas are never fetched automatically from `@schema` references. Tools MAY fetch them when the user has enabled it (§6.9), only over HTTPS and only for qualified names outside the special-use domains, and MUST check fetched schemas against the reference's fingerprint and the catalog's pins. A project catalog cannot enable fetching."
- **§13**: a **schema catalog** conformance class: §6.9 lookup order, conflicts and pins.
- **Appendix E**: the conventions table entry "Schema names: lowercase with `-_./` (enforced, §6.7)" becomes "qualified (`domain/path`) for schemas shared beyond one project; local names otherwise", and the lints of §0005.8 are added.

---

## 0005.12 Open questions and future work

1. **Signed schemas.** Pins check content, not authorship. A detached signature next to `{version}.novs`, verified against keys published at `https://{host}/.well-known/…`, would let a consumer trust a schema it has never seen before. That needs a key format and a well-known URI registration, and is better done once there are published schemas to sign.
2. **Version listings.** The default location serves exact versions only, which is all that lookup needs. A `https://{name}/versions.nova` index would let `nvf schema fetch acme.example/invoice` find the newest version, and let editors offer completions.
3. **A media type** for `.novs` (and `.nova`) files, so that servers can label them. Something like `application/vnd.nova.schema`, registered when the format reaches 1.0.
4. **Schemas that reference other schemas.** The schema language has no imports yet. When it gets them, they will name schemas with the same `name@version[#fingerprint]` references and resolve them with the lookup order of §0005.4.1, so catalogs are designed to serve that case as well.
5. **Community namespace.** Standards whose owners do not publish NOVA schemas (PDDL, for example) could live under a shared `novafile.dev/community/…` namespace, maintained in a repository of their own. Whether the project wants to curate that is a governance question, not a format question.
6. **A proxy or mirror protocol**, along the lines of Go's module proxy, so that organisations can serve all external schemas from one internal host. A catalog `remote` entry with prefix `""` (every name) would be the hook; it is not allowed yet because the prefix has to be a whole segment.
