# NOVA Proposal 0003: Labels and annotations

| | |
| --- | --- |
| Status | Draft proposal for discussion. Not normative until merged into SPEC.md. |
| Targets | §7.1 (filter selectors), §8.2 (envelope `meta`), a new non-normative conventions document (`docs/conventions/labels-annotations.md`), Appendix C |
| New kinds / tags / directives | none |
| Date | 2026-11-17 |

---

## 0003.0 Summary

Kubernetes `metadata.labels` and `metadata.annotations` answer two problems that appear in **any** system where many independent parties share typed objects:

1. **Cross-cutting grouping.** Objects need to be put into overlapping, non-hierarchical sets ("all frontend pods in prod on the canary track") by people who do not own the object's type. *Labels* are a small, flat string→string map with a deliberately weak selector language, so that sets are transparent and cheap to index.
2. **Decoration under a closed schema.** Tools need to attach their own data to objects whose schema they do not control, without colliding with each other or with future fields. *Annotations* are a namespaced, schema-exempt side channel.

Both needs are general. Most of the *shape* Kubernetes gave them is not: string-only values, 63-character limits, a 256 KiB cap, "beta annotations" that stood in for API fields, and `kubectl.kubernetes.io/last-applied-configuration` follow from Go's `map[string]string`, etcd sizing, the API-versioning process and client-side apply.

NOVA already has most of what it needs. Records with quoted keys, `map<string, V>` schema types, filter selectors (`[?labels.tier=web]`), keyed patches, spreads in templates and value-level revisions cover labels and annotations as **ordinary schema-declared fields**. A schema-exempt channel (`$meta`, `@labeled`) would weaken NOVA's closed-by-default guarantee, break the positional profile and duplicate what schemas already express.

**Recommendation: option (B+).** Do the following:

- write a **conventions document** that fixes the field names (`labels`, `annotations`), their types, and the key syntax `[prefix/]name` with DNS-owned prefixes;
- make **two small, general spec changes** that labels expose but do not uniquely need:
  - **existence, absence and `in` filters** in §7.1;
  - a **namespaced-key extension rule** for the §8.2 envelope `meta`.

Everything else is **YAGNI** for a serialization format: a reserved metadata record, schema-exempt fields, ownership and field managers, size limits, label indexing, and annotations as a field incubator.

| Facet | Recommendation |
| --- | --- |
| Where labels live | An ordinary optional field `labels?: map<LabelKey, string>` that the schema author declares on the record types that are selected |
| Where annotations live | An ordinary optional field `annotations?: map<QualifiedKey, any>`. Values are **typed NOVA values**, not strings |
| Key syntax | `[prefix "/"] name`. `prefix` is a lowercase DNS subdomain (≤ 253) owned by the writer; `name` matches `[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?` (≤ 63). Unprefixed keys belong to the document's author. Same grammar as Kubernetes "qualified names" for interop |
| Part of the value / revision? | **Yes.** Like Kubernetes, and as NOVA's model (§2.13) requires |
| Selectors | Existing: `[?labels.tier=web]`, `[?labels."app.kubernetes.io/name"=shop]`. New (general): `[?labels.canary]` (exists), `[?!labels.canary]` (absent), `[?labels.tier in [web, api]]` |
| Envelope `meta` | Unprefixed `meta` field names stay reserved for the spec. Producers MAY add namespaced fields (`ci.example.com/run-id`). Annotations are **not** envelope `meta`: one describes the stored object, the other describes one observation of it |
| Ownership | A convention only: a prefix's owner writes its keys, using base-less conditional patches. No managed-fields machinery |
| Rejected | Schema-exempt `$meta` channel, `@labeled` schema keyword, spec-level size or charset limits on values, hashing that excludes annotations, "annotation → field" promotion as a blessed workflow |

---

## 0003.1 Motivation and question

NOVA has closed records by default (§6.1, §6.4 rule 5), schema-checked SemVer evolution (§6.5–6.7), path filters (§7.1), conditional patches (§7.4–7.5), an agent envelope that separates `value` from `meta` (§8.2), and comments that are explicitly *presentation* (§3). Two questions follow:

- Is there a **general** benefit in a recognised "labels/annotations" notion?
- Or did Kubernetes need these maps only because of its own shortcomings?

The answer below separates the two. The general benefit is real, but it lives mostly in **conventions**, because a format, unlike an API server, does not index, own or arbitrate objects.

---

## 0003.2 Prior art

Sources marked ✔ were read from primary text (project repositories fetched over raw GitHub) during this research. Sources marked ○ come from background knowledge because their hosts (kubernetes.io, queue.acm.org, AWS and GCP documentation, rfc-editor.org, w3.org, docs.docker.com, git-scm.com, whatwg.org) were not reachable from the research environment. **Re-check every ○ item before this text becomes normative.**

### 0003.2.1 Kubernetes: what the original design said ✔

The pre-1.0 design document `docs/design/labels.md` (tag `v0.5`) gives the motivation in its own words:

> "Service deployments and batch processing pipelines are often multi-dimensional entities (e.g., multiple partitions or deployments, multiple release tracks, multiple tiers, multiple micro-services per tier). Management often requires cross-cutting operations, which breaks encapsulation of strictly hierarchical representations, especially rigid hierarchies determined by the infrastructure rather than by users. Labels enable users to map their own organizational structures onto system objects in a loosely coupled fashion, without requiring clients to store these mappings."

It also explains why the selector language is weak on purpose:

> "The simplicity of label selectors is deliberate. It is intended to facilitate transparency for humans, easy set overlap detection, efficient indexing, and reverse-indexing (i.e., finding all label selectors matching an object's labels …)."

