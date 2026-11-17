# Proposal 0002: Streaming, massive documents and a TUI

| | |
| --- | --- |
| Status | Draft proposal for discussion. Not normative until merged into SPEC.md. |
| Targets | §2.13 (revisions), §4.2 (directives), §4.7/§4.9/§4.11 (text), §5.1–§5.5 (binary), §7.1–§7.5 (paths, queries, patches), §13–§14 (conformance, reference implementation) |
| New file kinds | NOVA Lines (`.novl`), indexed binary files (`.nvb` with an index locator frame), patch sidecars (`FILE.patches`) |
| New binary | frame flags `0x10 META` and `0x20 SHARED_DICT`; value tag `0x13 sized` (non-canonical) |
| New directives | `@columns`, `@key`, `@end` (NOVA Lines); `@expect` (patches) |
| New revision form | `tree:` Merkle revisions, alongside `sha256:` |
| New crates | `nova-stream`, `nova-doc`, `nova-tui` |
| Date | 2026-11-17 |

---

## 0. Summary

Today every NOVA tool loads the whole input, builds an owned `Value` tree, and only then works on it. That is fine for configuration files. It fails for logs, datasets, exports and model metadata, which reach gigabytes. Measurements of the current reference implementation (§3) also show that **block-syntax text parsing and wide records are quadratic**. A 74 MB human-text file takes **454 s** to hash and needs **2.1 GB** of RSS. Fixing that is a prerequisite for the rest of this proposal.

The recommendations, in one table:

| Area | Recommendation |
| --- | --- |
| Text record streams | **NOVA Lines** (`.novl`). Each non-blank, non-comment line is one complete flow value, as in JSONL but with NOVA's types. An optional header (`@nova`, `@schema`, `@columns {…}`, `@key id`) switches to **streaming-table mode**, where each line is a table row. An optional trailer `@end <count> [tree:<root>]` detects truncation. |
| Row count `[N]` | **Kept mandatory in documents.** There is no `[?]`. Unknown-length tables live only in NOVA Lines, where `@end` plays the role of `[N]`. A stream with no `@end` is reported as *open* (complete but unverified), not as an error. |
| `---` streams (§4.11) | Kept for multi-document configuration bundles. The spec gains an **indentation invariant**: continuation lines of multi-line flow values must be indented deeper than their owner. This closes a real ambiguity in which `---` inside a multi-line flow is split as a separator (§2.3). |
| Binary streams | Concatenated frames as today, plus **META frames** (flag `0x10`) carrying `!header`, `!dict`, `!index`, `!end` and a fixed 26-byte `!locator` at the end of the file. With `SHARED_DICT` (flag `0x20`), a frame's string table is pre-seeded from a stream dictionary. Writers batch 64–4096 records per frame. |
| String table | Stays per frame by default. A stream-scoped dictionary is opt-in through `SHARED_DICT`. Dictionaries are **immutable and identified by id**, so resync and random access still work. |
| Random access | An **index META frame** holding `u64` offset tables (frames, records, large subtrees), located through a fixed-size final locator frame. The file is still a valid frame stream. This follows the Parquet, Arrow-file and zip pattern of writing metadata at the end. |
| Skipping subtrees | A non-canonical wrapper tag **`0x13 sized`**: `0x13 varint(byte_len) value`. Its string-table entries are **scoped**: they are popped at the end of the wrapped value, so a reader can skip it in O(1) without losing back-reference state. Writers wrap only large containers (≥ 4 KiB by default). Canonical encoding is unchanged, so revisions are unchanged. |
| Lazy access | A borrowed **pull-event API** (`Event<'a>`) for text and binary, and a lazy **`ValueRef<'a>`** over memory-mapped binary. Literal and back-referenced strings are zero-copy, because the string table stores spans. |
| Streaming queries | Classify path segments as streamable (`.name`, `[n≥0]`, `[*]`, filters, projections) or as needing lookahead or buffering (`[-n]` in text, `[field=v]` uniqueness, `[v]` on sets and maps). Binary and `[N]` tables know counts up front, so `[-1]` is streamable there. |
| Hashing huge data | `sha256:` (§2.13) stays the definition of equality. It is computable in one pass only for list-shaped data with known counts. Add a **`tree:` revision**: a Merkle hash (RFC 6962-style for lists, key-sorted for records, hash-sorted for sets and maps). It is incremental, parallel and append-friendly, and gives cheap subtree revisions. Streams are identified by their `tree:` root. |
| Patches on huge data | A new patch directive **`@expect <rev>`** gives the revision of the value at `@scope`. Patches can then be checked without hashing the whole document. Streams are append-only. Edits to streams go to a **patch sidecar**, and `nvf compact` folds them in. |
| TUI | A separate crate `nova-tui` (ratatui + crossterm), also reachable as `nvf tui`. It has jless-style tree navigation, a visidata-style table view for uniform lists, `/` search, a `:` path and filter bar, breadcrumbs, and yank as path, NOVA or JSON. It is read-only by default. With `--edit`, every edit becomes a **conditional patch op**: it is previewed, applied atomically, undone with the inverse patch, and saved through **span-splicing**, so comments survive. Large files get a sidecar patch log instead of a rewrite. |

---

## 1. Motivation and goals

1. **Unbounded producers.** Logs, event feeds, LLM batch outputs and agent traces are produced incrementally and consumed by `tail -f`, by pipelines or by other agents. JSONL won because each line stands alone. NOVA has `---` text streams and binary frame streams, but no line-oriented record stream, no stream header, no truncation trailer and no stream identity.
2. **Large files.** Typical sizes are a 2–20 GB export, a 5 GB list of records, or a 300 MB configuration-like document with one huge list. Users want `nvf get`, `nvf hash` and a browser to work in roughly constant memory, and in time proportional to the bytes they actually touch.
3. **Interactive exploration and editing.** A TUI that understands NOVA's types, tables, paths and filters, schemas and the patch model, and that never silently loses comments.

Non-goals: a columnar analytics format (§4.1 explains why Parquet and Arrow stay out of scope), a database, and changing the value model.

---

## 2. Current state (what the code does today)

| Component | Behavior | Streaming obstacle |
| --- | --- | --- |
| `novafile-text` `Parser<'a>` (`crates/novafile-text/src/parser.rs`) | Recursive descent over a fully loaded `&str`. Builds an AST (`ast::Node`), then `Node::to_value` clones it into an owned `Value`. Optional span recording (`SpanMap`, sorted `Vec<Span>`) | The whole input must be in memory, and the AST and the `Value` coexist, so memory is about 2× the tree. There is no event or pull interface. |
| `novafile-value` codec (`crates/novafile-value/src/codec.rs`) | `decode(&[u8]) -> Value`, fully owned. `canonical_bytes` re-encodes each set or map child into its own `Vec<u8>` and sorts them (`sorted_children`) | Containers carry element counts but no byte lengths, so skipping a subtree means decoding it. Back-references (§5.3) make skipping stateful. |
| `novafile-binary` `FrameReader<'a>` | Iterates frames over `&'a [u8]`. Recovering mode resyncs on `NOVA` magic | Already streaming-friendly, because each frame has a byte `length`. Every frame is still decoded to an owned `Value`. |
| `novafile-patch` `select` (`query.rs`) | Evaluates paths over `&Value` and clones results | Needs the whole tree. |
| `novafile-cli` `load` | Reads the file (or stdin) to the end, detects the format, parses everything. `.jsonl` becomes one `Value::List` | No `--stream` mode. |
| `split_stream` (`novafile-text/src/lib.rs`) | Splits on any line that is exactly `---` | Ambiguous with multi-line flow values (§2.3). |

### 2.1 Measured baseline

The measurements were taken in a 4-vCPU Linux sandbox with a `--release` build of `novafile-cli`. The build came from a scratch copy of the workspace, with one in-progress line from a concurrent `SpanKind` edit removed so that it compiled. The dataset has 500,000 records of the form `{id, image, port, replicas, enabled, tags:[2], meta:{zone, cpu}}`. These are single runs, wall clock and peak RSS, so treat them as orders of magnitude.

| Input | Size | `nvf hash` time | Peak RSS |
| --- | --- | --- | --- |
| JSONL | 82.6 MB | 2.90 s | 937 MB |
| NOVA binary frame (`convert --to binary`) | 25.4 MB | 2.28 s | 933 MB |
| NOVA human text | 74.1 MB | **454 s** | 2,157 MB |
| NOVA compact text (no tables: records are nested) | 73.6 MB | (not run, same shape) | — |
| `sha256sum` of the JSONL (reference) | 82.6 MB | 0.08 s (~1 GB/s) | 13 MB |
| `wc -l` of the JSONL (reference) | 82.6 MB | 0.04 s | 13 MB |

**Scaling probes**, each on a single document:

| Shape | n = 50k | n = 100k | n = 200k |
| --- | --- | --- | --- |
| block list `- x{i}` | 4.7 s | 20.4 s | — |
| block record `k{i}: {i}` | 10.4 s | 43.6 s | — |
| flow list `[x0, x1, …]` | 0.02 s | 0.06 s | — |
| `@set[…]` | 0.03 s | 0.06 s | 0.16 s |
| JSON object with n keys | 4.0 s | 18.0 s | 62.3 s |
| binary record with n keys | 4.8 s | 21.8 s | 73.6 s |

### 2.2 Root causes (bugs to fix before any streaming work)

