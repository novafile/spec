# NOVA Proposal 0006: Template expressions, functions and a standard library

| | |
| --- | --- |
| Status | Draft proposal for discussion. Not normative until merged into SPEC.md. |
| Targets | §9 (templates: new §9.3a–§9.3c, changes to §9.2–§9.5 and §9.7), §12 (security), §13 (template language 0.2, conformance class), Appendix A (grammar), Appendix C, Appendix E (lints), conformance suite |
| New kinds / tags / directives | none in the value model; template directive `@def`; template language version `0.2` |
| Depends on | nothing normative. Uses the I-Regexp dialect of §6.1 `@pattern` (proposal 0004, merged) for `matches` |
| Date | 2026-11-19 |

---

## 0006.0 Summary

Templates (§9) can reference, interpolate, spread, branch and loop, and nothing else. That keeps them total and easy to read, but it also means a template cannot lower-case a name, cut it to 63 characters, add one to a port, or compute a checksum of its configuration. Authors who need any of these today go back to Helm, or pre-compute values outside the template and pass them in as parameters.

This proposal adds the missing power **without making the template language Turing complete**:

1. **Expressions.** One small expression language for values, conditions, interpolations and loop sources: references, calls, comparisons (`<`, `<=`, `>`, `>=`), arithmetic (`+`, `-`, `*`) and list and record **comprehensions** (`[for s in $services if $s.enabled: $s.name]`).
2. **User functions** (`@def`), with typed parameters and an optional result type. A function can call only built-ins and functions defined **above** it, so the call graph is acyclic and recursion cannot be written.
3. **A standard library** of 40 built-in functions: strings, collections, numbers, conversions and encodings, each with exact, locale-free and portable semantics.
4. **A step budget** next to the existing output budget, as a safety net against expensive but finite renders.
5. **A determinism fix.** Iteration over records, maps and sets gets a defined order, so equal inputs always render to equal outputs.

| Facet | Recommendation |
| --- | --- |
| Computational power | Not Turing complete. Iteration only over values that already exist; no `while`, no `range`, no recursion, no functions as values. Every render terminates, and the work it can do is bounded by a polynomial in the input size whose degree is the depth of loop nesting along the call graph (§0006.7) |
| Call syntax | `$f(args)` in value positions; `${f(args)}` in interpolations. Bare `f(x)` stays a plain string, as in every data document |
| Operators | `or`, `and`, `not`, `==`, `!=`, `<`, `<=`, `>`, `>=`, `+`, `-`, `*`, surrounded by whitespace. No `/` (it is the rational literal), no `%`; integer division is `div`/`mod` |
| Numeric rules | No implicit conversion between kinds (§2.5). Integer results are checked against the portable range [−2^63, 2^64 − 1]. Floats follow IEEE 754 with no fused operations |
| User functions | `@def name(p: T, …): R = expr`, or a block body. Parameters are checked against their types, never converted. Earlier definitions only. Not exported through `@import` (yet) |
| Standard library | 40 functions in six groups (§0006.5). No time, randomness, environment, files or network. No `indent`, `quote` or `toYaml`: templates work on values |
| Unicode | Code-point semantics, full default case mapping without language-specific rules, `White_Space` for `trim`, all pinned to Unicode 17.0.0 for template language 0.2 |
| Typing | Built-ins have signatures in schema type syntax. Arguments are checked at render time; a checker SHOULD check them statically from the parameter types |
| Errors | Every misuse is a render error. There is no `try`; `default`, `get` and `contains` handle the expected cases |
| Limits | New step budget (reference: 10^7 steps), counted exactly so that every renderer accepts and rejects the same templates |
| Iteration order | Records by key in UTF-8 byte order; sets and maps in canonical order (§2.12); lists and tuples in order |
| Version | Template language 0.2 (`@template 0.2`). It defines the iteration order that 0.1 left unspecified (§0006.6). The one 0.1 spelling that stops parsing is an escaped quote inside an interpolation, and it fails loudly (§0006.2.1) |
| Rejected | Turing completeness, lambdas and higher-order functions, `range`, user recursion with a depth limit, method or pipe syntax, `try`/`catch`, locale-aware functions, regex replacement, text-level helpers |

---

## 0006.1 Motivation

### 0006.1.1 What authors cannot write today

The Helm comparison (`/vs/helm/` on novafile.dev) lists "Your templates compute: string functions, arithmetic or cluster lookups" as a reason to stay with Helm. Cluster lookups are out of scope for any value-level template language. The rest is not, and it is what most charts actually do with Sprig:

| Helm idiom | What it is for | NOVA 0.1 |
| --- | --- | --- |
| `{{ .Release.Name \| trunc 63 \| trimSuffix "-" }}` | Kubernetes names are DNS labels of at most 63 characters | impossible |
| `{{ .Values.name \| lower \| replace "_" "-" }}` | normalise user input into a name | impossible |
| `{{ add .Values.port 1 }}` | a derived port | impossible |
| `{{ include "config" . \| sha256sum }}` in an annotation | restart pods when their configuration changes | impossible |
| `{{ .Values.tags \| join "," }}` | a comma-separated flag | impossible |
| `{{ if gt .Values.replicas 1 }}` | a pod disruption budget only when there are replicas to protect | impossible: conditions only have `==` and `!=` |
| `{{ default "info" .Values.logLevel }}` | a fallback for an optional value | `@if $level != null` twice, once per branch |
| `{{ range ... }}{{ if .enabled }}…` collecting names into one string | filter and transform a list | impossible |
| `{{- define "labels" }}` + `include` | a reusable block | `@let` works only when nothing varies |
| `{{ toYaml .Values.x \| nindent 8 }}`, `quote` | turning values back into text | not needed: values are spliced as values |

The last row is the part NOVA already gets right, and it must stay that way. Everything else is computation on values, and it can be added without giving up what §9.5 guarantees.

### 0006.1.2 Why not make it Turing complete

It would take very little: an unbounded loop, or functions that can call themselves, is enough. The proposal deliberately stays below that line, for three reasons.

