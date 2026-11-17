# NOVA Proposal — Appendix D: Tensors (vectors, matrices, n-dimensional arrays)

| | |
| --- | --- |
| Status | Draft proposal for discussion. Not normative until merged into SPEC.md. |
| Targets | §2 (value model), §4.7–4.10 (text), §5.1–5.2 (binary), §6.1–6.5 (schemas), §7.1 (paths), §11 (interop) |
| New kind | `tensor` |
| New binary tag | `0x12` |
| Date | 2026-11-17 |

---

## D.0 Summary

NOVA should add **one new value kind, `tensor`**: an element *dtype*, a *shape* (a list of non-negative dimension sizes), and a flat, row-major sequence of `product(shape)` elements, all stored in that dtype. A vector is a rank-1 tensor and a matrix is a rank-2 tensor. They are not separate kinds, but the schema language gives them aliases. A tensor is **not** sugar over nested lists. It is a distinct kind with its own equality, because NOVA's existing scalar kinds cannot represent `f32`, `bf16` or `i8` elements faithfully. A list of lists of floats is a different value from a tensor that holds the same numbers.

| Facet | Recommendation |
| --- | --- |
| Element dtypes (v1) | `bool`, `i8 i16 i32 i64`, `u8 u16 u32 u64`, `f16 bf16 f32 f64` |
| Deferred, codes reserved | complex (`c64`, `c128`), FP8/FP6/FP4, sub-byte ints, packed bits |
| Layout | row-major (C order) only; little-endian element bytes in binary |
| Shapes | rank 0 to 64 (MUST support up to 32); zero-sized dimensions allowed |
| Text (primary) | `@tensor<f32>[2,3](1.5, 2, 3; 4, 5, 6.25)`. `;` separates rows and `;;` separates 2-D slabs. A bytes escape hatch is `@tensor<f32>[1024,768](@bytes("…"))` |
| Binary | `0x12 dtype:u8 rank:varint dims:varint×rank pad:varint 0x00×pad data`. Canonical form has `pad = 0`; aligned (zero-copy) encodings choose `pad` |
| Schema | `tensor<f32, [3, 3]>`, `tensor<f32, [_, 768]>`, `tensor<f64, [n, n]>`, `vector<f32, 1536>`, `matrix<f64, 4, 4>` |
| Resolution | A rectangular nested list resolves to a tensor when every leaf is *admissible* in the dtype. The rule is exact or decimal-faithful: no silent rounding |
| Sparse | Out of v1. It is a library schema (COO), not a kind |
| Complex | Out of v1. Codes are reserved, and the interim encoding is a trailing axis of size 2 |

---

## D.1 Motivation

Today a 3×3 rotation matrix in NOVA is `[[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]`. That has five problems:

1. **Untyped.** The element precision (`f32` or `f64`) is lost, and `i8` and `u8` data become arbitrary-precision `int`s.
2. **Ragged-unsafe.** Nothing in the value says that the rows have equal length. The reader must re-check it every time.
3. **Verbose in binary.** Every element costs a type tag plus 8 bytes, or a varint. A 768-dimension `f32` embedding is 6,915 bytes as a NOVA list of floats, against 3,078 bytes as a tensor (§D.6.6).
4. **Slow.** Decoding is per element. No reader can memory-map the data or hand it zero-copy to NumPy, PyTorch or BLAS.
5. **Ambiguous shapes.** `[]` cannot say whether it is shape `[0]`, `[0, 3]` or `[3, 0]`, and a scalar cannot carry an `f32` or `bf16` precision.

Embeddings (vector databases, RAG pipelines), model weights and checkpoints, sensor frames, transforms in robotics and graphics, and scientific data all need this. Nearly every successor to JSON has had to bolt it on later: CBOR's RFC 8746, BSON's vector subtype 9 and Arrow's tensor extension types are examples.

---

## D.2 Prior art