It explains why sets are formed by attribute and not by enumeration. Labels are *reversible*: "with sets formed by just explicitly enumerating members, one would (conceptually) need to search all sets to determine which ones a pod belonged to."

Its reason for splitting labels from annotations is about **indexing cost**, not semantics:

> "We'll eventually index and reverse-index labels for efficient queries and watches, use them to sort and group in UIs and CLIs, etc. We don't want to pollute labels with non-identifying, especially large and/or structured, data. Non-identifying information should be recorded using annotations."

At that stage label syntax was "24 characters or less, all lowercase", and "Namespacing of label keys is under discussion". Prefixes came later.

The original `docs/annotations.md` (tag `v1.0.0`) says annotations hold data that "may be large, may be structured or unstructured, may include characters not permitted by labels". It lists these uses:

- fields managed by a declarative configuration layer, "in order to facilitate merging";
- build, release and image information;
- pointers to logging and monitoring systems;
- client and tool information;
- provenance;
- "lightweight rollout tool metadata (config and/or checkpoints)";
- on-call contacts.

Its justification is the most general sentence in the whole design:

> "Yes, this information could be stored in an external database or directory, but that would make it much harder to produce shared client libraries and tools for deployment, management, introspection, etc."

### 0003.2.2 Kubernetes: what it became ✔

From the API conventions (`kubernetes/community`, `api-conventions.md`):

- **Labels** "are intended for organizational purposes by end users". Annotations "enable third-party automation and tooling to decorate objects with additional metadata for their own use".
- "Unprefixed keys (e.g. `key-name`) are reserved for end-users. Third-party components must use prefixed keys." The `kubernetes.io` and `k8s.io` prefixes are reserved, and such keys "are effectively part of the kubernetes API and may be subject to deprecation and compatibility policies".
- Key prefixes "should carry as much context as possible": prefer `subsystem.kubernetes.io/parameter` over `kubernetes.io/subsystem-parameter`.
- **Beta annotations.** "In early versions of Kubernetes, some in-development features represented new API fields as annotations" (`something.beta.kubernetes.io/name`). This pattern is now deprecated: "Some such annotations may still exist, but no new annotations may be defined. New API fields are now developed as regular fields."
- "Beware that annotations aren't automatically handled by the API conversion machinery."
- "Inclusion of a system prefix in a label key is fairly hostile to UX."

Validation code (`kubernetes/apimachinery`):

- `TotalAnnotationSizeLimitB = 256 * (1 << 10)`, counted over keys plus values (`pkg/api/validation/objectmeta.go`).
- Prefixes are DNS-1123 subdomains (max 253).
- Selector operators are `In`, `NotIn`, `Exists` and `DoesNotExist` (`pkg/apis/meta/v1/types.go`).

From the current docs source (`kubernetes/website`, `labels.md`):

- Name segment ≤ 63 characters. A non-empty value ≤ 63 characters.
- "The label selector is the core grouping primitive in Kubernetes."
- `tier != frontend` also selects "all resources with no labels with the `tier` key". Negative operators match absent keys.

From the server-side apply KEP (`kubernetes/enhancements`, KEP-555):

- The `last-applied-configuration` annotation "tracks ownership for a single shared field manager".
- SSA replaces it: "the control plane will track a 'manager' for every field", and conflicts can be forced.
- `managedFields` itself "can represent up to 60% of the total size of an object".