1. **Termination.** A renderer can run an untrusted template (from a chart repository, from an agent) and know that it finishes. With a Turing-complete language, only a timeout can say that, and a timeout depends on the machine.
2. **Static checks.** A checker can type every expression from the parameter types, and can bound the cost of a render before running it. For a Turing-complete language, both questions are undecidable in general (Rice's theorem).
3. **Portability.** Limits on a Turing-complete language are wall-clock time or fuel counters that differ between implementations. A total language with an exactly counted budget accepts and rejects the same templates everywhere.

The languages that templates are usually compared with point the same way. Helm's named templates can include themselves, which is how charts end up with templates that do not terminate. Dhall, CUE and Starlark were designed to stay non-Turing-complete (Starlark forbids recursion and `while`, and loops only over existing values), and they are used at scale for configuration because of it, not despite it.

The cost is real but small. A template cannot express an algorithm whose number of steps is not bounded by its input: there is no fixpoint, no search and no unbounded string building. Configuration does not need those. Data that needs them should be computed by a program and passed in as a parameter.

---

## 0006.2 Expressions

### 0006.2.1 Where expressions appear

An **expression** computes a value. Template language 0.2 uses one expression grammar in five places:

| Place | Example | Form |
| --- | --- | --- |
| A value position in the body: after `key: `, after `- `, inside a flow collection | `name: $lower($n)` | an expression that begins with `$` |
| An interpolation in a quoted or block string | `"${lower($name)}-svc"` | `${` expression `}`; a leading `$` may be omitted |
| A condition | `@if $replicas > 1:` | any expression; it must evaluate to `bool` |
| A loop source | `@for s in $sort($names):` | any expression |
| The right-hand side of `@let`, `@def` and parameter defaults | `@let port = $base_port + 1` | any expression |

**Value positions.** A plain scalar cannot begin with `$` (§4.4), so a value position that begins with `$` is unambiguously an expression, and the expression runs to the end of the value: the end of the line, or, in flow context, the next `,` or closing bracket at the bracket depth where the expression began. Commas and brackets inside calls, groupings, flow collections and comprehensions belong to the expression, so `{maxUnavailable: $div($replicas, 2)}` is a record with one field. An expression that would begin with a literal is wrapped in `$( … )`:

```
port: $base + 1            # expression
port: $(1 + $base)         # expression that starts with a literal
port: 1 + $base            # NOT an expression: the plain string "1 + $base"
```

This keeps the rule of §9.2 that only `$` marks template code. A data document, or a value position without `$`, means exactly what it means today.

**Interpolations.** In 0.1, `${path}` takes a path without `$`. In 0.2, the content of `${ … }` is an expression, and if it begins with an identifier, a `$` is implied in front of it: `${name}` means `$name`, `${svc.ports[0]}` means `$svc.ports[0]`, and `${lower($name)}` means `$lower($name)`. The shorthand applies to the head only. Arguments are ordinary expressions, in which a bare word is a literal, so they are written in full:

```
"${lower($name)}-svc"      # call lower with the value of $name
"${lower(name)}-svc"       # call lower with the string "name": almost certainly a mistake (linted, §0006.8)
```

An interpolation is read as an expression up to its matching `}`, before the string's own escapes apply, so quotes and braces inside it belong to the expression: `"--tags=${join($tags, ",")}"` is one string. This is how JavaScript template literals and Python 3.12 f-strings work.

It is compatible with 0.1 except in one spelling. A 0.1 path may contain a quoted name or a string selector (§7.1), and inside a quoted string 0.1 writes its quotes escaped: `"${svc.\"odd key\"}"`. In 0.2 the content `svc.\"odd key\"` is read as an expression, where `\"` is not a token, so the template fails to load with a parse error instead of rendering something else. The 0.2 spelling is `"${svc."odd key"}"`. Paths of identifiers, indices and unquoted selectors, which is what 0.1 interpolations normally contain, are unchanged.

The value of an interpolation must be a scalar that §9.3 allows (a string, number, bool, timestamp, duration or unit variant), and is inserted as its canonical text.

### 0006.2.2 Operands

| Operand | Meaning |
| --- | --- |
| a flow value without `$` (§4.7): `production`, `8080`, `"a b"`, `[1, 2]`, `{a: 1}`, `!active`, `@duration(30s)` | a literal; bare words are classified by §4.4, so `production` is a string and `80` an int |
| a flow collection containing expressions: `[$a, $b]`, `{port: $p}` | a value built from the evaluated elements; duplicate keys are an error |
| `$name` followed by an optional path (§7.1) | a reference, as in §9.3 |
| `$name(arg, …)`, with `(` immediately after the name | a call (§0006.3, §0006.5). `$name (x)` with a space is a reference followed by a stray token, an error |
| `( expression )` | grouping, inside an expression |
| `$( expression )` | grouping that starts an expression in a value position |
| a comprehension, `[for …]` or `{for …}` | §0006.2.4 |

Function names and value names are separate namespaces. `$upper` is the value bound to `upper`, if any; `$upper(x)` calls the function `upper`. A parameter named `len` therefore does not hide the built-in `len`, and adding a built-in in a later version cannot break a template that uses the same name for a value.

### 0006.2.3 Operators

From loosest to tightest binding:

| Level | Operators | Operands | Result |
| --- | --- | --- | --- |
| 1 | `a or b` | `bool` | `bool`; `b` is evaluated only if `a` is `false` |
| 2 | `a and b` | `bool` | `bool`; `b` is evaluated only if `a` is `true` |
| 3 | `not a` | `bool` | `bool` |
| 4 | `a == b`, `a != b` | any | `bool`, by §2.12 equality |
| 4 | `a < b`, `a <= b`, `a > b`, `a >= b` | two values of the same **ordered** kind (below) | `bool` |
| 5 | `a + b`, `a - b` | numbers of the same kind; time (below) | as below |
| 6 | `a * b` | numbers of the same kind; `duration * int` | as below |

- **Operators are words surrounded by whitespace.** `$x-1` is a reference to a value named `x-1`, because identifiers contain `-` (Appendix A); `$x - 1` subtracts. `a<b` is not a comparison. This is required, not a style rule, and it means no existing name changes meaning.
- Comparison operators do not chain: `$a < $b < $c` is an error. Write `$a < $b and $b < $c`.
- There is no unary minus. Negative literals are numbers (`-1`); `0 - $x` negates.
- There is no `/`: `$a/2` would be ambiguous with rational literals such as `1/2` (§4.5). Integer division is `div` and `mod` (§0006.5.4).
- There is no string `+`. Interpolation and `join` build strings, and `concat` joins lists, so `+` never has to guess what its operands are.
- `and`, `or` and `not` require `bool` operands. There is still no truthiness (§9.3).

**Ordered kinds.** `<`, `<=`, `>`, `>=`, `sort`, `min` and `max` order:

- integers, decimals, rationals and floats numerically, each kind only with itself; comparing a NaN is an error;
- strings by Unicode code point (which is also UTF-8 byte order);
- timestamps by instant, durations by length;
- `false` before `true`.

Any other pair, including two values of different kinds and any container, is an error. This is deliberately not the canonical order of §2.12, which §2.12 itself says is not a numeric order.

**Arithmetic.**

| Operands | `+` | `-` | `*` |
| --- | --- | --- | --- |
| `int`, `int` | sum | difference | product |
| `decimal`, `decimal` | exact sum | exact difference | exact product |
| `rational`, `rational` | exact, in lowest terms | exact | exact |
| `float`, `float` | IEEE 754 binary64, round to nearest, ties to even | same | same |
| `timestamp`, `duration` | a later timestamp | an earlier timestamp | — |
| `timestamp`, `timestamp` | — | the `duration` between them | — |
| `duration`, `duration` | sum | difference | — |
| `duration`, `int` | — | — | a scaled `duration` |

Every other combination is an error: there is no implicit conversion between numeric kinds (§2.5). The rules that make results portable:

- An `int` result outside [−2^63, 2^64 − 1], the range every implementation must support (§2.1), is an error, even if the implementation could hold it. Otherwise one renderer would produce a value that another cannot.
- A `decimal` result with more than 38 significant digits, or an exponent outside the 32-bit range, is an error (§2.3). A `rational` result whose numerator or denominator does not fit in 64 bits (signed numerator) is an error (§2.4).
- Float operations MUST NOT be fused or reordered (no fused multiply-add, no extended precision). An overflow gives ±∞ and an invalid operation gives NaN, as IEEE 754 defines; both are values (§2.2), and they are rejected later only if a schema rejects them.
- A `timestamp` result outside the years 0001–9999, or a `duration` beyond ±(2^63 − 1) seconds, is an error (§2.6, §2.7).

### 0006.2.4 Comprehensions

A comprehension builds a list or a record by iterating over an existing value, the expression form of `@for`:

```
[for x in SOURCE: VALUE]
[for i, x in SOURCE if CONDITION: VALUE]
{for x in SOURCE: KEY: VALUE}
{for k, v in SOURCE if CONDITION: KEY: VALUE}
```

- `SOURCE`, the loop variables and the iteration order are those of `@for` (§0006.6).
- `if CONDITION` filters; the condition must be a `bool`.
- The list form evaluates `VALUE` once per element that passes the filter, in order.
- The record form produces one field per element. `KEY` must evaluate to a string; a duplicate key is an error, as it is for `@for` (§9.3).
- Inside brackets, `[for` and `{for` followed by whitespace begin a comprehension. A list literal cannot start that way today (`[for x]` is not valid flow syntax, because flow items are separated by commas), so no existing value changes meaning.

```
names: $([for s in $services if $s.enabled: $s.name])
ports: $({for s in $services: $s.name: $s.port})
```

---

## 0006.3 User functions: `@def`

### 0006.3.1 Syntax

A template MAY define functions in its header, among its `@let` bindings:

```
@let registry = "ghcr.io/example"

@def dns_label(s: string): string = $trim_suffix($slice($lower($replace($s, "_", "-")), 0, 63), "-")

@def image(name: string, tag: string = latest): string = "${registry}/${name}:${tag}"

@def labels(component: string):          # block form: the body is a template body
  "app.kubernetes.io/name": $chart
  "app.kubernetes.io/instance": $release
  "app.kubernetes.io/component": $component
  @if $component == web:
    tier: frontend
```

- `@def NAME(PARAMS)[: RESULT] = EXPRESSION` is the flow form. The block form omits `= EXPRESSION`, and its body is indented two spaces on the following lines; it is evaluated like a template body, with `@if`, `@for` and spreads.
- `NAME` is an identifier. Defining the same name twice is an error.
- Each parameter is `name: TYPE [= DEFAULT]`, with `TYPE` in schema syntax (§6.1), as for `@param`. Parameters with defaults come last. At least one parameter is required: a function without parameters is a `@let`.
- `RESULT` is optional and defaults to `any`.

### 0006.3.2 Semantics

- **Calls** are positional: `$image(api)`, `$image(api, v2)`. Too many or too few arguments is an error.
- **Arguments are checked, not converted.** Each argument is validated against its parameter type (§6.4), and a mismatch is an error. Resolution (§6.3) is not applied: it exists to read text, and arguments are already values. Passing the string `"80"` to a `u16` parameter is an error, not a conversion. (`@param` still resolves, because its arguments do come from text, §9.4.)
- **The result** is validated against `RESULT`.
- **Scope is lexical.** The body sees its own parameters, the template's `@param`s and imports, and the `@let` and `@def` bindings **above** it. It does not see the caller's loop variables or the `@let`s below it. Parameters may shadow template-level names.
- **No recursion.** A body may call built-ins and functions defined above it, and nothing else. A call to the function itself, or to one defined later, is an error, reported when the template is loaded, before any argument is bound. The call graph is therefore a DAG by construction, and no depth limit or cycle detection is needed.
- **Functions are not values.** A function cannot be passed, returned, stored or referenced without calling it. There are no lambdas, so `map` and `filter` are comprehensions (§0006.2.4).
- **Shadowing a built-in.** A `@def` may have the name of a built-in, and calls in the template then reach the `@def`. This keeps adding a built-in in a later minor version compatible (§13.1). It is linted (§0006.8).
- **Imports** do not export functions in this proposal. An imported template is rendered to a value (§9.4) and its `@def`s are not visible. See §0006.11 item 1.

### 0006.3.3 Why this cannot loop

The call graph is acyclic because a function can only reach definitions above it. Loops and comprehensions iterate over values that exist before the loop starts, and nothing can extend a value while it is being iterated. Every expression therefore terminates.

What remains is cost. A chain of functions that each call the previous one twice does 2^n calls for n definitions, and nested comprehensions over a list of length m do m^k work at depth k. Both are finite, both are bounded by the template's text and its arguments, and both are caught by the step budget (§0006.7).

---

## 0006.4 Built-in functions: common rules

These rules apply to every function in §0006.5.

- **Signatures** are written in schema type syntax (§6.1). `T` and `K`, `V` stand for "the same type in every position of this signature" and are notation, not schema syntax. `number` means `int | decimal | rational | float`; `scalar` means the scalars that interpolation accepts (§9.3).
- **No implicit conversion.** An argument of the wrong kind is an error. The only conversions are the ones the conversion functions (§0006.5.5) perform when called.
- **Strings are sequences of Unicode scalar values.** Lengths, indices and slices count scalar values. No function looks at grapheme clusters, normalises (§2.8) or depends on a locale.
- **Unicode version.** Every function that needs Unicode character data (`lower`, `upper`, `trim`) uses **Unicode 17.0.0** in template language 0.2. Code points unassigned in that version have no case mapping and are not white space. A later template language version MAY move to a later Unicode version; a renderer MUST use the version that the declared template language version names, so that one template renders identically everywhere.
- **Purity.** A built-in is a function of its arguments. No built-in reads the clock, randomness, the environment, files or the network, or depends on the platform. Two conforming renderers given the same template, arguments and imports produce values with the same revision (§2.13).
- **Errors.** A built-in either returns a value or fails the render with an error that names the function and the argument. There is no way to catch an error. The expected "absent" cases have functions of their own (`default`, `get`, `contains`), so errors are left for mistakes.
- **Cost.** Every call costs steps (§0006.7).

## 0006.5 The standard library

Forty functions in six groups. Each is in the library because templates that generate configuration need it often, and because it has one portable meaning. §0006.5.7 lists what is left out and why.

### 0006.5.1 Strings

| Function | Result | Semantics |
| --- | --- | --- |
| `lower(s: string)` | `string` | Full default lowercase mapping (Unicode §3.13, `toLowercase`): `UnicodeData.txt` plus the unconditional mappings of `SpecialCasing.txt`, plus the `Final_Sigma` condition. No language-specific mappings (Turkish, Azeri, Lithuanian). `lower("ΣΑΣ")` = `"σας"`, `lower("İ")` = `"i̇"` (`i` + U+0307) |
| `upper(s: string)` | `string` | Full default uppercase mapping (`toUppercase`), same sources. The result may be longer: `upper("straße")` = `"STRASSE"` |
| `trim(s: string)` | `string` | Removes leading and trailing code points with the Unicode `White_Space` property |
| `trim_prefix(s: string, p: string)` | `string` | `s` without `p` at its start, if it starts with `p`; otherwise `s`. Removes at most one occurrence |
| `trim_suffix(s: string, p: string)` | `string` | the same at the end |
| `starts_with(s: string, p: string)` | `bool` | whether `s` begins with `p` (scalar by scalar). Every string starts with `""` |
| `ends_with(s: string, p: string)` | `bool` | whether `s` ends with `p` |
| `replace(s: string, old: string, new: string)` | `string` | Replaces every non-overlapping occurrence of `old`, scanning left to right. `old` = `""` is an error |
| `split(s: string, sep: string)` | `list<string>` | The parts between occurrences of `sep`, scanning left to right; n occurrences give n + 1 parts. `split("", ",")` = `[""]`, `split("a,,b", ",")` = `[a, "", b]`. `sep` = `""` is an error |
| `join(xs: list<scalar> \| tuple \| set<scalar>, sep: string)` | `string` | The elements' interpolation text (§9.3) separated by `sep`. Sets are joined in canonical order. A `null` or container element is an error |
| `slice(s: string, start: int, end?: int)` | `string` | The scalar values from index `start` up to, not including, `end` (default: the length). Indices are clamped to the length; `start > end` gives `""`; a negative index is an error. `slice($name, 0, 63)` truncates |
| `matches(s: string, pattern: string)` | `bool` | Whether the **whole** of `s` matches `pattern`, an I-Regexp (RFC 9485) exactly as for `@pattern` (§6.1), with the same linear-time requirement (§12). An invalid pattern is an error |

Also applying to strings: `len`, `contains`, `string` (below).

`lower` and `upper` are the only functions that need tables. The full mappings were chosen over the simple (one-to-one) mappings because they are what Rust, Java, JavaScript, Python and ICU produce by default, so the expected answer for `straße` is the one most implementations give without extra work. Language-specific mappings are excluded because they need a locale, and a locale is ambient state.

### 0006.5.2 Values in general

| Function | Result | Semantics |
| --- | --- | --- |
| `len(x: string \| bytes \| list<any> \| tuple \| set<any> \| record \| map<any, any>)` | `int` | scalar values, octets, elements, fields or entries |
| `contains(x, y)` | `bool` | `string`, `string`: `y` is a substring of `x` (`""` is in every string). `list`, `tuple`, `set`: an element equals `y` (§2.12). `record`: `y` is a string and a field with that key is present, even if its value is `null`. `map`: `y` is a key |
| `get(x, key, fallback)` | any | `record`: the field `key` (a string), `map`: the value for `key`, `list` or `tuple`: the element at index `key` (an `int`, 0-based, negative is an error). `fallback` if the field, key or index is absent. A present `null` is returned as `null` (§2.10) |
| `default(x, fallback)` | any | `x`, unless `x` is `null`, then `fallback`. Optional parameters bind `null` when not given (§9.4), so this is the usual way to fill them |
| `kind(x: any)` | `string` | the kind name of §2: `null`, `bool`, `int`, …, `variant` |

Paths (§7.1) already reach into values whose shape is known; `get` is for keys that are computed or may be absent, and for keys that are not identifiers.

### 0006.5.3 Collections

| Function | Result | Semantics |
| --- | --- | --- |
| `keys(x: record \| map<K, any>)` | `list<string>` or `list<K>` | the keys, in iteration order (§0006.6) |
| `values(x: record \| map<any, V>)` | `list<V>` | the values, in the same order as `keys` |
| `sort(xs: list<T> \| tuple \| set<T>)` | `list<T>` | ascending, by the order of §0006.2.3. All elements must be of the same ordered kind; otherwise it is an error. Equal elements are identical values, so stability does not arise |
| `unique(xs: list<T> \| tuple)` | `list<T>` | the elements without later duplicates (§2.12 equality), in first-occurrence order |
| `concat(xs: list<T>, …)` | `list<T>` | the lists one after the other; one or more arguments |
| `merge(a: record, b: record, …)` | `record` | the fields of all records; later arguments win. Shallow, like a spread (§9.3). Also accepts maps, all of one kind |

`len`, `contains`, `get`, `slice` (on lists: `slice(xs: list<T>, start: int, end?: int)`, same rules as for strings) and `join` also apply to collections. Filtering and mapping are comprehensions (§0006.2.4). There is no `range`: iteration counts come from the data, never from a number (§0006.10).

### 0006.5.4 Numbers

| Function | Result | Semantics |
| --- | --- | --- |
| `min(a, b, …)`, `min(xs)` | `T` | the least of two or more arguments, or of the elements of one non-empty list, tuple or set. Ordered kinds only, all of one kind (§0006.2.3); also works on strings, timestamps and durations |
| `max(a, b, …)`, `max(xs)` | `T` | the greatest, likewise |
| `floor(x: decimal \| rational \| float)` | `int` | the greatest integer ≤ `x`. A non-finite float or a result outside the portable integer range is an error |
| `ceil(x: decimal \| rational \| float)` | `int` | the least integer ≥ `x` |
| `round(x: decimal \| rational \| float)` | `int` | the nearest integer, **ties away from zero**: `round(2.5)` = `3`, `round(-2.5)` = `-3` |
| `div(a: int, b: int)` | `int` | floored division: the greatest integer ≤ a / b. `b` = `0` is an error. `div(-7, 2)` = `-4` |
| `mod(a: int, b: int)` | `int` | `a - b * div(a, b)`: the result has the sign of `b`. `mod(-7, 2)` = `1`, which is what bucketing (`mod($i, $zones)`) needs |

Rounding ties away from zero is what people expect from "round" in configuration (and what Rust's `f64::round` does). Floored division is chosen over truncation so that `mod` is never negative for a positive divisor.

### 0006.5.5 Conversions

| Function | Accepts | Result |
| --- | --- | --- |
| `string(x)` | a scalar that interpolation accepts (§9.3) | its interpolation text: a string unchanged, everything else its canonical text (§4.10) |
| `int(x)` | an `int`; a `string` that §4.4 classifies as an `int` | `int`. `int("08")` and `int("1.0")` are errors, as their text is not an integer token. Use `floor`, `ceil`, `round` for other numbers |
| `float(x)` | an `int`, `decimal` or `rational` (rounded to nearest, ties to even); a `string` that §4.4 classifies as a `float` or `int` | `float` |
| `decimal(x)` | an `int`; a `string` in the form of a `@decimal(…)` literal (§4.8) | `decimal`. Floats are refused: their exact binary value is rarely what was meant. Write `$decimal($string($f))` to go through the shortest text |

These exist because parameters are typed and kinds never convert implicitly (§2.5). They are the explicit, named conversions a template needs when a value of one kind feeds a field of another.

### 0006.5.6 Encoding and digests

| Function | Result | Semantics |
| --- | --- | --- |
| `base64_encode(x: string \| bytes)` | `string` | standard base64 with padding (RFC 4648 §4) of the bytes, or of the UTF-8 encoding of the string |
| `base64_decode(s: string)` | `bytes` | strict decoding: standard alphabet, padding required, no white space, unused bits zero. Anything else is an error |
| `sha256(x: string \| bytes)` | `string` | the SHA-256 digest of the bytes or of the string's UTF-8 encoding, as 64 lowercase hexadecimal digits |
| `revision(x: any)` | `string` | the revision of `x` (§2.13): `sha256:` + the digest of its canonical binary encoding |
| `to_json(x: any)` | `string` | the JSON text of `x`: the NOVA → JSON mapping of §11.1, serialized by RFC 8785 (JSON Canonicalization Scheme). An `int` beyond ±2^53 and a non-finite float are errors instead of mappings, because RFC 8785 cannot represent them exactly |
| `to_nova(x: any)` | `string` | the canonical text of `x` (§4.10), without a trailing newline after a flow value |

`revision` is the NOVA way to write Helm's `checksum/config` annotation: it hashes the configuration **value**, so reformatting the config, reordering its keys or changing its comments does not restart a pod, and any change of value does. `sha256` is for the cases where an external system defines the digest over text or bytes. `to_json` and `to_nova` exist for one job: embedding a configuration file in a string field, such as a Kubernetes `ConfigMap`. They are canonical so that the embedded text, and any checksum over it, is stable.

### 0006.5.7 Left out, and why

| Function or family | Why not |
| --- | --- |
| `now`, `date`, `uuid`, `rand*`, `env`, `readFile`, `lookup` | Not functions of their arguments. A render must depend only on its template, arguments and imports (§0006.4). Values like a deployment time are parameters (`@param deployed_at: timestamp`) |
| `indent`, `nindent`, `quote`, `toYaml`, `tpl` | Text-level helpers. Templates splice values, so there is nothing to indent or quote (§9.1) |
| `title`, `capitalize`, `camelcase`, `snakecase` | Word boundaries and title case depend on language and script. A template that needs them for ASCII identifiers can split and join |
| regex `find`, `replace`, capture groups | I-Regexp (§6.1) has no captures, and adding a second, larger regex dialect brings back backtracking and the differences between engines. `matches`, `replace` and `split` cover configuration |
| `printf`, `format` | Interpolation formats strings. Width and precision formatting is locale-adjacent and grows a mini-language |
| `repeat`, `pad_start`, `pad_end` | Rarely needed for values, and the classic tool for blowing up string size |
| `range`, `until`, `seq` | Iteration counts would come from a number instead of the data. `@for i, x in $xs` gives indices |
| `sort_by`, `group_by`, `map`, `filter`, `reduce` | Need functions as values. Comprehensions cover `map` and `filter`; `sort_by` is §0006.11 item 2 |
| `abs`, `pow`, `sqrt`, `log` | `abs` is `max($x, 0 - $x)`; the others are not configuration arithmetic, and transcendental functions are not correctly rounded on every platform |
| Cryptography beyond SHA-256 (`genCA`, `bcrypt`, `htpasswd`) | Needs randomness or secrets. Generate secrets outside the template |
| `ascii_lower`, `ascii_upper` | `lower` and `upper` give the same result on ASCII. If ASCII-only output must be enforced, `matches` checks it |

---

## 0006.6 Iteration order (a fix to §9.3)

§9.3 lets `@for` iterate over records, maps and sets, but does not say in which order. Field, entry and element order is not part of these values (§2.9–§2.11). The reference implementation iterates in the order in which the input happened to store them, so two **equal** argument values can render to two **different** results, for example a list whose items come from a record of services. That breaks the expectation that rendering is a function of values, and it makes revisions of rendered output depend on how the arguments were spelled.

Proposed rule, for `@for`, comprehensions, `keys`, `values`, `join` and every other built-in that walks a collection:

| Source | Order | Index variable |
| --- | --- | --- |
| list, tuple | element order | the 0-based index (`int`) |
| record | by key, in UTF-8 byte order (the order of canonical text, §4.10) | the key (`string`) |
| map | canonical order of the keys (§2.12) | the key |
| set | canonical order of the elements (§2.12) | the 0-based position in that order (`int`) |

Author order would read more naturally, but it is not part of the value, cannot be relied on after a value passes through binary, a patch or another tool, and §2.10 only says implementations SHOULD keep it. A template that needs a specific order iterates over a list.

Canonical order is the byte order of canonical encodings (§2.12), not numeric or alphabetical order. A set of ints iterates in zigzag-varint order, so `@set[64, 63, -64]` yields `63, -64, 64`, and shorter strings come before longer ones. Where people read the result, iterate over `$sort($xs)`.

This does not change the meaning of any 0.1 template: 0.1 left the order unspecified, so no 0.1 template could rely on one, and 0.2 only defines it. It does change what a given renderer produces, and that includes templates without a version: §13.1 reads an undeclared `@template` as the newest version the renderer implements, so such templates get the defined order as soon as their renderer implements 0.2. Templates that must render byte-identically across that upgrade SHOULD declare `@template 0.1` and move to 0.2 deliberately.

---

## 0006.7 The step budget

The output budget (§9.5) bounds what a render **produces**. It does not bound work that produces nothing: `$len([for a in $xs: [for b in $xs: [for c in $xs if $c != $c: $a]]])` builds only |xs|² empty lists but runs |xs|³ iterations, and a chain of n `@def`s that each call the previous one twice does 2^n calls. A renderer MUST therefore also enforce a **step budget** (reference default: 10^7 steps). Exceeding it is an error.

So that every renderer accepts and rejects exactly the same templates, steps are counted exactly:

| Event | Steps |
| --- | --- |
| applying an operator (§0006.2.3), including each of `and`, `or`, `not` that is evaluated | 1 |
| evaluating an `@if` or `@else if` condition, or a comprehension filter | 1 (plus its operators) |
| one iteration of an `@for` or a comprehension (counted before its filter) | 1 |
| a call of a `@def` | 1 (plus the steps of its body) |
| a call of a built-in | 1, plus 1 per element, field or entry of each collection argument and of a collection result, plus 1 per started 64 bytes of the UTF-8 (or octets) of each string or bytes argument and result |

References, literals and interpolations cost no steps of their own. The output budget (§9.5) is clarified at the same time: it also counts the elements, fields and entries of every collection an expression constructs, including intermediate collections (a comprehension inside `len`) that never reach the output, so that it also bounds memory. A scalar result of an operator or a call is not a node until it is placed in a collection or in the output. This keeps the two budgets apart: a render that builds no collections, such as a chain of `@def`s over integers, can only exceed the step budget. Short-circuited operands are not evaluated and cost nothing. The budget is per render, including the rendering of imports.

The limit is a safety net, not a design element: ordinary templates use a few thousand steps. 10^7 lets a render take at most a fraction of a second in the reference implementation. A host MAY lower or raise the budget, like the output budget.

A checker can also bound the steps of a template **statically**, without its arguments, as a polynomial in the sizes of its parameters, because loops only iterate over existing values and the call graph is a DAG. `nvf check` could report that bound; this proposal does not require it.

---

## 0006.8 Typing and static checks

Template parameters are typed (§9.2), `@def` parameters and results are typed, and every built-in has a signature. A checker can therefore infer a type for every expression and check, before any rendering:

- that every call has the right number of arguments and argument types compatible with the signature;
- that every condition and filter is a `bool`;
- that every interpolation is a scalar;
- that operators get operands of matching kinds;
- that every reference and call names something defined above it;
- given the target schema (§9.4), that the rendered value can have the shape the schema requires, where the types involved are not `any`.

Renderers MUST check all of these dynamically and report a failure as an error. `nvf check` (and the language server) SHOULD check them statically. Because the language has no recursion and no unbounded iteration, these checks are decidable; a type `any` is the only thing that weakens them.

**Lints** (Appendix E):

| Rule | Level | Checks |
| --- | --- | --- |
| `shadowed-builtin` | warning | a `@def` with the name of a built-in function |
| `bare-argument` | warning | a bare word argument in an interpolation that has the name of a value in scope: `"${lower(name)}"` where `$name` exists |
| `dynamic-pattern` | hint | a `matches` pattern that is not a literal, which cannot be checked when the template is loaded |
| `unused-def` | hint | a `@def` that is never called |

---

## 0006.9 Example

A Kubernetes `Deployment` that uses most of the proposal. It renders to a plain value, which `nvf render … --to yaml` writes as YAML.

```
@template 0.2
@param release: string
@param chart: string @pattern("[a-z0-9-]+")
@param replicas: u16 @range(1..50) = 2
@param ports: list<u16>
@param config: AppConfig                    # a record type from the host's schema
@param log_level?: string

@def dns_label(s: string): string = $trim_suffix($slice($lower($replace($s, "_", "-")), 0, 63), "-")

@let name = $dns_label("${release}-${chart}")

@def labels(component: string):
  "app.kubernetes.io/name": $chart
  "app.kubernetes.io/instance": $release
  "app.kubernetes.io/component": $component

metadata:
  name: $name
  labels: $labels(web)
  annotations:
    "checksum/config": $revision($config)   # restart only when the config value changes
spec:
  replicas: $replicas
  selector:
    matchLabels: $labels(web)
  template:
    metadata:
      labels: $labels(web)
    spec:
      containers:
        - name: web
          image: "ghcr.io/example/${chart}:${config.version}"
          args:
            - "--log-level=${default($log_level, info)}"
            - "--features=${join($sort($config.features), ",")}"
          ports: $([for p in $sort($unique($ports)): {containerPort: $p, name: "http-${p}"}])
          env:
            @for k, v in $config.env:
              - name: $upper($replace($k, "-", "_"))
                value: $string($v)
  @if $replicas > 1:
    strategy:
      rollingUpdate: {maxUnavailable: $div($replicas, 2)}
```

Compared with the Helm chart this replaces, there is no `_helpers.tpl` text, no `trunc 63 | trimSuffix "-"` repeated in every file, no `nindent`, no `quote`, and every value that reaches the output has a kind.

---

## 0006.10 Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Make the language Turing complete** (recursion or `while`), with a time limit | Loses termination by construction, static type and cost checks, and portable limits (§0006.1.2). Every real use case found in Helm charts fits within bounded iteration |
| **Recursion with a depth limit** | Still exponential, still needs fuel to bound, and encourages writing algorithms in configuration. The DAG rule costs nothing and makes recursion unwritable |
| **Lambdas and `map`/`filter`/`reduce`** | Functions as values make the type system higher-order and `reduce` makes accumulation over arbitrary state possible. Comprehensions cover `map` and `filter` with plain syntax |
| **`range(n)` / `@for i in 0..n`** | Makes the number of iterations depend on a number instead of the data, so a single parameter can request 10^18 iterations. Lists of the right length can be passed as parameters |
| **Bare calls (`lower(x)`) in value positions** | `lower(x)` is a plain string today in every NOVA document; giving it a second meaning in templates would silently change data that was meant literally. `$` keeps template code visible (§9.7) |
| **Pipes (`$name \| trim \| lower`) or methods (`$name.lower()`)** | A second way to write every call. `\|` is the union operator in types (§6.1), which appear in the same template header, and `.` is the path separator (§7.1), so `$x.lower` would be a field |
| **String `+`** | Overloads `+` across kinds that never convert (§2.5). Interpolation already builds strings |
| **`/` for division** | Collides with the rational literal (`1/2`, §4.5) |
| **Simple (1:1) case mapping** | Differs from what most standard libraries return by default (`straße` → `STRASSE`), so implementations would have to build special tables to be conformant |
| **Locale parameter for case mapping** | Ambient or per-call locale data varies between platforms and versions; configuration identifiers should not depend on it |
| **`try`/`catch` or error values** | Errors are mistakes; recoverable cases have `default`, `get` and `contains`. Catching errors would make "it rendered" mean less |
| **Sprig compatibility** | Sprig's ~200 functions include text helpers, clocks, randomness and cryptography, and their semantics are those of Go's library. A small, specified set is easier to implement identically |
| **Author order for record iteration** | Not part of the value (§2.10); equal arguments could render to unequal results (§0006.6) |

---

## 0006.11 Open questions and future work

1. **Exporting functions from imports.** Shared helpers (Helm's `_helpers.tpl`) would want `@import "helpers.tpl.nova" as h` and `$h.dns_label(x)`. Imports already form a DAG (§9.5 rejects cycles), so this keeps the call graph acyclic. It needs a syntax that does not collide with paths (`$h.dns_label` is a field today) and a rule for which `@def`s are public.
2. **`sort_by(xs, path)`**, sorting records by a field named by a path (§7.1), without functions as values. Common for deterministic Kubernetes lists.
3. **Map comprehensions** (`@map{for …: K => V}`), when a template needs non-string keys.
4. **A static cost report** (`nvf check --cost`), giving the polynomial bound of §0006.7.
5. **Optional chaining.** `$get($x, a, null)` covers one level; a path operator for "absent or null stops here" (`$x?.a?.b`) would be shorter, but `?` already marks optional and nullable types (§6.1).
6. **Unicode updates.** Which template language versions move to which Unicode version, and whether a template may declare an older one.
7. **Site copy.** If this is merged, the `/vs/helm/` page on novafile.dev (rows "Termination" and "Functions", and "When to stay with Helm") must change, since templates then compute.

---

## 0006.12 Conformance cases

New directories under `conformance/template/`, each with `template.nova`, `args.nova` and `expect.json`:

| Case | Shows | Expected |
| --- | --- | --- |
| `case-mapping` | `upper("straße")`, `lower("ΣΑΣ")`, `lower("İ")`, `upper("ǆ")` | `STRASSE`, `σας`, `i̇`, `Ǆ` |
| `trim-unicode` | `trim("\u{A0}\u{2003}x\u{3000}")`, and `trim("\u{200B}x\u{200B}")`, where U+200B is not `White_Space` | `"x"`, and `"\u{200B}x\u{200B}"` unchanged |
| `split-join` | `split("a,,b", ",")`, `split("", ",")`, `join` of ints and a timestamp | `[a, "", b]`, `[""]`, canonical texts |
| `replace-empty` | `replace($s, "", x)` | error |
| `slice-truncate` | a 70-character name cut to 63, then `trim_suffix` of `-` | 62 characters |
| `record-iteration-order` | `@for k, v in` a record written as `{b: 1, a: 2, "B": 3}` | items in the order `B`, `a`, `b` |
| `set-iteration-order` | `[for x in @set["b", "a", "c"]: $x]` | `[a, b, c]` (canonical order) |
| `comprehension-filter` | list and record comprehensions with `if` | the filtered values |
| `comprehension-duplicate-key` | a record comprehension producing a key twice | error |
| `operator-whitespace` | `$x-1` with a parameter `x-1`, and `$x - 1` | the parameter's value, and the difference |
| `mixed-kind-arithmetic` | `$i + 1.0` with `i: int` | error |
| `int-portable-range` | `$(18446744073709551615 + 1)` | error |
| `floor-mod` | `div(-7, 2)`, `mod(-7, 2)`, `round(-2.5)` | `-4`, `1`, `-3` |
| `compare-kinds` | `1 < "2"` | error |
| `def-block` | a block `@def` with `@if` in its body, called twice with different arguments | two records |
| `def-forward-call` | a `@def` calling one defined below it | error at load time |
| `def-self-call` | a `@def` calling itself | error at load time |
| `def-argument-no-conversion` | passing `"80"` to a `u16` parameter | error |
| `def-shadows-builtin` | a `@def lower(s: string)` | the `@def` is called |
| `step-budget` | 30 `@def`s, each calling the previous twice | error: step budget |
| `nested-comprehension-budget` | three nested comprehensions over 300 elements, only the innermost with a filter that rejects everything: 90,300 nodes (under the output budget) but more than 2.7 × 10^7 steps | error: step budget |
| `intermediate-output-budget` | `len` of a comprehension that builds 2 × 10^6 elements | error: output budget |
| `interpolation-call` | `"${lower($name)}-svc"` and `"${name}"` | both interpolated |
| `revision-checksum` | `revision` of two equal records written in different key order | equal strings |
| `to-json-canonical` | `to_json({b: 1, a: [true, null]})` | `{"a":[true,null],"b":1}` |
| `to-json-big-int` | `to_json(9007199254740993)` | error |
| `base64-strict` | `base64_decode("aGk")` (no padding) | error |
| `matches-whole` | `matches("abc", "b")`, `matches("abc", "a.c")` | `false`, `true` |
| `no-truthiness-functions` | `@if $len($xs):` | error: condition is not a `bool` |

---

## 0006.13 Normative text

The proposed changes to SPEC.md, in summary:

- **§9.1**, last sentence: "The template language is **total**: every render terminates, and its output and the work it does are bounded. It is deliberately not Turing complete (§9.3b)."
- **§9.2**: add `@def` to the header example and the list of declarations; `@template 0.2`.
- **§9.3**, **References** and **Interpolation**: as §0006.2.1 (interpolation content is an expression with an implied leading `$`). **Conditions**: "a condition is an expression (§9.3a) that MUST evaluate to a `bool`". **Loops**: the source is an expression, and the iteration order is §0006.6.
- **New §9.3a Expressions**: §0006.2.
- **New §9.3b Functions**: §0006.3 and §0006.4.
- **New §9.3c Standard library**: the tables of §0006.5.1–§0006.5.6.
- **§9.4** step 3: "`@let` and `@def` declarations are processed in order; each may use parameters, imports and earlier declarations. Rebinding a name is an error. A `@def` body is checked for calls to itself or to later definitions before evaluation starts."
- **§9.5**: replace "no user-defined functions, no recursion, no arithmetic" with "no recursion (a function can call only built-ins and functions defined above it), no functions as values, no I/O other than host-mediated imports, and iteration only over existing values". Add the step budget of §0006.7 as a third limit.
- **§9.7**, "Total": "Templates have no recursion and no unbounded iteration, have a bounded output and a bounded amount of work, and terminate by construction."
- **§12**, Resource limits: "…and template output and evaluation steps (§9.5)". New bullet: "**Template functions** have no access to time, randomness, the environment, files or the network; `matches` is subject to the pattern rule above."
- **§13.1**: the template language becomes 0.2. The rule "minor versions may only *add* syntax" gets an exception while the major version is 0, which is already why minor versions must match exactly then: "While the major version is 0, a minor version MAY make existing syntax invalid, provided that a document using it fails to load rather than changing its value." The interpolation change of §0006.2.1 is the only such case in 0.2. **§13**, Template renderer: "§9, including the output and step budgets, import restrictions, and the standard library with Unicode 17.0.0 data".
- **Appendix A**: replace `cond`/`unary` with the expression grammar below, and add `@def` to the directives.
- **Appendix E**: the lints of §0006.8.

```
expr        = or
or          = and (WS "or" WS and)*
and         = not (WS "and" WS not)*
not         = "not" WS not | cmp
cmp         = sum [WS ("==" | "!=" | "<" | "<=" | ">" | ">=") WS sum]
sum         = prod (WS ("+" | "-") WS prod)*
prod        = atom (WS "*" WS atom)*
atom        = flow-value                                 ; literals; may contain expr operands
            | "$" identifier "(" [expr ("," expr)* [","]] ")"   ; call
            | "$" path                                   ; reference
            | "$(" expr ")" | "(" expr ")"
            | "[for" WS for-head ":" WS expr "]"
            | "{for" WS for-head ":" WS expr ":" WS expr "}"
for-head    = [identifier "," WS] identifier WS "in" WS expr [WS "if" WS expr]
interp      = "${" (identifier-led-expr | expr) "}"      ; a leading identifier implies "$"
value-expr  = "$" …                                      ; an expr beginning with "$" in a value position; in flow context it
                                                         ; ends at "," or a closing bracket of the enclosing depth only
def         = "@def" SP identifier "(" param ("," param)* ")" [":" SP type] (SP "=" SP expr NL | NL body(2))
param       = identifier ":" SP type [SP "=" SP expr]
```