1. `crates/novafile-text/src/parser.rs:989`, in `block_list`: `let idx = items.iter().filter(|i| matches!(i, Item::Node(_))).count()` runs once per item, so the cost is **O(n²)** in list length. Keep a running counter instead.
2. `crates/novafile-text/src/parser.rs:643`, in `push_entry`: the duplicate-key check is a linear scan over the entries, which is **O(n²)** in fields per record. Use a `HashSet<&str>`, or a sorted check when n is small.
3. `crates/novafile-value/src/record.rs:57/77`: `Record::insert` calls `contains_key`, which is a linear `position`. Building a record therefore costs **O(n²)** in *every* input path: text, JSON and binary decode. Keep a lazily built hash index once a record exceeds about 16 fields, or check duplicates in bulk at construction (sort the key refs and compare neighbors).
4. `crates/novafile-value/src/codec.rs:128`: `Encoder::string` inserts every literal into a `HashMap<String, usize>` (an owned `String` plus SipHash) **even in canonical mode**, where back-references are never emitted. Skip the table when `canonical || !dedupe_strings`. Use a borrowed-key or FxHash table otherwise.
5. `sorted_children` calls `canonical_bytes` per child. Nested sets and maps are therefore re-encoded once per nesting level, and every child allocates its own `Vec`. Encode children into one arena buffer and sort `(start, end)` ranges.
6. `Node::to_value` deep-clones literals out of the AST, so peak memory is about the AST plus the `Value`. Make it consuming (`into_value(self)`), or build `Value` directly when no template is involved.

With items 1–3 disabled in a scratch build, which gives an upper bound, the 74 MB text file hashes in **4.70 s**, about 16 MB/s end to end, though still at 2.16 GB RSS. The 200k-key binary record hashes in **0.15 s**, down from 73.6 s. Stack sampling of the fixed build shows `malloc`, `realloc` and `free` dominating: `Vec` growth, `String` clones in `to_value`, the encoder's string `HashMap`, and dropping the tree. The memory blow-up is about **29×** the text size and **37×** the binary size. This is why §5 insists on borrowed and lazy access for large inputs. Fixing allocation alone will not reach "constant memory".

### 2.3 An ambiguity in §4.11

§4.7 allows flow values to span lines inside brackets with any indentation. This document parses (verified with the reference CLI) and yields `a = ["x", "---"]`:

```
a: [x,
---
]
```

`split_stream` would cut it into two invalid documents. Block strings are safe, because their content is always indented. Proposed fix (spec text in §8.1): the **indentation invariant**. Every continuation line of a multi-line flow value MUST be indented more than the line on which the value starts. A column-0 line is therefore always either a top-level entry, `---`, a directive, or a comment. This invariant is also what makes structural indexing (§5.6), parallel parsing (§5.7) and the TUI's lazy outline (§7.5) cheap.

---

## 3. Prior art

Legend: ✔ = read from primary text (spec or source) while preparing this proposal. ◐ = confirmed through search-result snippets of the primary documentation. ○ = from background knowledge, not re-verified here. `www.rfc-editor.org` and `arrow.apache.org` were not reachable from the research environment, so RFC text and Arrow docs were read via mirrors or the GitHub source where noted.

### 3.1 Streams