The issue *"Large CRDs go over size limits"* (kubernetes/kubernetes#82292) records that large CRDs mainly ran into "the client-side-apply annotation limit". The 256 KiB annotation cap, the error text "metadata.annotations: Too long: must have at most 262144 bytes", and `last-applied-configuration` doubling an object's size are ○ for the error string.

### 0003.2.3 Survey across systems

The columns mean:

- **Sel?** — used for selection or identity;
- **Key namespacing** — how keys avoid collisions;
- **Values** — the value type;
- **In identity/hash** — whether the data is part of the object's identity or hash.

| System | Sel? | Key namespacing | Values | Limits | In identity/hash | Lesson for NOVA |
| --- | --- | --- | --- | --- | --- | --- |
| **Borg** job names ○ | yes, by regex on names | none | encoded in the name string | name length | the name *is* identity | Encoding attributes into identifiers is the failure that labels fixed ("Borg, Omega, and Kubernetes", 2016 ○) |
| **K8s labels** ✔ | yes (equality and set selectors) | `[dns-prefix/]name`; unprefixed = user | string ≤ 63 | name ≤ 63, prefix ≤ 253 | part of the object (resourceVersion bumps); not identity | Weak selectors on purpose; negative operators match absent keys |
| **K8s annotations** ✔ | no | same as labels; third parties MUST prefix | string (JSON inside strings in practice) | 256 KiB total | part of the object | Stringly typed; no conversion between API versions; once used as a field incubator |
| **Prometheus labels** ✔ | yes; labels **are** series identity | `__` prefix reserved | string; empty = absent | none in the model (cardinality is the practical limit ○) | yes: changing any label "will create a new time series" | Identity labels and descriptive data must be kept apart, or cardinality explodes |
| **OCI image annotations** ✔ | no | reverse DNS (`com.example.key`); `org.opencontainers` reserved | string | — | inside the manifest, so in the digest | "Consumers MUST NOT generate an error if they encounter an unknown annotation key." Standard keys (`org.opencontainers.image.source` …) replaced the community label-schema.org keys |
| **Docker `LABEL`** ○ | yes (`--filter label=`) | reverse-DNS recommended | string | — | in the image config, so in the digest | Docker labels are OCI annotations under another name; one concept, two words |
| **AWS tags** ○ | yes (cost allocation, IAM conditions, Resource Groups) | `aws:` reserved | string | 50 tags/resource, key 128, value 256 | not identity | Tags drive *policy* (IAM `aws:ResourceTag`), so they carry security weight |
| **GCP labels vs. network tags** ○ | labels: billing and filtering; network tags: firewall targeting; Resource Manager tags: IAM/policy | lowercase keys | labels string ≤ 63; network tags are a *set of strings* | 64 labels | not identity | One provider needs **three** constructs because "selection for billing", "selection for network policy" and "selection for access control" have different trust levels |
| **S3 metadata vs. tags** ○ | metadata: no; tags: yes (lifecycle, IAM, replication) | `x-amz-meta-` | string | metadata 2 KB and immutable after upload; ≤ 10 mutable tags | metadata is part of the object version; tags are not | The same split again: immutable descriptive data vs. mutable selectable data |
| **OpenTelemetry resource attributes** ✔ | yes (backends group by them) | dotted names from semantic conventions (`service.name`) | `AnyValue` (primitives, arrays, maps) | default 128 attributes; values truncated | immutable per Resource; merges are last-writer-wins | Typed values work. Shared **semantic conventions** (a registry of names) are worth more than syntax |
| **CloudEvents extension attributes** ✔ | yes (routing without decoding `data`) | flat `[a-z0-9]`, ≤ 20 recommended; no prefixes | small typed set (Boolean, Integer, String, Binary, URI, Timestamp) | — | part of the event | Attributes exist so intermediaries need not decode the payload. "Sensitive information SHOULD NOT be carried … in context attributes" |
| **HTTP / e-mail headers** ○ | partly (routing, content negotiation) | historically `X-`; RFC 6648 deprecates the `X-` convention | string | per server | not identity | Namespacing by "experimental" markers fails, because experimental names become permanent. Namespace by **owner**, not by status |
| **XML namespaces; attributes vs. elements** ○ | — | namespace URI per vocabulary | attributes: strings; elements: structured | — | part of the infoset | Per-vocabulary namespaces work, but URI-sized prefixes are heavy. "Attribute or element?" is the same debate as "annotation or field?" |
| **HTML `data-*`** ○ | yes (CSS attribute selectors, `querySelector`) | the `data-` prefix only | string | — | part of the DOM | A schema-exempt extension point inside a closed vocabulary works because the vocabulary (HTML) is owned by someone else |
| **JSON-LD `@context`** ○ | — | IRIs | any JSON | — | — | Global names by indirection. Too heavy for NOVA's goals (hidden meaning, needs fetching) |
| **Protobuf custom options / `Any`** ✔ (`Any`), ○ (options) | — | options: extension field numbers; `Any`: `type_url` | typed messages | — | part of the descriptor / message | Typed extension slots are possible ("Do not attempt to contact type URLs"). Field-number registries are a coordination cost |
| **Git notes** ○ | no | ref namespace (`refs/notes/<ns>`) | blob | — | **not** in the commit hash | Annotating without changing identity needs out-of-object storage |
| **ID3v2 `TXXX` frames** ○ | no | free-text description per frame | string | — | part of the file | User-defined slots in a closed frame set: the same pattern as annotations |

### 0003.2.4 Lessons

1. **Grouping by attribute, not by hierarchy or enumeration, is a general need.** It recurs in Borg → Kubernetes, AWS/GCP tags, Prometheus and OTel. It solves a real problem: many overlapping, cross-cutting sets that are cheap to reverse-map.
2. **A namespaced side channel is needed wherever the schema owner and the data writer differ.** Kubernetes (project-owned types), OCI (spec-owned manifest), HTML (WHATWG-owned elements), ID3 and CloudEvents all have one. Systems where the user owns the schema need it less.
3. **Owner-based namespacing beats status-based namespacing.** DNS or reverse-DNS prefixes (Kubernetes, OCI, Java) have aged well. `X-` and `*.beta.kubernetes.io` have not: both were deprecated.
4. **Labels and annotations differ by cost, not by meaning.** Labels are indexed, so they must be small and flat. A format has no index, so the split is a convention about *intended use*, not a structural necessity.
5. **Stringly typed side channels decay into configuration languages.** Kubernetes annotations carry JSON, YAML and even code snippets inside strings: ingress-nginx configuration snippets, and CVE-2021-25742 ○. OTel and CloudEvents show that typed values are feasible.
6. **The side channel is part of the object.** Kubernetes, OCI, CloudEvents and S3 metadata include it in the object and its digest. Git notes are the counterexample, and they pay for it with separate storage and sync.
7. **The real costs are churn and ownership.** Frequently changing annotations (heartbeats, leader election records ○) bump the object version and cause conflicts for everyone else. Ownership of keys needed SSA's `managedFields`, which can reach 60% of an object's size.

---

## 0003.3 Which problems are inherent, which were Kubernetes-specific

| Problem | Inherent to (a) many tools share objects | (b) closed schemas | (c) selection queries | (d) tool ownership/provenance | Kubernetes-specific? |
| --- | --- | --- | --- | --- | --- |
| Overlapping, non-hierarchical sets of objects | ✔ | | ✔ | | No |
| Selectors simple enough to index and reverse-index | | | ✔ (only with an index) | | Mostly an **API-server** concern; a format has no index |
| Somewhere for third-party data despite closed types | ✔ | ✔ | | ✔ | No, but its strength depends on who owns the schema (in Kubernetes: the project, until CRDs) |
| Collision-free keys among independent writers | ✔ | | | ✔ | No |
| Co-locating tool data with the object ("not an external DB") | ✔ | | | ✔ | No |
| string→string only | | | | | **Yes**: Go `map[string]string` in `ObjectMeta`, JSON/protobuf API types |
| 63-char names and values, DNS-like charset | | | partly (labels flow into DNS names, env vars, selectors in URLs ○) | | **Yes** |
| 256 KiB annotation cap | | | | | **Yes**: etcd request size (~1.5 MiB ○) and watch fan-out |
| `*.beta.kubernetes.io` fields as annotations | | ✔ (types could not change quickly) | | | **Yes**: the API review and versioning process; now forbidden |
| `last-applied-configuration` | ✔ (needs 3-way merge state) | | | ✔ | **Yes**: client-side apply with no server merge. Replaced by SSA `managedFields` |
| Annotations not converted across API versions | | ✔ | | | **Yes**: the conversion machinery |
| No validation of annotation contents | | ✔ | | | Consequence of string-typed and schema-exempt design |

**Problems annotations caused** (✔ unless marked):

- **Stringly typed configuration.** No types and no validation; JSON is embedded in strings. Typos in keys are silently ignored, because unknown annotations MUST be tolerated in OCI and are tolerated in practice in Kubernetes.
- **Hard size limits** that broke `kubectl apply` for large CRDs (#82292).
- **Duplication and migration debt.** Beta annotations lived on next to the fields that replaced them ○.
- **Prefix rules that are "hostile to UX"** for labels.
- **Security.** Annotations interpreted as configuration by controllers (ingress snippets) became an injection vector ○.
- **Churn.** Volatile annotations bump `resourceVersion`.

---

## 0003.4 Mapping to NOVA

### 0003.4.1 What NOVA can already express (no spec change)

```
@schema shop@1.0.0
services:
  - id: api
    image: ghcr.io/example/api:v5
    replicas: 5
    labels:
      tier: backend
      track: stable
      "app.kubernetes.io/part-of": shop
    annotations:
      "ci.example.com/build":
        run: 48213
        commit: "9f2c1e7"
        finished_at: @timestamp("2026-11-17T15:58:02Z")
      "oncall.example.com/team": payments
```

```
# schema
type LabelKey = string @len(1..317)        # 253 + "/" + 63
record Service:
  id: string @key @id(1)
  image: string @id(2)
  replicas: u16 @id(3)
  labels?: map<LabelKey, string> @id(14)
  annotations?: map<string, any> @id(15)
```

- **Keys.** `"app.kubernetes.io/part-of"` is a quoted record key (§4.3). Paths reach it with a quoted name: `services[id=api].labels."app.kubernetes.io/part-of"` (§7.1 `name = identifier | quoted-string`).
- **Types.** `map<string, V>` accepts the stored record by resolution (§6.3, "keys become strings"). The reference implementation does this in `novafile-schema/src/resolve.rs` ✔. `novafile-serde` maps a Rust `HashMap<String, String>` to a record ✔, so labels round-trip as records and export to JSON as objects.
- **Selection.** `@get services[?labels.tier=backend].{id,replicas}` works today.
- **Patching.**
  - `+ services[id=api].labels.track: canary` adds a label (§7.5: `P` is a record or map, so the entry is added).
  - `services[id=api].labels.track: stable -> canary` relabels with compare-and-swap.
- **Templates.** Common labels are a spread:
  ```
  @let common = {team: payments, "app.kubernetes.io/part-of": shop}
  services:
    - id: api
      labels:
        ...$common
        tier: backend
  ```
- **Binary and positional.** These are ordinary fields with `@id`s, so the positional profile (§4.12) and `novafile-proto` (`map<string,string>` → proto `map`) both work. Repeated label keys benefit from string back-references (§5.3).

The general need — grouping plus decoration — is therefore already met **by schema authors who opt in**. What is missing is (i) a shared vocabulary, so that tools can rely on the field names and key syntax, and (ii) two expressiveness gaps in filters.

### 0003.4.2 Option space for the side channel

| Approach | Pros | Cons |
| --- | --- | --- |
| **`@open` records** | Zero ceremony | Opens the *whole* record: typos in real fields are no longer caught. Third-party keys share the field namespace, so a later schema version that adds a field with the same name silently changes meaning. Unknown fields are untyped. Positional encoding is impossible (§4.12) |
| **Schema-declared `labels`/`annotations` fields** (recommended) | Typed and validated; visible in the schema; positional and proto work; no new spec concept; the schema author decides which types are annotatable | Every schema must declare them; a tool cannot annotate a type whose author did not opt in |
| **Schema-exempt reserved field** (`$meta`, `@meta`, or a keyword `record Service @labeled`) | Universal: every record can be labelled; tools need no schema cooperation | Breaks "closed by default" and "the schema describes the whole value". It needs special cases in validation, positional, proto, JSON mapping, diff and templates (`$` is the template reference sigil, §9.2). It reintroduces Kubernetes' string-typed, unconvertible channel. Most NOVA schemas are owned by their users, so the cooperation problem is small |

The deciding point: **in Kubernetes, the schema owner (the project) and the annotator (any controller) are different parties, and changing the schema took a release.** In NOVA, schemas are typically owned by the same organisation that runs the tools, and adding an optional field is a checked MINOR release (§6.5, §6.7). Inherent problem (b) is therefore much weaker here. Where it does exist — a published third-party schema — the schema author can declare `annotations?: map<string, any>` once, and a convention makes that declaration uniform.

### 0003.4.3 Interaction with the §8.2 envelope `meta`

These are different things and must stay different:

| | Envelope `meta` | Annotations |
| --- | --- | --- |
| Describes | One **observation or result**: who returned it, when, whether it was verified, with what confidence | The **stored object** itself |
| Lifetime | One tool response | Persisted with the object |
| Part of the value / revision | No: "Consumers MUST NOT merge `meta` into `value`" | Yes |
| Written by | The tool producing the result | Any tool, via patches |

**Rules that follow:**

- An object's annotations travel **inside `value`**.
- If an agent wants to *persist* provenance (for example "verified by deploy-checker at T"), it writes an annotation with a patch. It never copies `meta` into `value` implicitly.
- **Gap in §8.2.** The text lists `meta` fields "with defined meanings when present", but does not say whether *other* fields are allowed, or how third parties name them. That is exactly the annotation-key problem. Proposed: unprefixed `meta` field names are reserved for this specification, and producers MAY add fields whose names are qualified keys with a prefix (`ci.example.com/run-id`). Consumers MUST ignore prefixed fields they do not understand.

### 0003.4.4 Revisions and hashing

- Annotations and labels are part of the value, so they are part of the revision (§2.13). This is the same as Kubernetes `resourceVersion` and OCI digests, and it is the only option consistent with "two values are equal iff their canonical encodings are identical".
- Excluding them (Git-notes style) would let two different values share a revision and break compare-and-swap. **Rejected.**
- **Consequence: churn.** When a tool annotates a document, every pending whole-document `@base` precondition goes stale. NOVA already has the remedy, and the convention should spell it out:
  - Tools that write annotations SHOULD send **base-less** patches whose operations are conditional (`old -> new`, `? path`), scoped to their own key:
    ```
    @patch
    @scope services[id=api].annotations
    ? "ci.example.com/build"
    = "ci.example.com/build": {run: 48214, commit: "1c0ffee", finished_at: @timestamp("2026-11-17T16:20:00Z")}
    ```
  - Highly volatile data (heartbeats, progress) SHOULD NOT be stored as annotations. This is the Kubernetes lesson that moved leader election to `Lease` objects ○.
- A per-scope revision (a precondition on the revision of the `@scope` value, not the whole document) would help every concurrent writer, not just annotators. It is listed as an open question, not part of this proposal.

### 0003.4.5 Patches and ownership

- Kubernetes needed `managedFields` because the **server** merges declarative intent from several appliers. NOVA patches are explicit operations with compare-and-swap; there is no "apply" that must infer deletions. Field managers are therefore **YAGNI** at the format level.
- **Convention.** The owner of prefix `p` is the only writer of keys `p/*`. Unprefixed keys belong to the document's author or human editors.
- **Enforcement** belongs to hosts. §7.5 step 2 already lets a host bind a singular scope per tool call, for example `services[id=api].annotations`. That confines a tool to one object's annotations, but not to its own keys within them: "only keys with prefix `ci.example.com/`" is not expressible.
  - Do not add prefix scopes now. If hosts need this, a future "write policy" can be added generally, not just for annotations (open question 4).

### 0003.4.6 Queries and selectors

Kubernetes selector operators compared with NOVA filters today:

| Kubernetes | NOVA today | Gap |
| --- | --- | --- |
| `tier=web` | `[?labels.tier=web]` | — |
| `tier!=web` | `[?labels.tier!=web]` | **Semantics differ.** Kubernetes matches objects *without* `tier`. NOVA never matches a missing path (§7.1) |
| `tier in (web,api)` | none (filters combine only with AND) | needs OR or `in` |
| `tier notin (web,api)` | chain `[?labels.tier!=web][?labels.tier!=api]` (present only) | absent keys differ, as above |
| `canary` (exists) | approximated by `[?labels.canary!=null]` | a hack: fails for present `null` values |
| `!canary` (absent) | **not expressible** | — |

These are **general** filter gaps, not label gaps: "orders without a `shipped_at`" and "status in [failed, draining]" need the same thing. The proposal adds `exists`, `absent` and `in` (§0003.6.1).

NOVA keeps its own `!=` rule ("missing never matches"). A Kubernetes adapter translates `tier!=web` to `[?!labels.tier]` *or* `[?labels.tier!=web]`, which needs OR. The adapter can either report that it is inexact or run two queries; see open question 3.

### 0003.4.7 Schema evolution: annotations as an incubator

Kubernetes used annotations as an incubator because adding a field to a stable API was slow. The result was duplicated state and migrations, and the practice is now banned ✔.

In NOVA, adding an optional field is a checked MINOR bump. The incubator has no reason to exist, and promoting `annotations."x.example.com/foo"` to a field `foo` is a data migration that NOVA cannot make transparent (different paths, and therefore different patches and selectors).

The conventions document should say: **annotations are for data the schema author does not own, not for fields the schema author has not written yet.**

### 0003.4.8 Comments vs. annotations

| | Comment (§3) | Annotation |
| --- | --- | --- |
| Reader | humans | tools (and humans) |
| Part of the value / revision | no | yes |
| Survives text → binary → text | no (document-preserving editors only) | yes |
| Addressable by paths, patches, queries | no | yes |

Rule of thumb for the conventions document: **if a program ever reads it, it is an annotation; if only people read it, it is a comment.** A "do not edit — managed by X" banner is a comment for humans. The machine-checkable equivalent is an annotation `"x.example.com/managed": true`.

### 0003.4.9 Labels vs. `@key`

Labels are **non-identifying**: many objects share them. `@key` (§6.2) is identity: unique per list, and it makes selectors singular, which patches require. The two never substitute for each other:

- A filter on labels is never singular, so it cannot target a patch.
- `@key` fields cannot be relabelled without changing identity.

Prometheus is the warning case: there, labels *are* identity, and every label change creates a new series.

### 0003.4.10 Value types

- **Label values: strings only (recommended).**
  - Selectors stay unambiguous. In NOVA `3` and `"3"` are different values, and `[?labels.v=3]` would not match `v: "3"`.
  - Labels map 1:1 to Kubernetes, Prometheus, AWS and GCP.
  - **Cost:** under a `map<_, string>` schema, `version: 3` in a document is an int, and resolution never converts numbers to strings (§6.3). Authors must quote: `version: "3"`. This is NOVA's "no surprising conversions" principle working as intended. The error message should suggest quoting.
- **Annotation values: any NOVA value.** This is the main improvement over Kubernetes: no JSON-in-strings. Schema authors MAY narrow it (`map<string, AnnotationValue>`) or define per-key types in a typed record they control.
- **Size limits:** none in the format. Hosts already need resource limits (§12). A conventions document can recommend label sizes compatible with Kubernetes (≤ 63) for portability.

---

## 0003.5 Options and recommendation

| Option | What | Benefit | Cost / risk |
| --- | --- | --- | --- |
| **(A) Do nothing** | Users model labels and annotations in schemas as they like | No spec surface | Every tool invents `tags`, `labels`, `meta`, `extra` and `x_*`. There is no shared key syntax, so collisions return. The `exists` and `in` gaps remain |
| **(B) Conventions document only** | Recommended field names and types, key grammar, ownership and churn guidance, interop mapping | Shared vocabulary at zero normative cost. Tools (LSP completions, `nvf get` docs, Kubernetes/OCI adapters) can rely on it | Selector gaps remain. Envelope `meta` extensibility stays ambiguous |
| **(B+) Conventions + two general spec changes** (recommended) | (B), plus §7.1 `exists`/`absent`/`in` filters and the §8.2 namespaced-`meta` rule | Fixes real expressiveness gaps that also help non-label data. Keeps closed-by-default intact | Small grammar growth in the path language, which must stay non-Turing-complete (it does: no OR of arbitrary filters, no functions) |
| **(C) First-class spec support** | Reserved `$meta`/`@meta` record on every record or document, `@labeled` schema keyword, spec-level key grammar, size and charset limits, ownership in patches | Universal annotatability without schema cooperation | Breaks closed-by-default, positional and proto mappings. Duplicates schemas. Imports Kubernetes-specific limits into a format. Ownership machinery is a server concern. Large surface for a need mostly met by (B) |

**Pick (B+).** It keeps the general part of the Kubernetes design:

- user-owned grouping by flat labels;
- an owner-namespaced decoration channel;
- typed values (an improvement on Kubernetes);
- annotations as part of the value.

It drops the parts that came from Kubernetes' server, storage and versioning constraints.

### YAGNI list (explicitly not proposed)

- A schema-exempt metadata channel, or a reserved `$meta`/`@meta` field.
- A `@labeled` / `@annotated` schema keyword. A field declaration is one line, and the keyword would only save typing.
- Spec-level length, charset or count limits on label values or annotations. These are host policy.
- Field managers / `managedFields`, or any ownership tracking in the value.
- Label indexing requirements, reverse-index semantics, or a separate "label selector" language distinct from §7.1 filters.
- Excluding annotations from revisions.
- An "annotation → field" promotion mechanism, or `*.beta.*` naming.
- JSON-LD-style global vocabularies, or `@context` indirection.
- Selector OR, regex or prefix matching (`[?labels has-prefix "ci.example.com/"]`) until a concrete use appears.

---

## 0003.6 Spec sketches

### 0003.6.1 §7.1 Filters: existence, absence, membership (normative, general)

Grammar change (replacing the filter alternative of `selector`):

```
selector   = "*" | int | identifier "=" flow-value | flow-value
           | "?" filter
filter     = path cmp flow-value                 ; comparison (unchanged)
           | path SP "in" SP flow-list           ; membership
           | path                                ; existence
           | "!" path                            ; absence
flow-list  = "[" [flow-value ("," flow-value)*] "]"
```

Proposed text:

> - `[?p]` selects elements for which the relative singular path `p` **resolves**, whatever its value, including `null`.
> - `[?!p]` selects elements for which `p` does **not** resolve. Per §7.2, *not found* is the only resolution failure that counts as absence. A *type mismatch* (e.g. `p` traverses a string) also counts as absence. *Ambiguous* is impossible because `p` is singular.
> - `[?p in [v1, …, vn]]` selects elements for which `p` resolves and **equals** (by the rules of `=` above, so numeric kinds compare numerically) at least one `vi`. An empty list matches nothing.
> - The existing rule "an element where `p` does not resolve never matches" applies to comparisons and `in`. Hence `[?p!=v]` does not select elements lacking `p`. Write `[?!p]` for those.
> - There is no general OR, and there is still no `notin`. Use a chain of `!=` filters for present values.

Examples:

```
@get services[?labels.tier in [frontend, edge]].id
@get services[?labels.canary].id              # has a canary label
@get services[?!labels."app.kubernetes.io/part-of"].id   # unlabelled services
@get orders[?!shipped_at][?status in [!paid, !packed]].id   # also non-label use
```

Ambiguity check. `!` already starts variant literals (`!paid`), but only in *value* position. In `[?!p]` the `!` directly follows `?` in *path* position, where variants cannot occur. `in` cannot be confused with a field named `in`, because it follows a complete path and is surrounded by spaces. A field literally named `in` is reached as `[?in in [..]]` or `[?"in"=…]`.

### 0003.6.2 §8.2 Envelope `meta` extension fields (normative)

Add after the `meta` table:

> Field names in `meta` that do not contain `/` are reserved for this specification. A producer MAY add other fields whose names are **qualified keys** (Appendix E). Consumers MUST ignore qualified fields they do not understand and MUST NOT treat them as part of `value`. `meta` describes the result, not the domain object. Annotations of the domain object, if any, are part of `value`.

```
@envelope result
value:
  id: api
  replicas: 8
  annotations:
    "ci.example.com/build": {run: 48214}
meta:
  source: deployment-api
  observed_at: @timestamp("2026-11-17T16:21:00Z")
  verified: true
  "deployment-api.example.com/request-id": "req_7f3a"
```

### 0003.6.3 Appendix E (new, normative grammar only): qualified keys

A small grammar shared by the conventions document and §8.2, so that one definition exists:

```
qualified-key = [prefix "/"] key-name
prefix        = dns-label ("." dns-label)*              ; ≤ 253 octets, lowercase
dns-label     = alnum-lower [ (alnum-lower | "-")* alnum-lower ]   ; ≤ 63
key-name      = alnum [ (alnum | "-" | "_" | ".")* alnum ]         ; ≤ 63
```

> A key with a prefix is owned by whoever controls the DNS name `prefix`. Unprefixed keys belong to the document's author. Prefixes ending in `<nova-domain>` are reserved for this specification. This grammar is identical to Kubernetes "qualified names", so labels and annotations copied from Kubernetes objects are valid NOVA qualified keys.

(The schema language has no pattern attribute, so a schema can bound only the length (`@len(1..317)`), not the grammar. See open question 2.)

### 0003.6.4 Conventions document (non-normative): `docs/conventions/labels-annotations.md`

Contents, in brief:

1. **Field names.** Use `labels` and `annotations`, directly on the record type that is selected or decorated (`services[*]`, not a nested `metadata` record). Paths stay short (`[?labels.tier=web]`) and the names cannot collide with envelope `meta`. When mirroring Kubernetes objects, keep `metadata.labels` and `metadata.annotations` unchanged.
2. **Types.**
   ```
   type QualifiedKey = string @len(1..317)
   record Example:
     labels?: map<QualifiedKey, string>
     annotations?: map<QualifiedKey, any>
   ```
   Give them `@id`s like any field. The canonical *stored* form is a record with quoted keys.
3. **Labels**:
   - small, flat, string values;
   - used to form sets;
   - ≤ 63-character values recommended for portability;
   - never identity (use `@key`);
   - user-owned when unprefixed.
4. **Annotations**:
   - any NOVA value;
   - keys from third-party tools MUST be prefixed;
   - not for fields the schema author intends to add;
   - not for volatile status;
   - not for secrets (a CloudEvents lesson).
5. **Writing.** Use base-less patches with conditional operations, scoped to the writer's key. Every write changes the document revision.
6. **Comments vs. annotations.** Programs read annotations; people read comments.
7. **Interop.**
   - Kubernetes, Prometheus, OCI, AWS and GCP labels and tags map to `labels` (string values).
   - OCI annotations and Kubernetes annotations map to `annotations` with string values. NOVA → Kubernetes conversion of non-string annotation values MUST be reported as lossy: render the canonical text (§4.10) as a string.
   - OTel resource attributes map to `annotations` (typed), or to `labels` for the subset used for grouping.
   - Reverse-DNS OCI keys (`org.opencontainers.image.source`) are valid unprefixed key names and are kept verbatim. Tools SHOULD NOT rewrite them.
8. **Selector translation table** (Kubernetes → NOVA), including the inexact `!=`/`notin` cases.

---

## 0003.7 Open questions

1. **`map` vs. record for string-keyed dictionaries.** A schema type `map<string, V>` *resolves* a stored record into a `map`. Export of the resolved value to JSON then gives `[[k, v], …]` pairs (§11.1), while export of the stored value gives an object. Should NOVA add a "dictionary record" type (for example `record<V>` or `{string: V}`: a record whose field names are arbitrary and whose values are `V`)? It would also serve environment variables, HTTP headers and similar data. This is general, not label-specific.
2. **Key grammar in schemas.** Should the schema language gain `@pattern("…")`, or a named built-in format (`@format(qualified-key)`), so that `[prefix/]name` can be validated? Regexes raise portability and ReDoS questions (§12).
3. **OR in filters.** Translating Kubernetes `!=`/`notin` exactly needs "absent OR not equal". Is `[?!p | p!=v]` worth adding, or should adapters run two queries and merge? The recommendation is to defer.
4. **Write policies for hosts.** Should §7.5's host-bound scope generalise to a set of permitted path *prefixes* (including "keys with prefix `ci.example.com/`")? The recommendation is to defer until hosts ask for it.
5. **Per-scope revisions.** Should a patch be able to precondition on the revision of its `@scope` value instead of the whole document? This would reduce churn conflicts from annotation writers and any other concurrent writers.
6. **Label values beyond strings.** Allow `bool` and `int` values in labels, accepting the `3` vs. `"3"` trap in exchange for unquoted documents?
7. **Reserved prefix.** Which DNS name does the NOVA project own for its reserved keys (`<nova-domain>`)?
8. **A standard schema module.** Without schema imports, the convention's type definitions must be copied into each schema. Is that acceptable, or should the schema language gain imports (or well-known types such as `nova.QualifiedKey`)?
9. **Semantic conventions registry.** OTel's value comes from its named attributes (`service.name`), not its syntax. Should NOVA publish a small registry of well-known annotation keys (provenance: `<nova-domain>/source`, `…/generated-by`), or leave that to ecosystems?

---

## 0003.8 References

✔ = read from the primary source during this research; ○ = cited from background knowledge (host not reachable from the research environment).

- ✔ Kubernetes, *Labels* design document (pre-1.0, tag `v0.5`). https://github.com/kubernetes/kubernetes/blob/v0.5/docs/design/labels.md
- ✔ Kubernetes, *Annotations* (tag `v1.0.0`). https://github.com/kubernetes/kubernetes/blob/v1.0.0/docs/annotations.md
- ✔ Kubernetes, `DESIGN.md` (tag `v0.5`), "Labels" section. https://github.com/kubernetes/kubernetes/blob/v0.5/DESIGN.md
- ✔ Kubernetes, *Identifiers* design (tag `v1.0.0`). https://github.com/kubernetes/kubernetes/blob/v1.0.0/docs/design/identifiers.md
- ✔ Kubernetes community, *API Conventions* (metadata; label, selector and annotation conventions; deprecated alpha-field annotations). https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md
- ✔ Kubernetes website source, *Labels and Selectors*. https://github.com/kubernetes/website/blob/main/content/en/docs/concepts/overview/working-with-objects/labels.md · rendered: https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/ (○)
- ✔ Kubernetes website source, *Annotations*. https://github.com/kubernetes/website/blob/main/content/en/docs/concepts/overview/working-with-objects/annotations.md · rendered: https://kubernetes.io/docs/concepts/overview/working-with-objects/annotations/ (○)
- ✔ `k8s.io/apimachinery`, `pkg/api/validation/objectmeta.go` (`TotalAnnotationSizeLimitB`). https://github.com/kubernetes/apimachinery/blob/master/pkg/api/validation/objectmeta.go
- ✔ `k8s.io/apimachinery`, `pkg/util/validation/validation.go` (qualified names, DNS-1123). https://github.com/kubernetes/apimachinery/blob/master/pkg/util/validation/validation.go
- ✔ `k8s.io/apimachinery`, `pkg/apis/meta/v1/types.go` (`LabelSelectorOperator`, `ManagedFields`). https://github.com/kubernetes/apimachinery/blob/master/pkg/apis/meta/v1/types.go
- ✔ KEP-555, *Server-side apply*. https://github.com/kubernetes/enhancements/blob/master/keps/sig-api-machinery/555-server-side-apply/README.md
- ✔ kubernetes/kubernetes#82292, *Large CRDs go over size limits*. https://github.com/kubernetes/kubernetes/issues/82292
- ○ B. Burns, B. Grant, D. Oppenheimer, E. Brewer, J. Wilkes, *Borg, Omega, and Kubernetes*, ACM Queue 14(1), 2016 (labels vs. Borg job names). https://queue.acm.org/detail.cfm?id=2898444
- ○ A. Verma et al., *Large-scale cluster management at Google with Borg*, EuroSys 2015. https://research.google/pubs/large-scale-cluster-management-at-google-with-borg/
- ○ M. Schwarzkopf et al., *Omega: flexible, scalable schedulers for large compute clusters*, EuroSys 2013. https://research.google/pubs/omega-flexible-scalable-schedulers-for-large-compute-clusters/
- ✔ Prometheus, *Data model* (labels, `__` prefix, empty = absent). https://github.com/prometheus/docs/blob/main/docs/concepts/data_model.md · https://prometheus.io/docs/concepts/data_model/
- ✔ OCI Image Format Specification, *Annotations*. https://github.com/opencontainers/image-spec/blob/main/annotations.md
- ○ Docker, *Dockerfile reference: LABEL* and *Object labels*. https://docs.docker.com/reference/dockerfile/#label
- ○ AWS, *Tagging AWS resources* (limits, `aws:` prefix). https://docs.aws.amazon.com/tag-editor/latest/userguide/tagging.html
- ○ AWS, *Categorizing your storage using tags* (S3 object tags) and *Working with object metadata*. https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-tagging.html · https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingMetadata.html
- ○ Google Cloud, *Organize resources using labels* (labels vs. network tags vs. tags). https://cloud.google.com/compute/docs/labeling-resources
- ✔ OpenTelemetry, *Resource SDK* and *Common: Attributes* (AnyValue, limits). https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/resource/sdk.md · https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/common/README.md
- ○ OpenTelemetry, *Semantic Conventions: naming*. https://opentelemetry.io/docs/specs/semconv/general/naming/
- ✔ CloudEvents specification (context attributes, extension attributes, privacy). https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md
- ○ P. Saint-Andre, D. Crocker, M. Nottingham, *Deprecating the "X-" Prefix and Similar Constructs in Application Protocols*, RFC 6648. https://www.rfc-editor.org/rfc/rfc6648
- ○ P. Resnick (ed.), *Internet Message Format*, RFC 5322. https://www.rfc-editor.org/rfc/rfc5322
- ○ W3C, *Namespaces in XML 1.0*. https://www.w3.org/TR/xml-names/
- ○ WHATWG, *HTML: custom data attributes (`data-*`)*. https://html.spec.whatwg.org/multipage/dom.html#embedding-custom-non-visible-data-with-the-data-*-attributes
- ○ W3C, *JSON-LD 1.1* (`@context`). https://www.w3.org/TR/json-ld11/
- ✔ Protocol Buffers, `google/protobuf/any.proto`. https://github.com/protocolbuffers/protobuf/blob/main/src/google/protobuf/any.proto
- ○ Protocol Buffers, *Custom options*. https://protobuf.dev/programming-guides/proto2/#customoptions
- ○ Git, `git-notes(1)`. https://git-scm.com/docs/git-notes
- ○ ID3v2.4.0 frames (`TXXX`). https://id3.org/id3v2.4.0-frames
- ○ CVE-2021-25742 (ingress-nginx custom snippets via annotations). https://github.com/kubernetes/ingress-nginx/issues/7837
- NOVA SPEC.md §1, §2.10–2.13, §3, §4.3, §4.12, §6.1–6.7, §7.1–7.6, §8.2, §9, §11.1. Reference implementation (https://github.com/novafile/nova): `crates/novafile-schema/src/resolve.rs` (map-from-record resolution), `crates/novafile-serde/src/lib.rs` (string-keyed maps serialise as records).
