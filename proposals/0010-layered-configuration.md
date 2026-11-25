# NOVA Proposal 0010: Layered configuration

| | |
| --- | --- |
| Status | Merged into SPEC.md (§6.1, §6.4, §6.5, §6.8, §11.2) on 2026-11-25. This document keeps the rationale; SPEC.md is normative. |
| Targets | §6.1 (record rules), §6.4 (partial validation), §6.5 (evolution), §6.8 (meta-schema 0.3.5), §11.2 (JSON Schema), conformance suite |
| New kinds / tags / directives | none. New record attributes `@together`, `@one_of`, `@any_of` |
| Reference implementation | `novafile-schema` (`Schema::resolve_partial`), `novafile-serde` and `novafile-facet` (`from_str_with_schema_partial`), `nvf validate --partial`, `#[derive(NovaSchema)]` (`together`, `one_of`, `any_of`, `not_null`) |
| Date | 2026-11-25 |

---

## 0010.0 Summary

A configuration is often layered: a file, then environment variables, then command-line flags, each overriding the one below key by key. Every single layer is incomplete by design. One schema should describe the configuration and check it twice:

1. **Partial validation of each layer.** Every field is optional, as in TypeScript's `Partial<T>` applied deeply. Types, conversions, closed records, `@range`, `@len`, `@pattern` and the `@schema` reference still apply, so typos and wrong shapes fail early, at the layer that has them.
2. **Strict validation of the merged value**, with the required fields and three new **record rules**:
   - `@together(a, b, …)`: all of the fields or none of them;
   - `@one_of(a, b, …)`: exactly one of them;
   - `@any_of(a, b, …)`: at least one of them.

```
record Database @one_of(url, url_file) @together(user, password):
  url?: string
  url_file?: string
  user?: string
  password?: string @secret
```

## 0010.1 Motivation

Today a layered setup forces a choice:

- **A strict schema** (required fields required) rejects a valid file, because a required key may come from the environment.
- **A loose schema** (everything optional) accepts the file, but cannot express the rules that matter for the final configuration: "this section is all or nothing", "one of `url` and `url_file`". They end up in hand-written checks after merging, and the schema no longer documents them.

With partial validation, the schema stays strict. With record rules, the cross-field rules move into the schema, where editors, `nvf validate` and JSON Schema consumers see them.

## 0010.2 Record rules (§6.1)

- A rule follows the record name on the head line, like `@open`. A record may carry several rules of each kind.
- A rule names two or more distinct fields of the record, by names without quotes, so that its argument list needs no quoting rules of its own.
- Each named field MUST be optional and MUST NOT have a default or `@key`. A required field, or one with a default, is always present after resolution: the rule would be either always true or never satisfiable. A `@key` field is required anyway.
- A field counts as **present** when the record has it and its value is not `null`. Language bindings often write an absent optional value as `null` (serde writes `None` as `null` unless the field has `skip_serializing_if`), so counting `null` as absent makes `to_value` of a merged struct check the same way as the hand-written document would.
- A broken rule is one issue at the path of the record, for example `db: @one_of(url, url_file): 2 present (url, url_file); expected exactly 1`.
- The canonical text writes rules after `@open` and before a class, in the order written. Rule order changes the fingerprint, as field order does.

## 0010.3 Partial validation (§6.4)

Partial validation changes three steps of record resolution:

- a missing field is never an error (step 4);
- no default is filled in (step 2): a default in a layer would override the value of a lower layer when the layers are merged;
- record rules are not checked (step 6).

Everything else is unchanged. A union of records takes the first member that the present fields fit, since no member can fail for a missing field; schemas that rely on required fields to pick a union member resolve such layers less precisely, but the merged value resolves exactly.

Partial validation is a mode of the validator, not of the schema. There is no `@partial` directive: a document does not decide how strictly it is checked.

## 0010.4 Evolution (§6.5)

- Adding a rule, or changing its fields, is breaking: old data may break it.
- Removing a rule is compatible: it only accepts more.

## 0010.5 Descriptor (§6.8)

`RecordDef` gains `rules?: list<RecordRule>`, with `record RecordRule: kind: RuleKind, fields: list<string>` and `enum RuleKind = together | one_of | any_of`. The meta-schema becomes `novafile.dev/meta/schema@0.3.5` and uses the new attribute itself: `record Def @one_of(record, enum, alias):` replaces a rule that §6.8 used to state in prose. Every valid 0.3.4 descriptor is a 0.3.5 descriptor, since a 0.3.4 descriptor with other than exactly one of the three was already rejected on conversion.

## 0010.6 JSON Schema (§11.2)

Each rule becomes one `allOf` entry: `dependentRequired` for `@together`, `oneOf` and `anyOf` of `{"required": [field]}` for the others. JSON Schema counts a `null` property as present, so the mapping is exact only for fields that are left out instead of written as `null`. `"x-nova-rules"` keeps the rules for the way back.

## 0010.7 Language bindings (§11.3)

The reference derive adds the container attributes `#[nova(together = "a, b")]`, `one_of` and `any_of`, which name Rust fields. It also adds the field attribute `#[nova(not_null)]`, which derives `name?: T` instead of `name?: T?` for an `Option<T>` field. The fields of a struct that only uses `Option` so that layers can be merged keep their rules, and required fields stay required.

## 0010.8 Alternatives considered

- **A merge helper in the library** that takes the layers as values and merges them in order. Merging is a few lines with `to_value` and record updates, and every application has its own precedence rules (lists replace or append, `null` deletes or not). Left out.
- **Rules as body lines** (`@one_of(a, b)` on its own line inside the record). Rules are about the record, like `@open`, and the head line keeps the field list a plain list. The head line was chosen.
- **`@xor`, `@requires(a -> b)`.** `@one_of` covers the common exclusive case, and `@together` the common dependency. A general dependency rule can come later without changing these.
- **A `Partial<T>` type operator.** It would make partial checks a property of the schema text, and a layer would need a second root type. A validator mode keeps one schema and one root.

## 0010.9 Conformance cases

- `schema/record-rules/`: valid and invalid documents for each rule, `null` counted as absent, and layers in `partial-valid/` and `partial-invalid/` (the runner resolves those partially).
- `schema-invalid/rule-*.novs`: a rule with one field, an unknown field, a required field, a field with a default.
- `schema-versions/record-rule-added`, `record-rule-removed`.

## 0010.10 Open questions

- Should a rule name fields of nested records (`@one_of(tls.cert, tls.cert_file)`)? Not needed so far; the rule can sit on the nested record.