Sources marked ✔ were read from primary source text (specification documents or source code fetched from the projects' GitHub repositories) while preparing this proposal. Sources marked ○ are cited from background knowledge because the hosts were not reachable from the research environment, and should be re-checked before this text becomes normative.

### D.2.1 Survey table

| Format | Shape representation | Dtypes | Order / endianness | Zero dims, rank 0 | Alignment | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| **CBOR typed arrays, RFC 8746** ✔ | Tag 40: `[dims, array]` (row-major). Tag 1040: column-major | Tags 64–87: `uint/sint 8–64`, `binary16/32/64/128`, both endiannesses, plus "clamped uint8" | Endianness is a tag bit. Order is set by the tag (40 or 1040) | Dims "MUST be unsigned integers distinct from zero", so zero-sized dims cannot be expressed | None specified | The element count is implied by the byte-string length. No bf16, no bool typed array. Tag 41 marks a "homogeneous array" |
| **NumPy `.npy`** ✔ | Header dict `{'descr', 'fortran_order', 'shape'}` as a Python literal | Any NumPy dtype, including structured and object (pickled) | Endianness is in `descr` (`<f4`). C or Fortran order | `shape=()` is one element. Zero dims allowed | Header padded so data starts at a multiple of **64** bytes (`ARRAY_ALIGN = 64`) | v1.0 header ≤ 65,535 bytes. Readers cap the header at 10,000 bytes by default |
| **safetensors** ✔ | JSON header: `{name: {dtype, shape, data_offsets:[begin,end]}}`, plus `__metadata__` (string→string only) | `BOOL`, `U8…U64`, `I8…I64`, `F16`, `BF16`, `F32`, `F64`, `C64`, and `F8_E4M3`, `F8_E5M2`, `F8_E8M0`, `F4`, `F6_*` and others | Little-endian, C order, no strides | Both allowed | Header length padded to a multiple of 8. Tensors sorted by descending dtype alignment | Header ≤ 100 MB. No holes or overlaps in the buffer. Built for mmap and lazy loading. Values (NaN, Inf) are not validated |
| **Apache Arrow** ✔ | `FixedSizeList<T>[n]` for vectors. `arrow.fixed_shape_tensor` holds `shape` (plus `dim_names`, `permutation`) in metadata. `arrow.variable_shape_tensor` keeps each row's shape in a struct field. Separate IPC `Tensor` and `SparseTensor` messages | Any Arrow primitive type | Row-major physical layout. `permutation` describes logical transposes | — | Buffers 8-byte aligned, 64 recommended (○) | Sparse indexes: COO, CSR/CSC (`CSX`), CSF |
| **ONNX `TensorProto`** ✔ | `repeated int64 dims` | 28 types including `FLOAT16`, `BFLOAT16`, `COMPLEX64/128`, FP8 variants, `INT4/UINT4`, `INT2`, `FLOAT4E2M1`, `FLOAT6*` | "MUST be organized in row-major order". `raw_data` is little-endian | Yes | External data offsets "SHOULD be multiples of 4096" for mmap | Typed fields (`float_data`) or `raw_data`. Complex is interleaved real and imaginary. Bool is one byte per element. Sub-byte types packed LSB-first. `SparseTensorProto` = values + indices + dims. Symbolic dims through `dim_param` |
| **Protobuf packed repeated** ✔ | None; rank 1 only | Any scalar numeric | Fixed32/64 little-endian; ints as varints | — | — | Packed is the default for proto3 and Edition 2023. One `LEN` record of concatenated elements. Parsers must also accept split runs |
| **HDF5** ○ | Dataspace: rank ≤ 32 (`H5S_MAX_RANK = 32` ✔ in `H5Spublic.h`), with max dims or unlimited | Rich datatypes with explicit byte order | C order | Yes | — | Chunked layout, filter pipeline (deflate, shuffle, szip), fill values, attributes |
| **NetCDF-4** ○ | Named, shared dimensions. One unlimited dimension | Like HDF5 (built on it) | C order | — | — | Dimension names are first-class. CF conventions carry units and axes |
| **Zarr v3** ✔ | `shape`, `data_type`, `chunk_grid`, `dimension_names` | `bool`, `intN`, `uintN`, `float16/32/64`, `complex64/128`, raw bits, plus extensions | Endianness is a **codec** (`bytes` codec with `"endian"`), not part of the dtype | — | — | Chunk grid, codec pipeline (array→array, array→bytes, bytes→bytes). `fill_value` is required (e.g. `"NaN"`) |
| **MessagePack ext** ✔ | — | — | — | — | — | Ext types −128…−1 are reserved for predefined types (only timestamp, −1, is defined). Applications use 0…127. Libraries such as msgpack-numpy encode arrays as maps (○) |
| **BSON binary subtype 9** ✔ | Rank 1 only | `INT8 (0x03)`, `FLOAT32 (0x27)`, `PACKED_BIT (0x10)` | Little-endian | Empty allowed | — | Layout is `dtype:u8, padding:u8, data`. `padding` counts ignored low bits in the last byte of `PACKED_BIT`. Ignored bits SHOULD be zero "to ensure the same data representation has the same encoding" |
| **Amazon Ion** ○ | None | — | — | — | — | No typed arrays. The usual convention is an annotated `blob` (`f32_le::{{…}}`), whose meaning both sides must agree on out of band |
| **JSON** ○ | Nested arrays | Number only | — | `[]` loses shape | — | GeoJSON (RFC 7946) `coordinates` are nested arrays and often deliberately **ragged** (polygon rings, MultiPolygon depth 4) |

### D.2.2 Notation in languages and tools

| Tool | 2×2 literal / printed form | Remarks |
| --- | --- | --- |
| NumPy `repr` ○ | `array([[1., 2.],` / `       [3., 4.]], dtype=float32)` | dtype printed when not the default. Output **summarized** with `...` above `threshold` (1000 elements by default), which is lossy |
| Julia ✔ | `[1 2; 3 4]`. Higher dimensions use `;;`, `;;;`: "the number of semicolons in the separator specifies the particular dimension" | Column-major. `;` = dimension 1 (vertical), `;;` = dimension 2. Spaces and `;;` both concatenate horizontally |
| MATLAB / Octave ○ | `[1 2; 3 4]` or `[1, 2; 3, 4]` | Column-major storage. Commas optional within a row |
| Rust `ndarray` `Debug` ○ | `[[1.0, 2.0],` / ` [3.0, 4.0]], shape=[2, 2], strides=[2, 1], layout=Cc (0x5), const ndim=2` | serde form is `{"v":1,"dim":[2,2],"data":[…]}` ✔. `data` is in logical (row-major) iteration order |
| nalgebra ✔ | — | Storage is **column-major** (`VecStorage` "stored in column-major order"), so mapping to NOVA requires a transpose |
| jaxtyping / ONNX `dim_param` ✔ | `Float[Array, "batch 768"]` | Symbolic dimension names in types |

### D.2.3 Lessons

1. **dtype + shape + flat buffer** is the universal model (NumPy, safetensors, ONNX, Arrow, Zarr, HDF5). Nested lists appear only in text formats and in JSON.
2. **Row-major and little-endian won.** safetensors, ONNX `raw_data`, BSON vectors and the Arrow tensor types fix both. RFC 8746 keeps both endiannesses and both orders, which costs it a unique encoding.
3. **Zero-sized dimensions and rank 0 matter.** NumPy, safetensors and ONNX allow them. RFC 8746's tag 40 forbids zero dims, a gap that a NOVA→CBOR mapping must report.
4. **bf16 is no longer optional** for ML payloads (safetensors, ONNX). RFC 8746 predates it.
5. **Alignment drives zero-copy.** NumPy pads to 64 bytes, safetensors to 8 plus sorting by alignment, and ONNX recommends 4,096. A varint-based stream cannot be aligned by accident.
6. **Unique encodings need care.** BSON requires zeroed padding bits explicitly so that equal vectors encode identically, which is exactly NOVA's concern in §2.12.
7. **Chunking, compression and fill values belong to storage engines** (HDF5, Zarr), not to a value-interchange format.
8. **Ragged data stays nested lists** (GeoJSON). Tensors complement lists; they do not replace them.

---

## D.3 Value model

### D.3.1 Definition (proposed §2.14)

A **`tensor`** is a triple *(dtype, shape, elements)*:

- **dtype** is one of the element types in §D.3.2.
- **shape** is a sequence of *rank* non-negative integers `d₀ … d_{r−1}`, with 0 ≤ r ≤ 64.
- **elements** is a sequence of exactly `d₀ × … × d_{r−1}` elements (1 when r = 0) of that dtype, in **row-major order**: the last index varies fastest.

Kind table row: `tensor` — *a dense n-dimensional array of fixed-width numeric or boolean elements of one dtype.*

### D.3.2 Element dtypes (v1)

| Name | Bits | Element domain | Element read as NOVA kind | Canonical NaN |
| --- | --- | --- | --- | --- |
| `bool` | 8 | false/true (bytes `00`/`01` only) | `bool` | — |
| `i8` `i16` `i32` `i64` | 8–64 | two's-complement integers | `int` | — |
| `u8` `u16` `u32` `u64` | 8–64 | unsigned integers | `int` | — |
| `f16` | 16 | IEEE 754 binary16 | `float` (exact widening) | `7E00` |
| `bf16` | 16 | bfloat16 (1 sign, 8 exponent, 7 fraction bits) | `float` (exact widening) | `7FC0` |
| `f32` | 32 | IEEE 754 binary32 | `float` (exact widening) | `7FC00000` |
| `f64` | 64 | IEEE 754 binary64 | `float` | `7FF8000000000000` |

The dtype names deliberately reuse the integer names in §6.1 (`i8`…`u64`). Every `f16`, `bf16` and `f32` value is exactly representable in binary64, so reading an element as a NOVA `float` never loses information.

### D.3.3 Rules

- **Vector and matrix.** A vector is a rank-1 tensor and a matrix is a rank-2 tensor. They have no separate kinds. Schemas offer aliases (§D.7).
- **Rank 0.** Shape `[]` has exactly one element. This also gives NOVA a way to carry a single `f32` or `bf16` scalar with its precision.
- **Zero-sized dimensions** are allowed. `[0, 3]`, `[3, 0]` and `[0]` are different shapes, and all three have zero elements.
- **Maximum rank.** Implementations MUST support rank ≤ 32 (HDF5's limit, and NumPy 1.x's) and MUST reject rank > 64 (NumPy 2's `NPY_MAXDIMS`).
- **Size.** `product(shape) × itemsize` MUST be computed with overflow checks. Implementations MAY impose a lower element limit (§D.11).
- **Order.** Row-major only. Column-major sources (Fortran, nalgebra, MATLAB) are transposed by the binding, which copies the data.
- **NaN.** As in §2.2, all NaNs of a dtype are one value, canonicalized to the bit pattern in the table. `+0.0` and `−0.0` are distinct. Encoders producing **canonical** output MUST rewrite NaN payloads. Decoders MUST treat any NaN bit pattern as the canonical NaN.
- **Equality.** Two tensors are equal if and only if their dtype, shape and element bit patterns (after NaN canonicalization) are equal. This follows from §2.12 because the canonical encoding (§D.6) captures exactly those. Consequently:
  - `tensor<f32>[2](1, 2)` ≠ `tensor<f64>[2](1, 2)`, since the dtypes differ;
  - `tensor<f32>[6](…)` ≠ `tensor<f32>[2,3](…)` with the same elements, since the shapes differ;
  - a tensor ≠ any list, including the list of its elements.
- **Ordering.** Canonical order is the bytewise order of canonical encodings, as for every kind. It is not numeric or lexicographic element order.
- **Not sugar over lists.** Treating tensors as nested lists plus an annotation would fail in three ways. `f32`, `bf16` and `i8` elements are not values of any NOVA kind. Shapes such as `[0, 3]` vanish. And the representation-independent equality of §2.12 would depend on an annotation. A list stays the right model for ragged or heterogeneous data.

### D.3.4 Paths and patches (proposed additions to §7.1 and §7.5)

| Segment | Applied to | Selects |
| --- | --- | --- |
| `[i]` | tensor of rank ≥ 2 | The sub-tensor at index *i* of axis 0 (rank r−1, same dtype). Negative values count from the end |
| `[i]` | tensor of rank 1 | The element, read as `bool`, `int` or `float` |
| `[*]` | tensor of rank ≥ 1 | Each slice along axis 0 (queries only) |

A path into a rank-0 tensor is a type mismatch.

Patch semantics:

- `=` and the replace operation on an **element** or **sub-tensor** keep the dtype and shape. A new element must be **admissible** (§D.7.3) in the dtype. A new sub-tensor must have the same dtype and shape, or be a nested list that resolves to them.
- `+` and `-` (insert, remove) on tensors are errors in v1, because they would change the shape. Replace the whole tensor instead.
- §7.6 diffs SHOULD emit element or row replacements when few elements change, and whole-tensor replacement otherwise.

---

## D.4 Text syntax

### D.4.1 Options considered

The token counts below are for a 4×4 `f32` matrix with shortest-round-trip elements, measured with a real BPE tokenizer (§D.5).

| # | Spelling | Example | Parse | Readability / diff | LLM tokens (4×4) | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| A | Nested lists + dtype annotation | `@tensor<f32>[[1, 2], [3, 4]]` | Easy. Shape inferred, so there is no truncation check and no way to write `[0,3]` | Familiar (JSON-like) and diffable per row | ≈ JSON (101–107) | Accept on **input** only through schema resolution (§D.7.3) |
| B | **Flat body with explicit shape and `;` row separators** | `@tensor<f32>[2,2](1, 2; 3, 4)` | Unambiguous. Shape and separators cross-check each other | Matrix-like, one row per line in the human profile | 108 compact / 115 spaced | **Primary** |
| C | Julia/MATLAB whitespace rows | `[1 2; 3 4]` | Collides with NOVA lists (`[` is a list), needs a dtype anyway, and whitespace-separated words are not NOVA flow syntax | Very readable for 2-D | **94** (cheapest) | Rejected as a standalone form. Whitespace separators inside B are an open question (§D.13) |
| D | Shorthand dtype head | `@f32[2,2](1, 2; 3, 4)` | Unambiguous, but reserves 12 more `@` names | Less self-explanatory | ≈ B − 2 | Rejected for v1. Possible compact-profile alias |
| E | Bytes escape hatch | `@tensor<f32>[2,2](@bytes("AACAPwAAAEAAAEBAAACAQA=="))` | Trivial | Opaque. Not diffable or reviewable | 77 (≈ 3.8 tokens per `f32` element) | **Secondary**, for large or opaque data |
| F | Typed JSON object | `{dtype: f32, shape: [2,2], data: [...]}` | It is a record: no new syntax, but no new kind either | Verbose | ≈ JSON + 10 | Rejected. Use as an interop convention only (§D.9) |

### D.4.2 Proposed syntax (§4.8a)

```
tensor      = "@tensor" "<" dtype ">" "[" [dim ("," dim)*] "]" "(" body ")"
dtype       = "bool" | "i8" | "i16" | "i32" | "i64" | "u8" | "u16" | "u32" | "u64"
            | "f16" | "bf16" | "f32" | "f64"
dim         = "0" | '1'..'9' digit*
body        = ε | elements | bytes-chunks
elements    = elem (sep elem)*
sep         = ","  |  ";"+                      ; see the separator rule
elem        = number | "true" | "false" | "nan" | "inf" | "-inf"
bytes-chunks = "@bytes(" quoted ")" ("," "@bytes(" quoted ")")*
```

- **Inside the body** only numbers, `true`, `false`, `nan`, `inf` and `-inf` may appear. Strings are impossible there, so these bare words are unambiguous, and `@float("nan")` is unnecessary. Whitespace, newlines and `#` comments are allowed between tokens, as in other flow values (§4.7).
- **Separator rule.** For rank ≤ 1, every separator is `,`. For rank r ≥ 2, the separator between the elements at flat positions *k* and *k+1* is `;` repeated *m* times. Here *m* is the number of trailing axes that complete at position *k*, capped at r − 1, so 0 means `,`. In practice `;` ends a row, `;;` ends a 2-D slab and `;;;` ends a 3-D block. A wrong separator is an error with the offending flat index. Like the `[N]` row count in tables (§4.9), this catches misaligned or truncated LLM output.
- **Trailing separators are not allowed.**
- **The count is checked.** The number of elements MUST equal `product(shape)`. Otherwise this is an error that names the expected and actual counts.
- **Element conversion.** Numeric literals are converted **directly from the decimal text to the dtype**, rounding to nearest-even, just as `0.1` already becomes the nearest binary64. A literal that overflows the dtype to infinity is an error (cf. §4.5). Integer dtypes accept only `int` literals within range. Float dtypes accept `int`, `float` and the non-finite words. `bool` accepts only `true` and `false`.
- **Bytes form.** The concatenated chunks hold exactly `product(shape) × itemsize` bytes of little-endian, row-major element data. Chunks let writers wrap long data. Every chunk except the last SHOULD be a multiple of 4 base64 characters.
- **Comparison with Julia.** For rank 2 the result looks like MATLAB and Julia (`1, 2; 3, 4`). Unlike Julia, NOVA counts semicolons from the **innermost** axis, matching row-major nesting. In Julia `;;;` is dimension 3 counted from the outermost axis, because Julia is column-major.

Examples:

```
identity: @tensor<f64>[3,3](
  1.0, 0.0, 0.0;
  0.0, 1.0, 0.0;
  0.0, 0.0, 1.0
)
bias: @tensor<f32>[4](0.1, -0.25, 0.0, 1.5e-7)
scale: @tensor<bf16>[](0.125)                 # rank 0
mask: @tensor<bool>[2,3](true, false, true; false, false, true)
empty: @tensor<f32>[0,768]()                  # zero rows, 768 columns
cube: @tensor<i8>[2,2,3](1,2,3; 4,5,6;; 7,8,9; 10,11,12)
weights: @tensor<f16>[1024,768](@bytes("AAA8…"), @bytes("…"))
```

Tables (§4.9) accept tensors as cells:

```
chunks[2]{id,text,embedding}:
  c1, "Intro", @tensor<f32>[4](0.12,-0.03,0.88,0.41)
  c2, "Usage", @tensor<f32>[4](0.07,0.19,-0.5,0.02)
```

### D.4.3 Writer rules (additions to §4.10)

| Profile | Rule |
| --- | --- |
| canonical | Always the element form, never bytes. Separators `, ` and `; `. Rank ≥ 2 puts each last-axis row on its own line, indented two spaces, with `;`/`;;` at the line end and `)` on its own line. Rank 0 and 1 go on one line. Elements use the **shortest decimal that round-trips in the element's dtype** (not in binary64), spelled under the §4.10 float rules (`.0` kept, scientific notation outside 1e-4…1e16), so `f32` 0.1 prints `0.1` rather than `0.10000000149011612`. Integers and `true`/`false` print plainly. Non-finite values print as `nan`, `inf`, `-inf`. |
| human | As canonical. A writer SHOULD switch to the bytes form above a configurable element count (suggested default 4,096), wrapping chunks at 76 characters, one per line. |
| compact | Element form with `,` and `;` and no spaces. `.0` MAY be dropped, because the dtype already fixes the kind. The bytes form is used above the threshold. LLM-facing hosts SHOULD instead offer projections (§D.13, Q6) rather than base64. |

### D.4.4 Interaction with existing rules

- `@tensor` adds one name to the typed-literal namespace and one production to `flow-value` (Appendix A). Because `@` already dispatches typed literals, the `<`, `>` and `[` after `@tensor` cannot be confused with a plain scalar.
- A plain list such as `[0.1, 0.2]` remains a list of `float`s. Principle 2 ("no surprising conversions") is kept: only an explicit `@tensor`, or a schema (§D.7.3), creates a tensor.

---

## D.5 LLM-friendliness and token cost

**Method.** Random N(0,1)·σ data was rendered in each spelling and counted with a real byte-level BPE tokenizer: the legacy Anthropic tokenizer bundled with `anthropic==0.34.2`. Other tokenizers were unreachable from the research environment. Modern tokenizers that split digits into fixed groups (for example, groups of up to three) will give different absolute numbers, so re-measure with the target model's tokenizer (§10). The relative ordering is the robust finding.

**4×4 `f32`, shortest round-trip repr (16 elements)**

| Spelling | chars | tokens | tokens/element |
| --- | ---: | ---: | ---: |
| JSON nested `[[a, b], …]` | 196 | 107 | 6.69 |
| JSON nested compact `[[a,b],…]` | 181 | 101 | 6.31 |
| NOVA `@tensor<f32>[4,4](a, b; …)` (human, one line) | 205 | 115 | 7.19 |
| NOVA rows on separate lines | 215 | 120 | 7.50 |
| NOVA compact `(a,b;c,d)` | 190 | 108 | 6.75 |
| NOVA with whitespace separators `(a b; c d)` | 193 | 103 | 6.44 |
| Julia `[a b; c d]` | 176 | 94 | 5.88 |
| NOVA bytes form (base64) | 112 | 77 | 4.81 |

**768-dimension embedding**

| Spelling | `f32` full precision: tokens/element | Rounded to 4 decimal places (lossy): tokens/element |
| --- | ---: | ---: |
| JSON `[a, b, …]` | 7.12 | 5.37 |
| JSON compact `[a,b,…]` | 6.62 | 4.87 |
| NOVA compact `@tensor<f32>[768](a,b,…)` | 6.63 | 4.88 |
| whitespace-separated | 6.12 | 4.37 |
| base64 | 3.78 | 3.79 |

**By dtype (768 elements, comma-separated, shortest repr for the dtype)**

| dtype | decimal tokens/element | base64 tokens/element |
| --- | ---: | ---: |
| `f64` | 10.33 | 7.77 |
| `f32` | 6.68 | 3.83 |
| `f16` | 5.01 | 1.84 |

Findings:

1. **The fixed header costs about 8–10 tokens** (`@tensor<f32>[768](` = 8). That is negligible except for very short vectors. In exchange the reader gets the dtype, the shape and a count check.
2. **Per-element cost is dominated by digits, not punctuation.** The compact tensor form matches compact JSON within ±1% while carrying more information. Dropping a level of brackets saves about 2 tokens per row.
3. **Separators.** `, ` costs about 0.5 tokens per element more than `,`, and `,` about 0.5 more than a space (the space merges into the following number's token). Whitespace-separated elements would save another ~8%. This is listed as an open question rather than adopted, because NOVA flow syntax is comma-separated everywhere else.
4. **Precision is the big lever, and it must be lossless.** Printing in the *element dtype's* shortest round-trip form is essential. `f32` drops from ~10 to ~6.7 tokens per element compared with printing via binary64, and `f16`/`bf16` drop to ~5. Rounding to fewer digits saves another ~25% but changes the value. That is acceptable only as an explicit, labelled lossy projection (Q6), never as a value-preserving conversion (§3).
5. **base64 is about 45% cheaper for full-precision `f32`, and 60–65% cheaper for `f16`.** But the model cannot reason over it. It suits pass-through (an agent moving an embedding from tool A to tool B) and does not suit reading or editing.
6. **For generation, structure beats compactness.** LLMs are poor at counting long runs, so explicit shape plus `;` row checks turn silent misalignment into a precise error, the same rationale as the `[N]` row counts in tables. Models should not be asked to *generate* large numeric tensors at all.

---

## D.6 Binary encoding

### D.6.1 Tag layout (proposed row for §5.1)

| Tag | Kind | Payload |
| --- | --- | --- |
| `0x12` | tensor | `dtype:u8` `varint(rank)` `varint(dim)×rank` `varint(pad)` `0x00×pad` `data` |

- `data` is exactly `product(dims) × itemsize(dtype)` bytes: row-major, **little-endian** elements. No length prefix is needed, because the length follows from the shape. The decoder MUST check this length against the remaining input **before** allocating (§12).
- `pad` is 0…4095. The pad bytes MUST be zero. They exist only so that an encoder can align `data`.
- `bool` elements MUST be `0x00` or `0x01`.
- Decoders MUST reject an unknown dtype, rank > 64, a non-minimal varint, an overflowing size, truncated data, non-zero pad bytes or invalid bool bytes.

### D.6.2 dtype codes

The high nibble is the class and the low bits give the size. Decoders look codes up in a table rather than computing them.

| Code | dtype | itemsize | | Code | dtype | itemsize |
| --- | --- | --- | --- | --- | --- | --- |
| `0x01` | bool | 1 | | `0x21` | f16 | 2 |
| `0x10` | i8 | 1 | | `0x22` | f32 | 4 |
| `0x11` | i16 | 2 | | `0x23` | f64 | 8 |
| `0x12` | i32 | 4 | | `0x29` | bf16 | 2 |
| `0x13` | i64 | 8 | | `0x2A–0x2F` | *reserved: FP8 E4M3/E5M2 and variants, E8M0* | 1 |
| `0x18` | u8 | 1 | | `0x30–0x3F` | *reserved: sub-byte floats and ints (FP4, FP6, i4, u4, i2, u2)* | packed |
| `0x19` | u16 | 2 | | `0x42`, `0x43` | *reserved: c64, c128* | 8, 16 |
| `0x1A` | u32 | 4 | | `0x50` | *reserved: packed bits (`u1`)* | packed |
| `0x1B` | u64 | 8 | | others | *reserved* | — |

### D.6.3 Endianness

The data is little-endian, although the scalar `float` (tag `0x04`) is big-endian. The inconsistency is deliberate. Tensors exist for bulk, zero-copy data, and every mainstream CPU and GPU is little-endian, as are safetensors, ONNX `raw_data`, BSON vectors and the Arrow tensor types. Scalars are not affected. A single fixed byte order also preserves NOVA's one-encoding-per-value property, which RFC 8746 gives up by offering both.

### D.6.4 Alignment and zero-copy

- **Canonical encoding (§5.2): `pad = 0`.** The canonical bytes of a value cannot depend on where the value sits in a stream, because equality and revisions are defined on a value's own encoding.
- **Aligned encoding (non-canonical).** An encoder MAY choose `pad` so that `data` starts at a multiple of *A* bytes from the start of the enclosing frame (the `N` of `NOVA`) or from the start of the buffer when there is no frame. *A* SHOULD be 64, as in NumPy, and MAY be 4,096 for page-granular mmap, as ONNX recommends for external data. Readers then hand out typed slices without copying. A frame-level flag `0x10 ALIGNED`, informational like `DEDUPE`, MAY announce this.
- Converting an aligned encoding to canonical form means removing the padding. That is a linear copy with no re-encoding of elements, except for NaN canonicalization in float dtypes.
- Back-references (§5.3) do not apply. Tensors contain no strings.

### D.6.5 Compression and chunking

These are **not in the value encoding.** The equality and revision rules require one encoding per value, and compression levels and codecs vary. Compression belongs to frames. A future frame flag could apply zstd to the payload, optionally after a byte-shuffle transform. Byte-shuffle, as in the HDF5 shuffle filter and Blosc, groups byte *i* of every element together and markedly improves float compressibility. Chunking, fill values and partial I/O are storage-engine concerns (HDF5, Zarr). A NOVA document can *reference* such stores, but it should not reimplement them.

### D.6.6 Worked example and size comparison

The value `@tensor<f32>[2,3](1, 2, 3; 4, 5, 6)` in canonical encoding:

```
12                tag tensor
22                dtype f32
02                rank 2
02 03             dims 2, 3
00                pad 0
00 00 80 3F  00 00 00 40  00 00 40 40     1.0 2.0 3.0
00 00 80 40  00 00 A0 40  00 00 C0 40     4.0 5.0 6.0
```

That is 30 bytes. The equivalent RFC 8746 encoding, `d8 28 82 82 02 03 d8 55 58 18` followed by 24 bytes, is 34 bytes. Tag 85 (`0x55`) is the little-endian binary32 typed array.

| Value | NOVA list of `float` lists | NOVA tensor | RFC 8746 (tags 40 + 85) | safetensors |
| --- | ---: | ---: | ---: | ---: |
| 2×3 `f32` | 60 B | 30 B | 34 B | 8 + JSON header (~60 B) + 24 B |
| 3×3 `f32` | 89 B | 42 B | 46 B | — |
| 768 `f32` embedding | 6,915 B | 3,078 B | 3,077 B (tag 85 only, no tag 40) | — |
| 1024×768 `f32` | ~7.1 MB | 3,145,736 B | 3,145,745 B | 3,145,728 B + header |

### D.6.7 Design comparison

| Property | NOVA `0x12` | RFC 8746 | safetensors | `.npy` |
| --- | --- | --- | --- | --- |
| Self-describing inline value | yes | yes | no (a container format) | no (one array per file) |
| Multiple tensors per document | anywhere in the tree | anywhere | flat name → tensor map | no (`.npz` = zip) |
| Unique encoding | yes (fixed little-endian, fixed order, `pad = 0`, canonical NaN) | no (two endiannesses, two orders, plain arrays or typed arrays) | no (header JSON spacing, key order) | no |
| bf16 | yes | no | yes | through extension dtypes (`ml_dtypes`) ○ |
| Zero-sized dims | yes | no (dims must be ≠ 0) | yes | yes |
| Alignment | optional `pad` | none | 8-byte header padding, sorted by alignment | 64 bytes |
| Random access to the *n*-th tensor | must walk the tree | must walk | O(1) through header offsets | — |
| Element count | from shape | from byte length | from offsets | from shape |

The one area where safetensors is clearly better is **random access**: lazy loading of one tensor from a multi-gigabyte checkpoint. NOVA could match it later with an optional *index frame* (Q8). It is not needed for v1.

---

## D.7 Schema integration

### D.7.1 Types (additions to the §6.1 table)

| Syntax | Meaning |
| --- | --- |
| `tensor<D>` | A tensor of dtype `D`, any rank and shape |
| `tensor<D, [s₀, …, s_{r−1}]>` | A tensor of rank *r* whose dimension *i* matches `sᵢ` |
| `sᵢ` = `768` | Exactly 768 |
| `sᵢ` = `_` | Any size |
| `sᵢ` = `n` (lowercase identifier) | Any size, but every occurrence of `n` *within the same type expression* must bind to the same size. `tensor<f64, [n, n]>` is a square matrix |
| `vector<D, N>` / `vector<D>` | Alias for `tensor<D, [N]>` / `tensor<D, [_]>` |
| `matrix<D, R, C>` / `matrix<D>` | Alias for `tensor<D, [R, C]>` / `tensor<D, [_, _]>` |

`D` is a dtype name from §D.3.2. Canonical schema text (§6.6) uses the long `tensor<…>` form, as it does for `list<T>`.

```
record Chunk:
  id: string @key @id(1)
  text: string @id(2)
  embedding: vector<f32, 1536> @finite @id(3)

record Camera:
  intrinsics: matrix<f64, 3, 3> @id(1)
  distortion: vector<f64> @len(4..8) @id(2)
  frame: tensor<u8, [h, w, 3]> @id(3)          # h and w are free, but bound once
  pose: tensor<f32, [n, n]> @id(4)             # square
```

### D.7.2 Attributes

| Attribute | On tensors | Meaning |
| --- | --- | --- |
| `@range(lo..hi)` | yes | Every element lies in range (NaN fails). |
| `@len(lo..hi)` | yes | Bounds the **element count**. Mainly useful on `vector<D>`. |
| `@finite` *(new)* | float dtypes | No NaN or ±∞. |

Validation errors carry the full path down to the element, for example `chunks[id=c7].embedding[1203]: NaN violates @finite`, and also a shape error like `expected [_, 768], got [12, 767]`.

### D.7.3 Resolution (additions to §6.3)

**Dtype admission.** A scalar value *x* is **admissible** in dtype *D* when:

| D | x is admissible if |
| --- | --- |
| `bool` | *x* is a `bool` |
| integer dtypes | *x* is an `int` within *D*'s range |
| float dtypes | *x* is an `int` exactly representable in *D* (every \|i\| ≤ 2¹¹ for f16, 2⁸ for bf16, 2²⁴ for f32 and 2⁵³ for f64 qualifies, as do larger values that happen to be representable). *Or* *x* is a `float` and either (a) *x* is exactly representable in *D*, including ±0, ±∞ and NaN, or (b) **decimal-faithful**: *x* equals the binary64 parse of the shortest round-trip decimal of `round_D(x)`. *Or* *x* is a `decimal` that equals that shortest decimal, or is exactly representable. The result is `round_D(x)`. |

Rule (b) is what makes schema-typed human documents usable. A config that says `embedding: [0.1, 0.2, 0.3]` under `vector<f32, 3>` resolves, because the canonical `f32` text of `round_f32(0.1)` is `0.1`. The conversion invents nothing: it inverts the injective map *f32 → shortest decimal → f64*. It rejects inputs that would need rounding, such as `0.123456789` for `f32`, `3.14159` for `f16` (whose shortest f16 form is `3.14`), or the integer `16777217` for `f32`. Rule (a) covers exact values whose shortest decimal is not their full expansion, such as f16 `65504`, whose shortest round-trip form is `6.55e4`. As a rule of thumb, decimals with up to 6 significant digits (`f32`), 3 (`f16`) or 2 (`bf16`) always pass. These are the binary formats' guaranteed decimal precisions (`FLT_DIG = 6`).

| Target type | Accepted input | Rule |
| --- | --- | --- |
| `tensor<D, S>` | list (nested) | The list must be **rectangular**. Depth and lengths give the shape, which must match `S`. Every leaf must be admissible in `D`. An empty list needs `S` to fix the rank. For `tensor<D>` without `S`, the rank is the nesting depth down to the first scalar, and `[]` is an error. Errors report the first ragged row or inadmissible element by path. |
| `tensor<D, S>` | tensor of dtype `D′` | Only if `D′ → D` is an exact widening: `f16 → f32 → f64`, `bf16 → f32`, `iN → iM` (M > N), `uN → uM` and `uN → iM` (M > N), and any int dtype → a float dtype whose significand holds it (`i8`/`u8`/`i16`/`u16` → `f32`, `i32`/`u32` → `f64`). |
| `list<T>`, `T[]` | tensor | **Never.** A tensor does not degrade into lists. |
| `float` | rank-0 float tensor | Never (no implicit unwrap). |

Resolution never reinterprets `bytes` as a tensor and never narrows a dtype.

### D.7.4 Evolution (additions to §6.5)

| Change | Classification |
| --- | --- |
| Fixed dimension → `_` or a symbol; symbol → `_` | compatible |
| `_` → fixed dimension; adding a symbol constraint | breaking |
| Exact dtype widening (as in §D.7.3) | compatible |
| Dtype narrowing or other change; rank change | breaking |
| `list<float>` → `tensor<f64, …>` | compatible if every old value is rectangular with the right shape (data-dependent; report as *conditional*) |
| `list<float>` → `vector<f32, N>` | breaking (old values may not be decimal-faithful) |
| Adding `@finite` or a tighter `@range` | breaking |

---

## D.8 Projections, queries and the agent model

- `@get model.layers[0].weight` returns the tensor as written. A host SHOULD refuse, or switch to the bytes form, above a size limit rather than flood a model's context window.
- Proposed (Q6): a **summary projection**, `@get model.layers[0].weight @summary`. It returns a *record*, not a tensor, such as `{dtype: f32, shape: [1024, 768], min: …, max: …, mean: …, nan: 0, sha256: …}`. It is explicitly not the value, so it cannot be mistaken for lossless data, unlike NumPy's `...` summaries. The `sha256` is the revision of the tensor, which lets an agent write a conditional patch against data it has never seen in full.

---

## D.9 Interoperability mappings (additions to §11)

### D.9.1 JSON

| Direction | Mapping | Report? |
| --- | --- | --- |
| JSON → NOVA | Arrays are **always** lists. Tensors appear only through schema resolution (§D.7.3) or the opt-in typed convention below | — |
| NOVA → JSON (default) | A tensor becomes nested arrays of depth = rank. Rank 0 becomes a bare number, and bool elements become `true`/`false`. Float elements are written as the dtype's shortest decimal | **yes**: dtype and shape lost; zero-sized dims collapse (`[0,3]` → `[]`); non-finite elements become strings (§11.1); readers will parse f32 decimals to the nearest f64, not the stored f32 |
| NOVA → JSON (typed, opt-in) | `{"$tensor": "f32", "shape": [2,3], "data": [1,2,3,4,5,6]}`. Above a threshold, `"data"` becomes a base64 string of little-endian bytes | lossless; recognized on input only in the same opt-in mode |

### D.9.2 Rust (serde and libraries)

| Rust type | NOVA mapping |
| --- | --- |
| `Vec<f32>`, `[f32; N]` | **List of `float`** by default. serde gives a serializer no homogeneity guarantee, and choosing the kind from contents would break principle 2. `#[serde(with = "nova::as_tensor")]` opts in to `tensor<f32,[n]>`. |
| `Vec<Vec<f32>>` | List of lists. With `nova::as_tensor`, the rows are checked to be rectangular and the value is emitted as rank 2. |
| `nova::Tensor<T>`, `nova::Vector<T, N>`, `nova::Matrix<T, R, C>` | Native. These serialize through a private newtype-struct marker (the technique `toml` uses for datetimes), so the NOVA serializer emits tag `0x12` / `@tensor` while other serializers (e.g. serde_json) see nested sequences. |
| `ndarray::Array<T, D>` | Its built-in serde form `{v, dim, data}` would become a record. The `novafile` crate's `ndarray` feature provides an adapter mapping it to a tensor. `data` is already in logical row-major order. Non-standard layouts are copied, and standard-layout arrays are borrowed zero-copy. |
| `nalgebra::Matrix` | Column-major storage. The adapter **transposes** into row-major (copy). The shape is `[nrows, ncols]`. |
| `half::f16`, `half::bf16` | `f16` / `bf16` elements. |

### D.9.3 NumPy, PyTorch and others

| NOVA dtype | NumPy | PyTorch | Arrow | ONNX | safetensors |
| --- | --- | --- | --- | --- | --- |
| bool | `?` | `torch.bool` | `bool` (bit-packed; repack) | BOOL | BOOL |
| i8…i64 | `<i1`…`<i8` | `int8`…`int64` | `int8`…`int64` | INT8…INT64 | I8…I64 |
| u8…u64 | `<u1`…`<u8` | `uint8` (others recent) | `uint8`…`uint64` | UINT8…UINT64 | U8…U64 |
| f16 | `<f2` | `float16` | `halffloat` | FLOAT16 | F16 |
| bf16 | `ml_dtypes.bfloat16` | `bfloat16` | — (extension) | BFLOAT16 | BF16 |
| f32, f64 | `<f4`, `<f8` | `float32`, `float64` | `float`, `double` | FLOAT, DOUBLE | F32, F64 |

- **NumPy.** On decode, `np.frombuffer(buf, '<f4').reshape(shape)` is zero-copy when the data is aligned. On encode, `fortran_order` arrays and non-contiguous views go through `np.ascontiguousarray`. Big-endian dtypes are byte-swapped, object and structured dtypes are rejected, and shape `()` becomes rank 0.
- **Arrow.** A NOVA list of tensors that share dtype and shape (for example the `embedding` column of a table) maps to `arrow.fixed_shape_tensor`. Mixed shapes map to `arrow.variable_shape_tensor`.
- **safetensors.** A NOVA record whose fields are all tensors maps to a safetensors file. `__metadata__` takes only string→string entries, so other metadata is reported.
- **CBOR (RFC 8746).** A rank-1 tensor becomes a typed array: tag `64 | (f<<4) | (s<<3) | (e<<2) | ll` with `e = 1` (little-endian) for multi-byte types, e.g. f32 = 85, f64 = 86, f16 = 84, i32 = 78. 8-bit types use only the `e = 0` codes, i8 = 72 and u8 = 64, because 68 means "clamped uint8" and 76 is reserved. Rank ≥ 2 adds tag 40 around it. bf16 and bool have no typed array: they use tag 40 around a plain array, and the mapping is **reported**. Zero-sized dimensions cannot be expressed in tag 40 (**reported**). On input, tag 1040 is transposed and big-endian typed arrays are byte-swapped.
- **BSON.** Rank-1 `f32` and `i8` tensors map to binary subtype 9 (`0x27`, `0x03`). Other dtypes become arrays, and the mapping is reported. `PACKED_BIT` waits for a future `u1` dtype.
- **Protobuf.** `repeated float/double/intN` (packed) maps to a rank-1 tensor of the matching dtype, with the shape kept in a sibling field by convention. ONNX `TensorProto` maps directly: `dims` → shape, `raw_data` → data.
- **MessagePack.** Use an application ext type (0…127) whose payload is the NOVA `0x12` payload. Libraries' map-based conventions are mapped by adapter, with a report.
- **GeoJSON.** It stays as nested lists, because coordinates are routinely ragged. This is the canonical example of when **not** to use a tensor.

---

## D.10 Sparse tensors and complex numbers

### D.10.1 Sparse: **out of v1**

There are many layouts, each optimal for different access patterns: Arrow alone defines COO, CSR/CSC and CSF, and ONNX offers coordinate or linearized indices. Choosing one canonical sparse layout would bake in a storage decision, and equality across layouts (is a sparse tensor equal to its dense form?) is hard to define. Recommendation:

- No new kind. Publish a **standard library schema** that composes dense tensors, modelled on ONNX's `SparseTensorProto`:

  ```
  record SparseCoo:
    shape: vector<u64>
    indices: tensor<u64, [nnz, r]>     # lexicographically sorted, unique
    values: tensor<f32, [nnz]>
  ```

- It is a different value from the dense tensor, and converting between the two is an explicit library operation.
- Revisit if Arrow or ONNX interop demands it.

### D.10.2 Complex: **out of v1, codes reserved**

NOVA has no complex scalar kind. Element access, `@range` and text spelling (`1+2i`?) would all need new design. Meanwhile the community layout is settled: interleaved real and imaginary parts, real first, as in ONNX, NumPy `c8`/`c16` and safetensors `C64`. Recommendation:

- Reserve dtype codes `0x42` (`c64`) and `0x43` (`c128`) and the text names `c64` and `c128`.
- Interim convention: a trailing axis of size 2, `tensor<f32, [n, 2]>`. It is **byte-identical** to `c64[n]`, so a future complex dtype can be a zero-copy reinterpretation plus an exact schema widening.
- The v2 design must decide the element-read kind (a `(float, float)` tuple or a new `complex` kind) and the text syntax.

---

## D.11 Security considerations (additions to §12)

- Compute `product(dims) × itemsize` with overflow checking. Reject the value if it exceeds the remaining input or the implementation's element limit, and do so before allocating. One rank-64 header of large varints must not cause a huge allocation.
- Bound the rank (≤ 64) and the `pad` (≤ 4095).
- Text parsers MUST bound the element count before materializing, and SHOULD stream elements into a buffer of the declared size.
- Zero-copy readers MUST NOT assume alignment unless they checked it. Unaligned data is valid, and readers copy it.
- Do not trust NaN payloads in non-canonical input to be canonical. Canonicalize before hashing or comparing.

---

## D.12 Recommended v1 scope

1. **A `tensor` kind** (dtype, shape, row-major elements). Vectors and matrices are ranks 1 and 2. Rank 0 to 64, with support for 32 required. Zero-sized dims allowed.
2. **Thirteen dtypes**: `bool`, `i8–i64`, `u8–u64`, `f16`, `bf16`, `f32`, `f64`, with canonical NaN per dtype and `−0 ≠ +0`.
3. **Text**: `@tensor<D>[dims](…)` with `,`/`;`/`;;` separators checked against the shape, the dtype's shortest round-trip element spelling, bare `nan`/`inf` inside the body, and the `@bytes(…)` chunk escape hatch. Tensors allowed as table cells.
4. **Binary**: tag `0x12` with a dtype byte, varint rank and dims, a `pad` varint and little-endian data. Canonical form has `pad = 0`. The frame flag `ALIGNED` is informational.
5. **Schemas**: `tensor<D, [dims]>` with integer, `_` and symbolic dims; `vector` and `matrix` aliases; `@range`, `@len`, `@finite`; list → tensor resolution with **exact or decimal-faithful admission**; exact dtype widening.
6. **Paths and patches**: index into axis 0 and replace elements or sub-tensors. Inserting or removing elements is an error.
7. **Interop**: JSON nested arrays (reported) and an opt-in typed JSON form; NumPy, ndarray and nalgebra adapters; RFC 8746 and BSON subtype 9 mappings.
8. **Reserved, not specified**: complex, FP8/FP6/FP4, sub-byte ints, packed bits, column-major.
9. **Out**: sparse kinds, compression, chunking, fill values, strides and views, named dimensions.

---

## D.13 Open questions

1. **Whitespace element separators.** Allowing `@tensor<f32>[2,2](1 2; 3 4)` saves about 8% of tokens and reads like MATLAB and Julia. Should it be allowed in the compact profile, or everywhere? The cost is a second spelling and a departure from comma-separated flow syntax.
2. **Shorthand head.** Should the compact profile accept `@f32[2,3](…)` as an alias? It saves about 2 tokens per tensor and matters for tables with many tensor cells.
3. **Typed table columns.** `chunks[N]{id, embedding: f32[768]}:` would declare the dtype and shape once in the header, so cells are bare `(…)` bodies. This saves about 8 tokens per row and would map to Arrow `fixed_shape_tensor`.
4. **Symbol scope.** Should dimension symbols bind across the fields of a record (`x: tensor<f32,[n,d]>`, `w: tensor<f32,[d,k]>`), as jaxtyping does? That is powerful, but it makes validation non-local.
5. **Rank-polymorphic shapes.** Should schemas accept `tensor<f32, [.., 3]>` (any leading dimensions)?
6. **Lossy and summary projections for agents.** Should queries offer `@summary` and `@precision(k)`, and how must their responses be marked so they are never mistaken for the value?
7. **Named dimensions** (NetCDF, Zarr `dimension_names`, Arrow `dim_names`). Should they be part of the value, which affects equality, or only of the schema? The suggestion is schema-only.
8. **Index frame** for O(1) lazy access to tensors in large documents (safetensors parity).
9. **Frame compression** (zstd, with optional byte-shuffle) as a frame flag. Interaction with the `CANONICAL` flag and with CRC.
10. **Column-major flag.** Is there demand from Fortran, R, MATLAB or Julia producers for a non-canonical column-major binary form, as in RFC 8746 tag 1040? Reserve a bit in the dtype byte or the pad varint?
11. **Patch values for float elements.** `= w[0][0]: 0.1` goes through decimal-faithful admission. Is that sufficient, or does a patch need an explicit `@f32(…)` scalar spelling for values outside rule (b)?
12. **bool encoding.** Should `bool` use one byte per element (NumPy, ONNX, safetensors), or should bits be packed (Arrow, BSON `PACKED_BIT`) for masks? v1 uses bytes, and `u1` is reserved for packed bits.

---

## D.14 References

✔ = read from the primary source during this research; ○ = cited from background knowledge (host not reachable from the research environment).

- ✔ C. Bormann (ed.), *CBOR Tags for Typed Arrays*, RFC 8746 (Internet-Draft source). https://github.com/cbor-wg/array-tags/blob/master/draft-ietf-cbor-array-tags.md · RFC: https://www.rfc-editor.org/rfc/rfc8746.html
- ✔ NumPy, *NPY format* (`numpy/lib/_format_impl.py`). https://github.com/numpy/numpy/blob/main/numpy/lib/_format_impl.py · docs: https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html
- ✔ NumPy `NPY_MAXDIMS = 64`. https://github.com/numpy/numpy/blob/main/numpy/_core/include/numpy/ndarraytypes.h
- ✔ Hugging Face, *safetensors* (README and `safetensors/src/tensor.rs`). https://github.com/huggingface/safetensors
- ✔ Apache Arrow, *Canonical Extension Types* (fixed and variable shape tensor). https://github.com/apache/arrow/blob/main/docs/source/format/CanonicalExtensions.rst · https://arrow.apache.org/docs/format/CanonicalExtensions.html
- ✔ Apache Arrow, `format/SparseTensor.fbs`, `format/Tensor.fbs`. https://github.com/apache/arrow/tree/main/format
- ✔ ONNX, `onnx.proto` (`TensorProto`, `SparseTensorProto`, `TensorShapeProto.Dimension.dim_param`). https://github.com/onnx/onnx/blob/main/onnx/onnx.proto
- ✔ Protocol Buffers, *Encoding*, "Repeated Elements" (packed). https://github.com/protocolbuffers/protocolbuffers.github.io/blob/main/content/programming-guides/encoding.md · https://protobuf.dev/programming-guides/encoding/#packed
- ✔ MongoDB, *BSON Binary Subtype 9 — Vector*. https://github.com/mongodb/specifications/blob/master/source/bson-binary-vector/bson-binary-vector.md
- ✔ MessagePack specification (extension types). https://github.com/msgpack/msgpack/blob/master/spec.md
- ✔ Zarr v3 core specification. https://github.com/zarr-developers/zarr-specs/blob/main/docs/v3/core/index.rst · https://zarr-specs.readthedocs.io/en/latest/v3/core/index.html
- ✔ HDF5 `H5S_MAX_RANK = 32`. https://github.com/HDFGroup/hdf5/blob/develop/src/H5Spublic.h
- ○ HDF5 user guide (datatypes, chunking, filters, fill values). https://support.hdfgroup.org/documentation/
- ○ Unidata NetCDF-4 data model. https://docs.unidata.ucar.edu/netcdf-c/current/
- ✔ Julia manual, *Multi-dimensional Arrays*, concatenation with `;;`. https://github.com/JuliaLang/julia/blob/master/doc/src/manual/arrays.md
- ✔ Rust `ndarray` serde format (`src/array_serde.rs`). https://github.com/rust-ndarray/ndarray/blob/master/src/array_serde.rs
- ✔ `nalgebra` `VecStorage` (column-major). https://github.com/dimforge/nalgebra/blob/main/src/base/vec_storage.rs
- ○ Amazon Ion specification. https://amazon-ion.github.io/ion-docs/docs/spec.html
- ○ H. Butler et al., *The GeoJSON Format*, RFC 7946. https://www.rfc-editor.org/rfc/rfc7946
- ○ NumPy printing options (`threshold`). https://numpy.org/doc/stable/reference/generated/numpy.set_printoptions.html
- ○ jaxtyping. https://github.com/patrick-kidger/jaxtyping