| Format | Framing | Header and schema | Truncation and recovery | Random access | Lesson for NOVA |
| --- | --- | --- | --- | --- | --- |
| **JSONL / NDJSON** ○ | One JSON text per `\n`-terminated line. Raw newlines cannot occur inside JSON strings | None | A bad line is skipped. A truncated last line is detectable only if it does not parse. A truncated *number* (`123` from `1234`) is undetectable | None, but splittable at any `\n` → embarrassingly parallel | One record per line is the property worth copying. NOVA quoted strings already forbid raw newlines (§4.6), so single-line flow values work. |
| **JSON Text Sequences, RFC 7464** ◐ ([datatracker](https://datatracker.ietf.org/doc/html/rfc7464)) | `RS` (0x1E) + JSON text + `LF` | None | RS lets a parser resync after garbage. The final LF is a "canary" that detects truncated top-level numbers and `true`/`false`/`null` | None | Every record needs an unambiguous *terminator*, not just a separator. In NOVA Lines the newline terminates, and `@end` guards the whole stream. |
| **CBOR Sequences, RFC 8742** ◐ ([rfc-editor](https://www.rfc-editor.org/rfc/rfc8742.html)) | Concatenated self-delimiting items, with no separator and **no end-of-sequence indicator**. Media type `application/cbor-seq` | None | No resync. A decoding error loses the rest | None | The same as today's NOVA binary *payloads* without frames. NOVA frames (magic + length + CRC) are strictly better. Keep them. |
| **Protobuf length-delimited** ✔ ([delimited_message_util.h](https://github.com/protocolbuffers/protobuf/blob/main/src/google/protobuf/util/delimited_message_util.h)) | `varint(size)` + message | Out of band (`.proto`) | None: "A delimited message is a varint encoding the message size followed by a message of exactly that size" | None | A length prefix makes per-record skipping O(1). NOVA frames already have this. |
| **Arrow IPC stream and file** ✔ ([Columnar.rst](https://github.com/apache/arrow/blob/main/docs/source/format/Columnar.rst)) | Messages: `0xFFFFFFFF` continuation, int32 metadata length, Flatbuffer metadata padded to 8 bytes, body | **Schema message first**. Dictionary batches before use. `isDelta` appends to a dictionary, otherwise it replaces it | EOS = `0xFFFFFFFF 00000000`, or close | File format: `ARROW1` magic, the stream, a footer (schema + block offsets), int32 footer size, `ARROW1` | The schema-first header and **dictionary-by-id with deltas** inform NOVA's `!header` and `!dict`. The footer-with-offsets pattern informs `!index`. |
| **Avro object container** ✔ ([spec](https://github.com/apache/avro/blob/main/doc/content/en/docs/%2B%2Bversion%2B%2B/Specification/_index.md)) | `Obj\x01`, header map (`avro.schema`, `avro.codec`), 16-byte **sync marker**. Blocks: object count, byte size, objects, sync | Schema in the header | Sync markers let readers split files and detect corrupt blocks | Splittable at sync markers | **Blocks of many records** with count and byte size are the right unit for compression and string-table amortization. NOVA frames already work as blocks. Also, Avro arrays may carry a *negative count followed by a byte size* "so readers can skip the block without decoding it", which is precedent for NOVA's optional `sized` wrapper. |
| **TOON** ✔ ([SPEC.md](https://github.com/toon-format/spec/blob/main/SPEC.md)) | Indentation-based. `key[N]{f1,f2}:` tabular arrays, one row per line, delimiter `,`, tab or `|` declared in the header | Column list in the header | `N` is required. Strict mode (the default) rejects count mismatches, non-strict decodes every row present | None. The spec recommends streaming row output but defines no streaming protocol | Validates NOVA's `[N]` design. Neither TOON nor NOVA has an unknown-length table, and NOVA Lines fills that gap without weakening `[N]`. |
| **Parquet** (contrast) ✔ ([README](https://github.com/apache/parquet-format/blob/master/README.md)) | `PAR1` … row groups → column chunks → pages … FileMetaData (Thrift compact) + 4-byte LE length + `PAR1` | In the footer | "File Metadata is written after the data to allow for single pass writing" | Footer → column chunks | Footer-at-end for single-pass writers. Columnar layout is out of scope for NOVA, which is a tree format. Columnar *export* is an adapter (`nvf convert --to parquet`), not a NOVA feature. |
| **zstd seekable** ✔ ([format](https://github.com/facebook/zstd/blob/dev/contrib/seekable_format/zstd_seekable_compression_format.md)) | Independent zstd frames, with a seek table in a skippable frame (`0x184D2A5E`) at the end | — | Per-frame XXH64 low-32 checksum (optional) | 9-byte footer: `Number_Of_Frames`, descriptor, magic `0x8F92EAB1`. Entries hold compressed and decompressed sizes | Compression stays *outside* NOVA framing. Align zstd frames to NOVA frame or batch boundaries (§5.9). |
| **safetensors** ✔ ([README](https://github.com/huggingface/safetensors/blob/main/README.md)) | `u64 LE` header size + JSON header (`dtype`, `shape`, `data_offsets`) + byte buffer | Header first | Header ≤ 100 MB. No holes or overlaps | Offsets → mmap, lazy per-tensor load | Header-first works when sizes are known in advance. Writers of streams don't know them, so NOVA puts the index at the *end*. |

### 3.2 How databases read JSON

| System | Approach |
| --- | --- |
| **DuckDB** ◐ ([loading JSON](https://duckdb.org/docs/current/data/json/loading_json)) | `read_json(format := 'auto' \| 'newline_delimited' \| 'array' \| 'unstructured')`, plus `read_ndjson` as an alias for NDJSON. `maximum_object_size` defaults to 16,777,216 bytes. `ignore_errors` applies **only** to newline-delimited input. Schema is auto-detected from a sample (○ `sample_size`, default about 20,480 rows). NDJSON is read in parallel by splitting on newlines (○). |
| **SQLite** ◐ ([JSONB](https://sqlite.org/jsonb.html)) | JSON functions work on one value per cell. `json_each` and `json_tree` are table-valued functions (○). Since 3.45.0, **JSONB** is a binary encoding in which every element has a 1–9-byte header carrying type *and payload size*, so subtrees are skippable in O(1). SQLite calls JSONB internal, not an interchange format. There is no built-in NDJSON reader (○). |
| **Lesson** | DuckDB: line-delimited is the format that gets parallelism and error tolerance. SQLite: when a binary format will be queried in place, **container byte sizes pay for themselves**. NOVA adopts both, optionally and outside canonical form. |

### 3.3 Hashing and integrity

| Scheme | Notes |
| --- | --- |
| Certificate Transparency Merkle tree, RFC 6962 §2.1 ○ | `MTH` over leaves, with leaf prefix `0x00` and node prefix `0x01`. Splits at the largest power of two below n. Supports O(log n) inclusion and **consistency (append-only) proofs**. |
| BLAKE3 ○ | Internally a binary Merkle tree over 1 KiB chunks, so hashing parallelizes and verified streaming works. |
| Git trees ○ | A content hash per object, with trees hashing their children's hashes, so unchanged subtrees are reused. |

---

## 4. Streaming model

### 4.1 Decisions in brief

1. Use **one record model**. A NOVA stream *denotes a list* of values (records, usually). Every stream operation is defined as if it acted on that list, so the path language, query responses and patches carry over.
2. Use **three physical forms**:
   - **NOVA Lines** for text record streams. This is new.
   - **`---` text streams** for multi-document bundles. This exists today, with the §2.3 fix.
   - **Binary frame streams** for binary. This exists today, plus META frames.
3. **Append-only.** A stream never rewrites earlier bytes. Edits are separate patch records (§4.7).
4. **Columnar analytics are not in scope.** Interop goes through adapters.

### 4.2 NOVA Lines (`.novl`, proposed media type `application/nova-lines`)

```
@nova 0.2
@schema infrastructure@1.2.0#8c21a0f3d5e6b7c8
@key id
@columns {id, image, port, replicas, enabled}
auth, ghcr.io/example/auth:v2, 8080, 3, true
api,  ghcr.io/example/api:v5,  3000, 5, true
# comments and blank lines are allowed
web,  ghcr.io/example/web:v1,  80, , false      # empty cell = absent field (§4.9)
@end 3 tree:4f1c…
```

The rules:

- **Header.** Zero or more directive lines at column 1, before the first record: `@nova`, `@schema`, `@key`, `@columns`, and `x-…`.
- **Value mode** applies when there is no `@columns`. Each non-blank, non-comment line is **exactly one flow value** (§4.7), written on a single line. Multi-line flow values are not allowed in NOVA Lines. A single-line flow value can hold any NOVA value, because quoted strings forbid raw newlines (§4.6).

  ```
  {id: auth, at: @timestamp("2026-11-17T16:00:00Z"), state: !failed("disk full")}
  {id: api, tags: @set[a, b]}
  ```
- **Table mode** applies after `@columns {c1, …}`. Each line is a **table row** under the §4.9 rules: cells are flow values, an empty cell means an absent field, and the row has exactly as many cells as there are columns. A row denotes a record. A later `@columns` line redefines the columns for the rows that follow. This is allowed so that concatenating streams works (`cat a.novl b.novl`), but writers SHOULD NOT redefine columns otherwise.
- **`@key <field>`** declares that `field` is unique across records. Readers MAY build a hash index on it, and a duplicate is a stream error. It also makes `[id=x]` addressable on streams (§4.7).
- **`@end <count> [<revision>]`** is an optional trailer. It MUST be the last non-blank line. `count` is the number of records. The optional revision is the `tree:` root of the stream (§5.8). A reader that reaches EOF:
  - **with `@end`** checks the count, and the root if present, and reports the stream as *complete* or *corrupt*;
  - **without `@end`** reports the stream as *open*. Open is a status, not an error: `tail -f` works and producers can crash. `--strict` turns *open* into an error.
- **Errors.** A malformed line is reported with its line number and skipped in recovering mode (the default for `nvf get`; `--strict` stops). Because a record is always exactly one line, recovery is trivial and exact.
- **Concatenation.** Header directives MAY reappear later in the stream. `@nova` or `@schema` after records start a new *segment*. An `@end` inside a concatenation closes only its own segment.

**Why not `[?]{cols}:` inside ordinary documents?** The `[N]` count is NOVA's guard against truncated LLM output (§4.9). An escape hatch there would be used exactly when the guard matters. Streams are a different object: they are expected to be open, and they get their own trailer. Converting is lossless. `nvf convert --to nova x.novl` yields `[N]{…}:` with the count filled in, and `nvf convert --to novl doc.nova --path items` goes the other way.

**Why not reuse `---` for records?** `---` documents are block-structured, cost a separator line each, and cannot be parsed from an arbitrary byte offset without scanning back to a separator. NOVA Lines records can be: from any byte offset, skip to the next `\n`. The one piece of context needed is the latest `@columns` line, which a splitter finds by scanning backwards for a line starting with `@columns`, or reads from an index.

### 4.3 Binary streams: META frames

The frame layout (§5.4) stays as it is. Two flags are added:

| Flag | Name | Meaning |
| --- | --- | --- |
| `0x10` | META | The payload is a **stream-control value**, a variant (below), not a data record. Data readers skip it unless they understand it. |
| `0x20` | SHARED_DICT | A `dict_id: varint` follows the schema field (or the flags byte, if there is no schema). The frame's string table starts pre-seeded with dictionary `dict_id` (§4.5). |

META payloads are ordinary NOVA values, so a single decoder handles both data and control:

| Variant | Payload | Where |
| --- | --- | --- |
| `!header{nova, schema?, key?, columns?, created?, x-…?}` | Stream metadata, like NOVA Lines directives | First frame. MAY repeat after a segment boundary. |
| `!dict{id, strings: [..]}` | An immutable string dictionary | Before the first frame that references it. Writers SHOULD re-emit it periodically (for example every 64 MiB) so that recovering readers find it quickly. |
| `!index{…}` | Offset tables (§5.3) | Near the end. |
| `!end{count, root?}` | The same as NOVA Lines `@end` | Last data-bearing frame. |
| `!locator(@bytes(8 bytes, u64 BE offset of the !index frame))` | A fixed-size pointer | **Final frame, exactly 26 bytes** (below). |

The locator frame has a fixed byte layout, so a reader can find the index with one read from the end of the file:

```
4E 4F 56 41  01  10  13        "NOVA", version 1, flags=META, length=19
10 0E "locator"                variant-with-payload tag, str literal len 7
07 08 <u64 BE offset>          bytes(8)
```

That is 4 + 1 + 1 + 1 + 19 = **26 bytes**. A file with an index is *still* a plain concatenation of frames. Old-style readers that understand META simply see more frames, and §5.5 recovery is unchanged. (Readers implementing only spec 0.1 reject flag `0x10` as an unknown flag. That is the intended behavior for a pre-1.0 format.)

**Batching.** One frame per record wastes about 7–12 bytes of framing per record. It also defeats the string table, because keys are re-sent in every frame. Writers SHOULD put **a list of records** in each data frame, 64–4096 records or about 64 KiB–1 MiB. The stream then denotes the *concatenation* of those lists. The `!header` field `batched: true` declares this, so the payload `[r1, r2, …]` is not mistaken for one list-valued record. Record addressing is `(frame, index-in-frame)`, and the index flattens it.

### 4.4 Records, revisions and stream identity

| Identity | Definition | Cost | Use |
| --- | --- | --- | --- |
| Record revision | `sha256:` of the record's canonical encoding (§2.13) | O(record) | Conditional edits to one record (`@expect`, §4.7) |
| Stream value revision | `sha256:` of the stream *as a list value* | Needs `n` before the first element (`0x0A varint(n) …`), so it is a two-pass computation over a file and **impossible for a live stream** | Equality with a materialized document |
| **Stream root** | `tree:` Merkle root over record leaf hashes (§5.8) | One pass, O(log n) state, parallel | `@end`, the index, sidecar patches, replication and consistency proofs |

The recommendation: streams are identified by their **`tree:` root**. `sha256:` remains available via `nvf hash --exact`, which takes two passes.

### 4.5 String tables: per frame by default, shared dictionaries opt-in

| Option | Size | Resync | Random access | Complexity |
| --- | --- | --- | --- | --- |
| Per frame, as today | Keys are re-sent once per frame, which is small once frames are batched | ✔ | ✔ | none |
| Stream-scoped table that grows across frames | Smallest | ✘: a lost frame corrupts every later back-reference | ✘: reading frame k requires decoding all earlier frames | low |
| **Immutable dictionaries by id (SHARED_DICT)**, as in Arrow dictionary batches but without deltas | Small: `@columns` names, enum tags and hot values are 1–2 bytes | ✔: a frame names its `dict_id`, and a reader finds the dict by scanning back or via the index | ✔ | moderate |

The recommendation is the third option. Semantics: with SHARED_DICT, the frame's string table **starts** as `dict.strings`, and in-frame literals append after it, exactly as in §5.3. Canonical frames MUST NOT set SHARED_DICT, because canonical form has no back-references. Arrow-style delta dictionaries are deliberately left out: a delta makes a dictionary's content depend on stream history, which brings back the resync problem. Writers that need a new dictionary emit a new `!dict` with a new id.

### 4.6 Error recovery summary

| Layer | Detection | Recovery |
| --- | --- | --- |
| NOVA Lines record | Line fails to parse | Skip the line, report it, continue |
| NOVA Lines stream | `@end` count or root mismatch, or no `@end` | Status *corrupt* or *open* |
| Binary frame | Bad magic, version, flags or length; CRC mismatch (`0x04`) | Resync on the next `NOVA` (§5.5) |
| Binary dictionary | `dict_id` unknown at decode time | Look it up in the index, or scan back for `!dict`. Otherwise report the frame as *undecodable* and continue |
| Binary stream | `!end` mismatch, or no `!end` | Status *corrupt* or *open* |
| Index | Locator missing or bad, or index CRC fails | Ignore the index and fall back to a sequential scan. Never trust an index over the data: `nova verify` rebuilds and compares |

### 4.7 Patches and streams

Streams are append-only, so the operations map as follows:

| Intent | Stream form |
| --- | --- |
| Insert a record | Append a record (line or frame) |
| Edit or delete a record | Append a **patch document** to a sidecar `FILE.patches`. This is a `---`-separated text stream of `@patch` documents. A future option is in-band patch frames, `!patch{…}` META frames |
| Compact | `nvf compact FILE` rewrites the stream with all patches applied, writes a fresh `@end` and index, and archives or truncates the sidecar |

Stream paths treat the stream as a list: `[123]` is an ordinal, and `[id=auth]` is a keyed lookup, efficient when `@key id` is declared and indexed. A sidecar patch looks like this:

```
@patch infrastructure@1.2.0
@scope [id=api]
@expect sha256:5be1a2…            # revision of the record at @scope (new directive, §8.3)
replicas: 5 -> 8
---
@patch
@scope [id=web]
@expect sha256:0c7d…
- .                                # remove the scoped record
```

`@expect` is the key addition. A `@base` is a revision of the **whole** document, so checking it on a 5 GB stream means hashing 5 GB (or keeping an up-to-date `tree:` root). `@expect` checks only the scoped value. It brings compare-and-swap to the granularity where concurrent edits actually happen. `@base tree:<root>` remains available for "nothing anywhere changed" semantics.

Note that `- .` (remove the scope root) is not valid today: §7.5 has no way to remove the scoped value itself. The proposal allows `- .` when the scope's parent is a list or a stream.

---

## 5. Massive files

### 5.1 Strategy overview

| Need | Mechanism | Text | Binary |
| --- | --- | --- | --- |
| Bounded memory | Pull events (§5.4) | ✔ | ✔ |
| Find record k | Index (§5.3) | `.novl`: line-offset index (built on demand, cacheable) | `!index` frame |
| Skip a subtree | Lengths | Indentation scan (§5.6) | `0x13 sized` (§5.2), or a fallback structural skip |
| Zero-copy | Borrowed views | `&str` slices, `Cow` for escapes | `&[u8]` / `&str` from mmap, string table as spans |
| Parallelism | Splittable boundaries | Newlines (`.novl`), column-0 or indent-k lines (§2.3 invariant) | Frame boundaries, plus the index |
| Hash huge data | `tree:` revisions (§5.8) | ✔ | ✔ |
| Compression | Outer zstd seekable (§5.9) | ✔ | ✔ |

### 5.2 Should containers carry byte lengths?

The current encoding stores `varint(n)` element counts only. Skipping a container means walking it, and walking must still *track string-table appends*, because later back-references can point at strings inside the skipped subtree. So "skip" is really "parse without allocating". That costs roughly 1–3 GB/s on modern CPUs (an estimate; measure it), versus O(1) with a length.

| Option | Overhead | Skip | Writer cost | Back-reference interplay |
| --- | --- | --- | --- | --- |
| A. Status quo | 0 | O(subtree) structural walk | none | Must collect literal *spans* while skipping (cheap: record `(offset, len)` only) |
| B. Byte length on every container (new tags) | +1–4 bytes per container. For the 500k-record dataset (about 1.5 M containers) that is about +1.5–3 MB on 25 MB (6–12%) | O(1) | Must know the size before writing: buffer bottom-up or backpatch with fixed-width varints | Broken: skipping loses table entries unless entries are scoped |
| **C. Optional wrapper `0x13 sized`, only on large containers, with a scoped string table** | Negligible (threshold 4 KiB → less than 0.1%) | O(1) where present, O(subtree) elsewhere | Encode the child into a scratch buffer, then write the length. This only happens for large children | **Literals appended inside a `sized` value are popped at its end**, so a skip leaves the table exactly as it was. Back-references inside may refer to outer entries |

**Recommendation: C.**

```
0x13  sized    varint(byte_len)  value        ; value MUST be a container (list, tuple, set, record, map, variant-with-payload)
```

- It is transparent in the value model: it denotes the wrapped value.
- It MUST NOT appear in canonical encoding (§5.2). Revisions and equality are unchanged.
- Scoped string table: on entry, the decoder notes `t = table.len()`. On exit it truncates the table to `t`. Encoders do the same, so they never back-reference into a closed scope.
- `byte_len` MUST equal the encoded length of the wrapped value. A mismatch is a decode error.
- A writer option `sized_threshold` (default 4096 bytes; 0 disables) controls which containers are wrapped. An index (§5.3) can point at `sized` values to provide random access *inside* one huge document.

This is the SQLite JSONB lesson (sizes in headers enable in-place querying) and the Avro blocked-array lesson (optional byte size), applied only where it pays off.

### 5.3 Index frame (footer)

The `!index` META frame payload:

```
!index{
  version: 1,
  data_end: 123456789,                 # offset after the last data frame
  frames: @bytes(...),                 # u64 LE × F: offset of each data frame
  records: @bytes(...),                # u64 LE × (F+1): cumulative record count before each frame → binary search for ordinal k
  dicts: @map{0 => 4096, 1 => 77841},  # dict_id → frame offset
  keys?: {field: id, kind: !sorted, table: @bytes(...)},  # optional: sorted (hash64(key), ordinal) pairs for @key lookups
  subtrees?: [ {path: "items", offset: …, len: …, elem_offsets: @bytes(...)} ],  # sized subtrees inside huge single documents
  root?: tree:…,                       # stream root at index time
  crc32?: …
}
```

- Offsets are fixed-width `u64` LE in `bytes` blobs, not NOVA lists, so they can be read in place from mmap in O(1) without decoding the index (the Arrow footer `Block` pattern). One million frames make an 8 MB blob.
- **Incremental updates (append-only):** to append, write new frames, then a new `!index` and a new locator. The old index becomes garbage. This is the PDF incremental-update pattern (○), and it never rewrites earlier bytes.
- For text: `.novl.idx` sidecar files hold the same structure (line offsets every K records). They are rebuildable and keyed by file size, mtime and a sampled hash.

### 5.4 Pull-event API (text and binary)

```rust
/// A borrowed, allocation-free event stream over one value or a stream of values.
pub enum Event<'a> {
    Null, Bool(bool), Int(i128), Float(f64),
    Decimal(Decimal), Rational(Rational), Timestamp(Timestamp), Duration(Duration),
    Str(Str<'a>), Bytes(Bytes<'a>),                    // borrowed when possible
    StartList  { len: Option<u64> },                   // binary and `[N]` tables know len; block lists do not
    StartTuple { len: Option<u64> },
    StartSet   { len: Option<u64> },
    StartRecord{ len: Option<u64> },
    StartMap   { len: Option<u64> },
    Key(Str<'a>),                                      // record keys (map keys are values between StartMap/End)
    Variant(Str<'a>, /*has_payload*/ bool),
    End,
    Record,                                            // top-level record boundary in a stream (NOVA Lines line / frame item)
}

/// Text needs Cow for escapes; binary strings are always borrowed (literal or back-ref span into the mmap).
pub enum Str<'a> { Borrowed(&'a str), Owned(Box<str>) }

pub trait EventSource<'a> {
    fn next(&mut self) -> Result<Option<Event<'a>>, ReadError>;
    /// Skip the value whose Start* event was just returned (or the next scalar).
    /// O(1) for binary `sized`, else a structural walk; for text, an indentation scan when possible.
    fn skip_value(&mut self) -> Result<(), ReadError>;
    /// Byte offset of the next event in the source (for indexes, spans, error messages).
    fn offset(&self) -> u64;
    fn depth(&self) -> usize;
}

pub struct BinaryEvents<'a> { /* buf: &'a [u8], pos, stack, table: Vec<(u32 /*off*/, u32 /*len*/)>, scopes: Vec<usize> */ }
pub struct TextEvents<'a>   { /* src: &'a str, line-oriented cursor, indent stack */ }
pub struct LinesEvents<'a>  { /* NOVA Lines: one record per line, columns */ }

/// Lazily decoded view over memory-mapped binary; navigates by skipping.
#[derive(Clone, Copy)]
pub enum ValueRef<'a> {
    Scalar(ScalarRef<'a>),
    List(SeqRef<'a>), Tuple(SeqRef<'a>), Set(SeqRef<'a>),
    Record(RecordRef<'a>), Map(MapRef<'a>),
    Variant(&'a str, Option<LazyRef<'a>>),
}
impl<'a> RecordRef<'a> {
    pub fn get(&self, key: &str) -> Result<Option<ValueRef<'a>>, ReadError>; // linear scan with skip_value
    pub fn iter(&self) -> impl Iterator<Item = Result<(&'a str, ValueRef<'a>), ReadError>>;
}
impl<'a> SeqRef<'a> {
    pub fn len(&self) -> u64;
    pub fn nth(&self, i: u64) -> Result<ValueRef<'a>, ReadError>;  // O(i) skips, O(1) with an element-offset index
}
impl ValueRef<'_> { pub fn to_owned(&self) -> Result<Value, ReadError>; }
```

**Zero-copy back-references.** The decoder's string table stores `(offset, len)` into the source buffer rather than owned `String`s. Both literals and back-references then resolve to `&'a str` with no allocation. UTF-8 is validated once, at the literal.

**Builders.** `Value::from_events(src)` becomes the one materializer, and the existing `decode` and `parse` become thin wrappers. The `novafile-serde` deserializer can be driven by events directly, avoiding the intermediate `Value` (the serde-json `from_reader` pattern).

**Text duplicate keys in streaming mode.** A pull parser cannot reject duplicates before emitting the second key unless it keeps the key set per open record. It does keep that set: keys only, not values, so the memory is proportional to the widest record.

### 5.5 Streaming path evaluation

| Segment | Streamable? | Notes |
| --- | --- | --- |
| `.name` on a record | ✔ | Emit when found. Keep scanning, or rely on decoder duplicate checks, to report *duplicate key* |
| `[n]`, n ≥ 0 | ✔ | Skip n elements |
| `[-n]` | Binary: ✔ (count known). Text `[N]` table: ✔. Text block list or NOVA Lines: needs a ring buffer of n elements, or a 2-pass/index | Ring buffer of size n is acceptable for small n |
| `[field=v]`, `[v]` on a list | ⚠ | *Ambiguity* requires scanning to the end. Buffer the first match and emit at the end (O(1 match) memory). `--first` mode emits immediately. With `@key field`, uniqueness is guaranteed and emission is immediate |
| `[v]` on a set or map | ⚠ | Same as above, and also order-free |
| `[*]` | ✔ | Per element |
| `[?p op v]` | ✔ | Evaluate `p` per element. If `p`'s field may come after other fields, buffer one element (memory O(max element)). For binary `sized` elements, first scan keys only |
| `.{a,b}` | ✔ | Per element |
| `@revision` header of the response | ✘ in one pass | Streaming responses use NOVA Lines with `@end n tree:…`. `--revision` forces a second pass or uses the index's `root` |

API:

```rust
pub fn select_stream<'a, S: EventSource<'a>>(src: S, path: &Path, opts: SelectOpts)
    -> impl Iterator<Item = Result<Value, PathError>> + 'a;
```

CLI: `nvf get --stream FILE PATH` produces NOVA Lines output, or `-r` raw strings. For `.novl` and binary streams it is selected automatically.

### 5.6 Incremental parsing of indentation-based text

NOVA's fixed two-space grammar is an asset here. Under the §2.3 invariant:

- The **children of a line at indent k** are exactly the following lines with indent > k, up to the first non-blank line with indent ≤ k. Block strings and multi-line flow values are always deeper.
- A **structural outline** (the keys and list items at depth ≤ d) can therefore be built by a memchr-driven line scan, reading the first non-space byte and key of each line, **without parsing values**. Expected speed is on the order of `wc -l` plus a little (0.04 s for 82 MB above), so about 1–2 GB/s. The TUI uses this to open a multi-GB text file in about a second.
- `[N]{…}:` tables have **one row per line at indent k+2**, unless a cell holds a multi-line flow value, which the invariant keeps indented deeper. Row k is a line lookup.

Caveat: comments and blank lines at any indentation are skipped by the scanner, and `#` inside a quoted key needs only light lexing of the key itself.

### 5.7 Chunked and parallel processing

| Input | Split points | Context needed per chunk | Merge |
| --- | --- | --- | --- |
| NOVA Lines | Any `\n` | Latest `@columns`, `@key`, `@schema` | Concatenate; check `@end` count |
| Text, a huge top-level list or table | Lines at the child indent (§5.6) | Base indent, table columns | Concatenate; check `[N]`; renumber errors |
| Text, a huge top-level record | Column-0 key lines | — | Union, with a cross-chunk duplicate-key check (hash set of keys) |
| Binary stream | Frame boundaries (index or magic scan) | Dicts by id | Concatenate |
| Binary single huge value | `sized` subtrees and `elem_offsets` in the index | Outer string-table prefix (table entries before the subtree, recorded in the index as a dict-like snapshot or recomputed) | Concatenate |

The last row is the reason the `sized` scoping rule matters: the outer string-table *prefix* is fixed when a subtree starts, so a worker needs that prefix and nothing else.

### 5.8 Hashing huge documents: `tree:` revisions

**Why `sha256:` cannot always be streamed.** The canonical encoding (§5.2) requires:

- record fields **sorted by key bytes**, so all fields of a record must be seen before any is hashed;
- set elements and map entries **sorted by their own canonical encoding**, so all encodings must be buffered and sorted (external sort for huge sets);
- a `varint(n)` count *before* list elements, which a block list or open stream does not provide up front.

A single forward pass works only when every record is small, there are no huge sets or maps, and list counts are known: binary input or `[N]` tables. Over an mmapped *file* it is always possible in O(n log n) time with an O(index) memory two-pass method, since fields can be visited in sorted order by offset. For a live stream it is impossible.

**Proposal: an additional `tree:` revision** (NOVA Tree Hash, version 1), defined with SHA-256:

```
leaf(v)          = H(0x00 ‖ canonical(v))                         for scalars and for any value whose canonical size ≤ 1 KiB (inline small subtrees; cuts hashing overhead)
list/tuple(xs)   = H(0x01 ‖ tag ‖ MTH(hash(x₁)…hash(xₙ)))         MTH = RFC 6962 Merkle tree hash over child hashes (empty → H(""))
record(fs)       = H(0x01 ‖ 0x0D ‖ varint(n) ‖ concat over fields sorted by key bytes of (H(0x02 ‖ key) ‖ hash(value)))
set(xs)          = H(0x01 ‖ 0x0C ‖ varint(n) ‖ concat of hash(x) sorted bytewise)
map(es)          = H(0x01 ‖ 0x0E ‖ varint(n) ‖ concat over entries sorted by hash(key) of (hash(key) ‖ hash(value)))
variant(t, p)    = H(0x01 ‖ 0x10 ‖ str(t) ‖ hash(p))
written          tree:<64 hex>
```

Properties:

- **Equality-compatible.** Equal values (§2.12) give equal `tree:` hashes. Sets and maps are order-free because sorting is over child hashes, and records sort by key bytes.
- **One pass, bounded memory.** Memory is O(depth × widest record × 32 B). Sets, maps and wide records need 32 bytes per child, not the encoded child. Long lists need O(log n) state (the RFC 6962 "frontier").
- **Append-friendly.** The `tree:` root of a stream is the list hash of its records. Appending updates it in O(log n). RFC 6962 consistency proofs show that a new root extends an old one, which is what replication and audit need.
- **Parallel.** Chunks hash independently and combine.
- **Subtree revisions for free.** The TUI and patch engine cache hashes per node. An edit recomputes O(depth × log fanout) hashes, which makes `@expect` checks cheap.
- **Not a replacement.** `sha256:` stays *the* revision of §2.13, for compatibility, simplicity and agents. Revision preconditions accept either form (`@base tree:…`). A document's `tree:` and `sha256:` are different strings, and tools must not compare across forms.

The 1 KiB small-subtree inline rule keeps the number of hash invocations near (bytes / 1 KiB) instead of one per scalar. Without it, a hash per scalar would be about 10–20× slower than plain SHA-256 throughput. To be validated by benchmark (§5.10).

### 5.9 Compression

- **Outside NOVA framing.** Use `.nvb.zst` / `.novl.zst` in the **zstd seekable format**, with each zstd frame containing whole NOVA frames or whole lines (recommended 256 KiB–4 MiB uncompressed). NOVA index offsets are *uncompressed* offsets, and the seek table maps them to compressed ones.
- **Not in v0.2:** a per-frame compression flag. If added later: flag `0x40 COMPRESSED` plus a codec byte (zstd, lz4), with the CRC computed over the *uncompressed* payload.
- Expect a 3–6× ratio on the text forms and 2–3× on binary for record-heavy data (○ typical; measure it).

### 5.10 Performance expectations and what to measure

Targets for the reference implementation on one modern x86-64 core after the §2.2 fixes. These are estimates, to be confirmed:

| Operation | Today (measured, §2.1) | Target |
| --- | --- | --- |
| Text → owned `Value` | ~16 MB/s with fixes (74 MB in 4.7 s, including hash) | 150–300 MB/s |
| Text pull events (no allocation for unescaped strings) | — | 400–800 MB/s |
| Text structural outline (§5.6) | — | ≥ 1.5 GB/s (memchr-bound) |
| Binary → owned `Value` | ~11 MB/s of binary (25 MB in 2.3 s, including hash) | 300–600 MB/s |
| Binary pull events / `ValueRef` navigation | — | 1–2 GB/s; O(1) skips with `sized` |
| `sha256:` over canonical bytes | Dominated by encoding | SHA-256 bound: ~1 GB/s with SHA-NI (sha256sum measured 82 MB in 0.08 s here) |
| `tree:` hash | — | ≥ 0.7 × the SHA-256 rate per core, scaling with cores |
| `nvf get --stream '[?replicas>7].id'` on 5 GB `.novl` | Impossible (OOM) | ≤ 15 s single-threaded, ≤ 4 s on 8 cores; RSS < 64 MB |
| Peak RSS, owned `Value` | 29× text size, 37× binary size | ≤ 6× text size (compact `Value`: interned keys, `Box<str>`, small-int variant) |
| TUI open of a 5 GB text file | — | First screen in ≤ 1 s (outline of the first screen only), full outline in the background |

What to measure (add `benches/` with criterion and a `nova bench` dataset generator):

1. Throughput (MB/s) and allocations (count and bytes, via `dhat` or a counting allocator) for parse, decode, encode, canonical encode, `sha256:`, `tree:`. Shapes: wide records (10⁵ keys), long lists (10⁷), deep nesting (128), uniform tables, string-heavy and number-heavy data, large sets.
2. **Scaling exponent**: time at n, 2n, 4n for every shape. Make it a CI check, with fail at a ratio above 2.3×, so quadratic regressions like §2.2 cannot come back.
3. Peak RSS relative to input size.
4. Time to first record and time to the k-th record (streaming latency).
5. Skip cost with and without `sized`, and size overhead per threshold (0, 256, 4K, 64K).
6. Parallel speedup at 1, 2, 4 and 8 threads for `.novl` and binary streams.
7. Compression ratio and speed (zstd levels 1, 3, 9) for each representation.
8. TUI: frame render time (target < 4 ms), keypress-to-paint latency, index build time, memory at 1 GB and 5 GB.

---

## 6. Rust API sketches (stream I/O)

```rust
// crate nova-stream
pub enum StreamFormat { Lines, TextDocs, Binary }

pub struct StreamHeader {
    pub nova: Option<String>, pub schema: Option<SchemaRef>,
    pub key: Option<String>, pub columns: Option<Vec<String>>,
}

pub enum StreamStatus { Complete { count: u64, root: Option<TreeRev> }, Open { count: u64 }, Corrupt(String) }

pub struct StreamReader<R> { /* BufRead or mmap; format; header; recover: bool; counters */ }
impl<R: std::io::BufRead> StreamReader<R> {
    pub fn open(r: R) -> Result<Self, StreamError>;                 // sniff: "NOVA" magic → Binary, else Lines vs TextDocs by header/first line
    pub fn header(&self) -> &StreamHeader;
    pub fn recovering(self, on: bool) -> Self;
    pub fn records(&mut self) -> impl Iterator<Item = Result<Value, RecordError>> + '_;  // owned, simple
    pub fn events(&mut self) -> &mut dyn for<'a> EventSourceDyn<'a>;                    // borrowed, fast
    pub fn finish(self) -> StreamStatus;                             // checks @end / !end
}

pub struct StreamWriter<W> { /* format, header, batch size, dict, tree hasher, count */ }
impl<W: std::io::Write> StreamWriter<W> {
    pub fn new(w: W, format: StreamFormat, header: StreamHeader, opts: WriteOpts) -> Result<Self, std::io::Error>;
    pub fn write(&mut self, v: &Value) -> Result<(), WriteError>;   // validates against @columns / @key
    pub fn flush_batch(&mut self) -> Result<(), std::io::Error>;    // binary: emit one data frame
    pub fn finish(self, with_index: bool) -> Result<StreamSummary, std::io::Error>; // writes @end / !end (+ !index + !locator)
}

pub struct Index<'a> { /* borrowed from mmap */ }
impl<'a> Index<'a> {
    pub fn locate(file: &'a [u8]) -> Result<Option<Self>, IndexError>;  // reads the 26-byte locator
    pub fn record_count(&self) -> u64;
    pub fn record(&self, ordinal: u64) -> (u64 /*frame offset*/, u32 /*index in frame*/);
    pub fn by_key(&self, key: &Value) -> Option<u64>;
}

// crate novafile-value additions
pub struct TreeHasher { /* frontier stack for lists, per-depth sort buffers of 32-byte child hashes */ }
impl TreeHasher {
    pub fn feed(&mut self, e: &Event<'_>);
    pub fn finish(self) -> TreeRev;
}
pub fn tree_revision(v: &Value) -> TreeRev;
```

---

## 7. A TUI browser and editor

### 7.1 Prior art

| Tool | What to borrow | What to avoid | Source |
| --- | --- | --- | --- |
| **jless** | Vim movement (`j k h l`, `J K` siblings, `H` parent, `g G`, `%`, `zt zz zb`); `Space` to toggle, `c`/`C` collapse, `e`/`E` expand; `/ ? n N`, `*`/`#` search for focused key; **yank family** `yy yv ys yk yp yb yq` (pretty value, one-line value, string, key, dot path, bracket path, query path); **data vs line mode** (`m`); `:w file` | No editing; whole-file load | ✔ [app.rs](https://github.com/PaulJuliusMartinez/jless/blob/main/src/app.rs), [README](https://github.com/PaulJuliusMartinez/jless) |
| **fx** | Interactive viewer plus a JS or JSON expression language; yank via **OSC 52** with a local clipboard fallback (works over SSH); `?` shows keys | Its non-path language | ◐ [release notes](https://newreleases.io/project/github/antonmedv/fx/release/40.0.0) |
| **jnv** | Split screen: a **filter editor with live results** above a foldable viewer; tab-completion of keys and indices; debounce; JSON Lines input; implemented with **jaq** (no jq dependency) | — | ✔ [README](https://github.com/ynqa/jnv) |
| **VisiData** | Sheets, a column-oriented **table view**, frequency tables, sheet stack (drill down, `q` back) | Its keymap density | ✔/○ [README](https://github.com/saulpw/visidata) |
| **gron** | Flatten to greppable `path = value;` lines, and `--ungron` back | — | ✔ [README](https://github.com/tomnomnom/gron) |
| **lnav** | A **combined index populated as data is read**, with the UI showing a window of the index; an SQL prompt (`;`) over virtual tables; live tailing | — | ◐ [docs](https://docs.lnav.org/en/stable/ui.html) |
| **yazi** | Async I/O, never blocking the render loop; previews in background tasks | — | ○ |
| **Helix and vim** | `:` command line, `/` search, `n`/`N`, counts, `u` / `Ctrl-r` undo and redo, `y`/`p`, `gg`/`G`; Helix space-menu discoverability | Modal complexity beyond what's needed | ○ |
| **ratatui ecosystem** | `ratatui` (immediate-mode widgets: `Table`, `List`, `Paragraph`, `Scrollbar`); `crossterm` backend; `tui-textarea` (multi-line editor widget); `tui-tree-widget` (tree widget built for mqttui) | Off-the-shelf tree widgets require materialized items, so NOVA needs its own **virtualized** tree | ✔ [tui-tree-widget](https://github.com/EdJoPaTo/tui-rs-tree-widget); ○ API details of the others |

### 7.2 Screen layout

```
┌ nova-tui ─ infra.nova ─ text · 2.1 MB · schema infrastructure@1.2.0 ✓ · sha256:91cf16db ─ READ-ONLY ┐
│ . › services › [id=api] › replicas                                                   (breadcrumbs) │
├──────────────────────────────────────────────────────────────┬─────────────────────────────────────┤
│ ▾ services                         list[3] of record         │ path   services[id=api].replicas    │
│   ▸ [0] id=auth                    {id, image, port, …}      │ kind   int                          │
│   ▾ [1] id=api                                               │ value  5                            │
│       id         api                                         │ schema replicas: int @range(1..50)  │
│       image      ghcr.io/example/api:v5                      │        @default(1)                  │
│     ▶ replicas   5                                    ◆1     │ rev    sha256:5be1a2… (subtree)     │
│       port       3000                                        │ ─────────────────────────────────── │
│       enabled    true                                        │ pending patch (1 op)                │
│   ▸ [2] id=web                     {id, image, port, …}      │   services[id=api].replicas:        │
│ ▸ volumes                          map{4}                    │     5 -> 8                          │
│   limits                           {cpu: 2, mem: "4Gi"}      │ ⚠ web.port: 80 < @range(1024..)     │
├──────────────────────────────────────────────────────────────┴─────────────────────────────────────┤
│ :services[?replicas>3].{id,replicas}                                      2 matches  ⏎ jump · Tab  │
└ j/k move  h/l fold  / search  : path  t table  y yank  e edit  u undo  w save  ? help ─────────────┘
```

The table view (`t` on a list of uniform records) uses NOVA's compact-table notion: the columns are the union of the keys, ordered by first appearance, and empty cells mean the field is absent.

```
┌ services · table · 3 rows · 5 cols ───────────────────────────────────── sort: replicas ▼ ───────┐
│ #  id     image                       port   replicas  enabled                                    │
│ 1  api    ghcr.io/example/api:v5      3000   5         true                                       │
│ 2  auth   ghcr.io/example/auth:v2     8080   3         true                                       │
│ 3  web    ghcr.io/example/web:v1      80     ·         false          · = absent                  │
└ ⏎ open row  F freq  s sort  [ ] resize  c hide col  q back ───────────────────────────────────────┘
```

### 7.3 Keybindings

| Keys | Action | Notes |
| --- | --- | --- |
| `j`/`↓`, `k`/`↑` | Next or previous visible node | Counts: `5j` |
| `l`/`→` | Expand, or go to the first child if already expanded | |
| `h`/`←` | Collapse, or go to the parent if already collapsed | |
| `J`/`K`, `H` | Next/previous sibling; parent | jless |
| `gg`/`G`, `Ctrl-d`/`Ctrl-u`, `Ctrl-f`/`Ctrl-b` | Top/bottom; half page; page | |
| `zt` `zz` `zb` | Scroll the focused node to top, center, bottom | |
| `Space` | Toggle fold | |
| `c`/`C`, `e`/`E` | Collapse siblings or deep; expand siblings or deep | Deep expand is capped at N nodes on big files |
| `1`–`9` then `z` | Fold to depth N | |
| `/`, `?`, `n`/`N` | Incremental search forward or backward (keys, values, regex with `\v`) | Background on big files |
| `Ctrl-f` | Search scope picker: keys / values / both, current subtree / whole | Only when not in Vim-page mode |
| `*`/`#` | Search for the focused key | jless |
| `:` | **Path bar**: a NOVA path (§7.1). Singular → jump. With `[*]`, filters or a projection → results list, `Tab` cycles, `Enter` jumps | Live preview, debounced (jnv) |
| `.` | Path bar pre-filled with the current path | |
| `F` | Filter the current list by a predicate (`?replicas>3`) as a view filter | Non-destructive |
| `t` | Toggle table view for a list of records | |
| `s`, `S` | Sort the table by column ascending/descending (view only) | |
| `Enter` | Open: drill into a table row or a long string (pager) | |
| `q`/`Esc` | Back (pop the view stack) or quit | |
| `yy`, `yv`, `yk`, `yp`, `yq` | Yank value as NOVA block, value as one-line flow, key, path, `nvf get` command | OSC 52, with a local clipboard fallback |
| `yj`, `yJ` | Yank as JSON (compact or pretty), with loss warnings (§11.1) | |
| `m` | Toggle tree mode / source (line) mode | jless |
| `i` | Toggle the inspector pane | |
| `e` (`--edit`) | Edit the focused scalar inline (tui-textarea); `Enter` stages `old -> new` | |
| `a`, `o` (`--edit`) | Add a field or list item after the focused one (stages `+`) | |
| `dd` (`--edit`) | Stage a remove (`- path: old`) | |
| `r` (`--edit`) | Rename a key (stages a remove plus an add, shown as one logical edit) | |
| `u`, `Ctrl-r` | Undo / redo (inverse patches) | |
| `p` | Show the pending patch (as a NOVA patch document) | |
| `w` / `:w`, `:w FILE`, `:wp FILE` | Apply and save; save as; write the pending patch only | |
| `:q`, `:q!` | Quit; quit and discard staged edits | |
| `R` | Reload from disk (rebases staged edits via `@expect`) | |
| `?`/`F1` | Help overlay | |

### 7.4 Architecture

```
crates/
  nova-doc     — document model for tools (no UI deps):
                 Source (mmap'd or in-memory text/binary/novl), NodeId, lazy Outline index,
                 Cursor, materialize(NodeId) -> Value, subtree revisions (tree:), SpanMap bridge,
                 EditSession (staged patch, apply, inverse, span-splice save)
  nova-stream  — §6 (also used by novafile-cli)
  nova-tui     — ratatui + crossterm app (bin `nova-tui`, lib for embedding); novafile-cli gets
                 `nvf tui` behind a default-on cargo feature `tui` (so minimal builds stay small)
```

Model, view, update (the Elm architecture, which ratatui's documentation recommends ○):

```rust
struct Model {
    doc: nova_doc::Doc,                 // lazy; owns Source + Outline + caches
    view: ViewStack,                    // Tree | Table{path, sort, cols} | Pager | Results{query}
    tree: TreeState,                    // expanded: HashSet<NodeId>, focus: NodeId, scroll anchor
    prompt: Option<Prompt>,             // Search | Path | Command, with history
    edit: Option<nova_doc::EditSession>,// None unless --edit
    jobs: JobQueue,                     // background: outline build, search, hash, validation
    status: Status,
}
enum Msg { Key(KeyEvent), Resize(u16,u16), Tick, JobDone(JobResult), FileChanged }
fn update(m: &mut Model, msg: Msg) -> Vec<Cmd>;   // pure-ish; Cmd = spawn job / write file / clipboard
fn view(m: &Model, f: &mut Frame);                // renders only visible rows
```

- **Virtualized rows.** The tree is never flattened. `TreeState` keeps the focused `NodeId` and a scroll anchor. `view` walks forward from the anchor until the screen fills, asking `Doc` for children lazily. A 10⁷-element list shows `[0]…[49]`, and `G` jumps to `[9999999]` via the index.
- **Background jobs.** Run on a thread pool with channels. Rendering never blocks: unfinished regions show `…indexing 37%`.
- **`NodeId`.** `(source offset, depth)` for lazy sources. For owned `Value`s, a path. Stable across edits through re-resolution.

### 7.5 Big-file behavior

| File size | Strategy |
| --- | --- |
| < 64 MiB (configurable) | Load fully: owned `Value` plus `SpanMap`. All features |
| ≥ 64 MiB, text | Structural outline (§5.6) built lazily per expanded node. Values are parsed when visible. Search streams in the background. Table view parses the visible rows only |
| ≥ 64 MiB, binary | mmap plus `ValueRef`. Uses the `!index` and `sized` wrappers when present, otherwise a background outline pass that records `elem_offsets` per expanded list |
| `.novl` / binary streams | Shown as a top-level list. The line or frame index is built in the background. `F` follows a growing file (tail mode, lnav) |
| stdin | Spooled to a temp file, then treated as a file |

### 7.6 Editing through the patch engine

The recommendation is yes: **every edit is a conditional patch op.** Concretely:

1. **Staging.** `e` on `replicas` with value 5, entering `8`, stages `services[id=api].replicas: 5 -> 8`. Paths prefer stable selectors: `[id=…]` when the list has a unique `id`, `key` or `name` (the §7.6 diff heuristic), otherwise an index. Staged ops form one pending `Patch` with `@expect` per scope, or a `@base` for small files.
2. **Preview.** The inspector shows the pending patch as text and the projected schema validation of the patched value, run in the background. Invalid edits are marked inline (`⚠`) but may still be staged.
3. **Apply.** `w` runs `novafile_patch::apply` on the *current on-disk* value. If the file changed underneath, the base or expect check fails and the TUI offers rebase or abort. Application is atomic (§7.5).
4. **Save with comments preserved (span-splicing).** The parser already records byte spans per path, including the key range (`parse_with_spans` / `SpanMap`). For each op:
   - *replace a scalar*: substitute the value's byte range with the canonical spelling of the new value (§4.10);
   - *add a field*: insert a new line after the last sibling's span at the sibling's indentation;
   - *add a list item*: likewise, as `- ` or a table row (and update the `[N]` header count);
   - *remove*: delete the entry's line range, including trailing inline comments, but keep full-line comments above it;
   - *anything else* (replacing a block subtree with a different shape): re-render that subtree in the human profile and splice it in. Comments **inside** that subtree are lost and the user is warned.

   **Safety invariant:** after splicing, re-parse the new text and require `revision(new_text) == revision(patched_value)`. On mismatch, refuse to save, show a diff, and offer `:w!` for a full re-render that drops comments. The write is atomic: temp file, `fsync`, `rename`, preserving mode bits.
   This gives document-preserving edits *before* the lossless CST (Appendix C item 3) exists. When the CST lands, the splice engine moves onto it.
5. **Undo and redo** use inverse patches:

   | Op | Inverse |
   | --- | --- |
   | `T: a -> b` | `T: b -> a` |
   | `+ T: v` on a record field | `- T: v` |
   | `+ L: v` append to a list | `- L[n]: v`, where n is the length before the append |
   | `+ S: v` on a set | `- S[v]` |
   | `- T: old` | `+ T: old` (lists: insert at the recorded index) |
   | `= T: v` | Recorded at stage time as `T: old -> v`, or `+ T: v` if T was absent |

   Undo before save pops a staged op. Undo after save stages the inverse as a new edit, so history is linear and every step is conditional.
6. **Safety.** Read-only is the default. `--edit` is required, and the title bar shows `EDIT`. Edits on a file with no schema warn once. Binary files are edited by re-encoding the whole frame, after checking the frame flags (CANONICAL and DEDUPE are preserved) — or via the append path below.
7. **Big files (for example 5 GB).** Never rewrite in place. `w` **appends** the patch to `FILE.patches` (a `---` text stream of `@patch` docs with `@scope` and `@expect`). The view overlays pending sidecar patches; changed nodes are marked `◆`. `:compact` (or `nvf compact`) materializes a new file in a streaming pass and replaces the original atomically. For indexed binary streams, an edited record can instead be **appended as a new frame plus a new `!index`** that redirects the ordinal (§5.3), which also never rewrites old bytes.

### 7.7 Scope

**MVP (one release)**

- Fix the §2.2 quadratic and allocation issues (a prerequisite for anything bigger than 10 MB).
- `nova-tui`, read-only: tree view with `h j k l` and folding, inspector with types and schema hover, breadcrumbs, `/` search with `n`/`N`, `:` path bar (singular jump, plus a results list for `[*]`, filters and projections), table view for uniform lists, yank (`yy yv yk yp yj`) via OSC 52, `m` source mode.
- Fully loaded documents up to about 64 MiB. Virtualized rendering from day one.
- Inputs: NOVA text, binary, JSON, JSONL (shown as a list).

**Phase 2**

- `--edit`: staging, preview, validation, inverse-patch undo, span-splice save with the re-parse invariant.
- Large text: lazy structural outline (§5.6), background search.
- NOVA Lines reader and writer in `nova-stream`. `nvf get --stream`. TUI tail mode.

**Phase 3**

- Binary pull events, `ValueRef`, `0x13 sized`, META frames, `!index` and locator, SHARED_DICT.
- `tree:` revisions, `@expect`, patch sidecars, `nvf compact`, `nova verify`.
- Big-file editing via sidecars. Frequency view (`F`) and column stats in the table view.

**Later:** zstd-seekable reading, parallel parsing, in-band `!patch` frames, an LSP-shared `nova-doc`, `@ref` navigation (Appendix C item 2), and a CST-backed editor.

---

## 8. Proposed spec text

### 8.1 §4.7 addition: the indentation invariant

> **Continuation lines.** When a flow value spans lines, every continuation line MUST be indented by more spaces than the line on which the flow value begins. A line that contains only a closing bracket MAY be indented exactly as much as that line. In particular, a line at column 1 is never inside a flow value that began on an earlier line.

Rationale: this makes `---` splitting (§4.11), structural indexing and parallel parsing well-defined. It is backward-incompatible only for documents that place flow continuation lines at or below the owner's indentation. Writers in the reference implementation never produce those.

### 8.2 §4.11 amended and §4.12 added

> **4.11 Text streams.** A text stream is a sequence of documents separated by lines consisting exactly of `---`. Because of the continuation-line rule (§4.7), such a line can never occur inside a document. Each document is parsed independently; an error in one document does not prevent reading the others.
>
> **4.12 NOVA Lines.** A NOVA Lines stream (media type `application/nova-lines`, extension `.novl`) is UTF-8 text consisting of an optional **header** of directive lines, followed by **record lines**. Blank lines and lines whose first non-space character is `#` are ignored. A record line is one flow value (§4.7) that MUST NOT span lines. If a `@columns {c1, …}` directive is in effect, each record line is instead a table row (§4.9) under those columns, and denotes a record.
>
> Directives defined for NOVA Lines (each at column 1, on its own line):
>
> | Directive | Meaning |
> | --- | --- |
> | `@nova`, `@schema` | As in §4.2. Appearing after a record line, they begin a new segment. |
> | `@columns {c1, …}` | Column names for the following rows. MAY be repeated; each occurrence applies until the next. |
> | `@key <field>` | Every record has a unique value at `field` within the segment. A violation is an error. |
> | `@end <count> [<revision>]` | Ends the segment: `count` records were written, and the optional `tree:` revision (§2.14) is the root of the segment. It MUST be followed only by blank lines, comments or a new segment. |
>
> A reader that reaches the end of input without `@end` MUST report the stream as *open*. A reader in **recovering** mode that encounters an invalid record line MUST report it and continue with the next line. A NOVA Lines stream denotes the list of its records.

### 8.3 §7.4 and §7.5 additions: `@expect` and removing the scope root

> `@expect <rev>` — OPTIONAL; requires `@scope`. Before any operation is applied, the revision of the value at the scope MUST match `rev` (prefix match per §2.13), otherwise the patch fails with a *stale scope* conflict. `@base` and `@expect` MAY both be given.
>
> (§7.5 table, `- T`): When `T` is `.` and a scope `S` is in effect whose parent is a list, or a stream (§4.12, §5.5), the scoped element is removed.

### 8.4 §2.14 (new): tree revisions

> The **tree revision** of a value is computed by the NOVA Tree Hash (version 1) defined in Appendix E, and is written `tree:` followed by 64 lowercase hexadecimal digits. Equal values have equal tree revisions. Wherever this specification accepts a revision as a precondition, a tree revision is also accepted. Implementations MUST NOT compare a `sha256:` revision with a `tree:` revision. Tree revisions are RECOMMENDED for identifying streams and documents too large to hash in canonical form.

(Appendix E is the definition in §5.8, with test vectors.)

### 8.5 §5.1 addition: tag `0x13`

> | `0x13` | sized | `varint(len)` value | The value MUST be a list, tuple, set, record, map or variant with payload, and its encoding MUST occupy exactly `len` bytes. It denotes that value. String-table entries appended while decoding the wrapped value are removed when it ends (§5.3). MUST NOT occur in the canonical encoding. |

(Coordinate with Proposal 0001, which takes `0x12` for tensors.)

### 8.6 §5.4 additions: flags

> | `0x10` META | The payload is a stream-control value (§5.6). It is not part of the data the stream denotes. |
> | `0x20` SHARED_DICT | A `dict_id: varint` follows the schema reference, if any. The frame's string table initially holds the strings of dictionary `dict_id` (§5.6), in order. MUST NOT be combined with CANONICAL. |

### 8.7 §5.6 (new): stream control and indexes

> META frames carry one variant: `!header{…}`, `!dict{id, strings}`, `!index{…}`, `!end{count, root?}` or `!locator(bytes)`. Readers MUST ignore META variants they do not recognize. If a binary file ends with an index, its last 26 bytes MUST be a `!locator` frame without CRC whose payload holds the big-endian `u64` offset of the `!index` frame. An index is advisory: readers MUST NOT accept data that contradicts it, and MAY rebuild it. A frame stream whose `!header` has `batched: true` denotes the concatenation of its data frames' list payloads; otherwise it denotes the list of the data frames' payloads.

### 8.8 §7.3 addition: streaming responses

> A host MAY answer a query whose result is a sequence (`[*]`, filters) with a NOVA Lines stream instead of a document. Such a response carries `@scope` (when applicable) in the header and SHOULD end with `@end <count>`. It MAY omit `@revision` when the queried document's revision is not known without a second pass. If it includes one, it MUST be the revision of the queried document.

---

## 9. Open questions

1. **`@end` placement and signing.** Should `@end` carry a signature (for example an ed25519 field `sig:`) for append-only audit logs, or is that left to an outer layer? (Leaning toward an outer layer, via an `x-sig` directive.)
2. **Value mode vs. table mode in one stream.** Is `@columns` redefinition worth the splitter complexity, or should a column change start a new segment (`@nova` again)?
3. **`tree:` leaf-inlining threshold.** Is 1 KiB right? Should it be part of the algorithm identity (`tree:` vs `tree1k:`)? It must be fixed forever once published.
4. **Map ordering in `tree:`.** Sorting entries by `hash(key)` is simple, but the order diverges from canonical order. Is that a problem for proofs that a key is absent? (Absence proofs would want key-sorted order.)
5. **Breaking change of §4.7.** Is the continuation-line rule acceptable for 0.2, or should `split_stream` instead track bracket depth? (That would make stream splitting depend on full lexing, which costs splittability.)
6. **`sized` everywhere vs. thresholded.** Should the CLI default to `sized_threshold = 4096` for `--to binary`, or off, preserving today's bytes? Should there be a frame flag announcing that `sized` is present?
7. **Batched frames vs. one record per frame.** Is the `batched` header bit a good idea, or should batching be a distinct frame flag, so that a frame is self-describing without the header?
8. **Key index format.** Use a sorted `(hash64, ordinal)` table, or a minimal perfect hash? What happens with hash collisions in `by_key`? (A verify-on-read fallback is planned.)
9. **TUI editing of tables.** Should editing a cell in a `[N]{…}:` table splice the cell in place? (Yes, with comma and quote handling.) Should adding a column re-render the whole table? (Probably.)
10. **Sidecar naming and discovery.** Use `FILE.patches` or `FILE.nova-patches`? Should `nvf get` apply sidecars automatically (risky), or only with `--with-patches`?
11. **Schema validation of streams.** Validate per record against `@schema` (a schema for the record type) or against the list type? (Proposal: `@schema` in a stream header names the **record** type.)
12. **JSONL detection.** Should `nvf` treat `.jsonl` as a stream (lazily) rather than as a `List` value by default? (Yes, for `get --stream` and the TUI. `convert` keeps today's behavior.)

---

## Appendix: Sources

- RFC 7464 JSON Text Sequences: https://datatracker.ietf.org/doc/html/rfc7464 (◐ via search snippets; `www.rfc-editor.org` was unreachable)
- RFC 8742 CBOR Sequences: https://www.rfc-editor.org/rfc/rfc8742.html (◐)
- Protobuf delimited messages: https://github.com/protocolbuffers/protobuf/blob/main/src/google/protobuf/util/delimited_message_util.h (✔)
- Arrow columnar and IPC format: https://github.com/apache/arrow/blob/main/docs/source/format/Columnar.rst (✔; arrow.apache.org was unreachable)
- Avro specification: https://github.com/apache/avro/blob/main/doc/content/en/docs/%2B%2Bversion%2B%2B/Specification/_index.md (✔)
- Parquet format: https://github.com/apache/parquet-format/blob/master/README.md (✔)
- TOON spec: https://github.com/toon-format/spec/blob/main/SPEC.md (✔)
- zstd seekable format: https://github.com/facebook/zstd/blob/dev/contrib/seekable_format/zstd_seekable_compression_format.md (✔)
- safetensors: https://github.com/huggingface/safetensors/blob/main/README.md (✔)
- DuckDB JSON loading: https://duckdb.org/docs/current/data/json/loading_json (◐)
- SQLite JSONB: https://sqlite.org/jsonb.html (◐)
- jless: https://github.com/PaulJuliusMartinez/jless (✔ README and `src/app.rs` keymap)
- jnv: https://github.com/ynqa/jnv (✔)
- fx: https://newreleases.io/project/github/antonmedv/fx/release/40.0.0 (◐)
- gron: https://github.com/tomnomnom/gron (✔)
- VisiData: https://github.com/saulpw/visidata (✔ README; ○ feature details)
- lnav: https://docs.lnav.org/en/stable/ui.html (◐)
- tui-tree-widget: https://github.com/EdJoPaTo/tui-rs-tree-widget (✔ README only)
- Not re-verified (○): RFC 6962 Merkle tree hash, BLAKE3 tree mode, PDF incremental update, ratatui, crossterm and tui-textarea APIs, yazi, Helix keymaps, DuckDB parallel NDJSON details, `sample_size` default.
- Local measurements: §2.1. Release build of a scratch copy of this workspace on 2026-11-17, 4 vCPUs, single runs.
