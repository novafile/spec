# NOVA specification

**NOVA — Notation for Objects, Values & Agents** — is one precise semantic model with several interchangeable representations: human text, compact text for LLMs (with tables), a canonical binary encoding, conditional patches and queries for agents, schemas with SemVer-checked evolution, and a total, value-level template language.

This repository is the language-neutral home of the format:

| Path | Contents |
| --- | --- |
| [`SPEC.md`](SPEC.md) | The specification (draft 0.1) |
| [`proposals/`](proposals/) | Design proposals that are not normative yet (tensors; streaming, massive documents and a TUI; labels and annotations) |
| [`meta/nova-schema.novs`](meta/nova-schema.novs) | The meta-schema `nova-schema@0.1.0`, which describes schema descriptors (§6.8) |
| [`examples/`](examples/) | Example documents, a schema, a patch and a template (CC0-1.0) |
| [`conformance/`](conformance/) | The cross-implementation test suite |

## Implementations

| Project | Language | Contents |
| --- | --- | --- |
| [novafile/nova](https://github.com/novafile/nova) | Rust | Reference implementation: crates `novafile-*` (umbrella crate `novafile`), CLI `nvf`, language server `nvf-lsp` |
| [novafile/vscode-novafile](https://github.com/novafile/vscode-novafile) | TypeScript | VS Code extension: syntax highlighting and the language server client |
| [novafile/tree-sitter-nova](https://github.com/novafile/tree-sitter-nova) | tree-sitter | Grammar for Helix, Neovim, Zed and others |

An implementation that passes the conformance suite may say so; see [`conformance/README.md`](conformance/README.md).

## Changing the specification

The specification and the conformance suite change together. A pull request that changes behaviour updates `SPEC.md`, adds or updates cases under `conformance/`, and regenerates their expectations with the reference implementation (`cargo run -p novafile-conformance -- generate path/to/spec/conformance`). Larger ideas start as a document under `proposals/`.

## License

The specification, proposals, meta-schema and conformance suite are licensed under the [Apache License, Version 2.0](LICENSE) (SPDX-License-Identifier: `Apache-2.0`). Implementations of the format may use any license.

The example files in [`examples/`](examples/) are dedicated to the public domain under [CC0-1.0](examples/LICENSE) (SPDX-License-Identifier: `CC0-1.0`): copy them into your own projects without conditions.

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in this work shall be licensed as above, without any additional terms or conditions.
