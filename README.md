# NOVA specification

**NOVA — Notation for Objects, Values & Agents** — is one precise semantic model with several interchangeable representations: human text, compact text for LLMs (with tables), a canonical binary encoding, conditional patches and queries for agents, schemas with SemVer-checked evolution, and a total, value-level template language.

This repository is the language-neutral home of the format:

| Path | Contents |
| --- | --- |
| [`SPEC.md`](SPEC.md) | The specification (draft 0.1) |
| [`proposals/`](proposals/) | Design proposals that are not normative yet (tensors; streaming, massive documents and a TUI; labels and annotations) |
| [`meta/nova-schema.novs`](meta/nova-schema.novs) | The meta-schema `nova-schema@0.2.0`, which describes schema descriptors (§6.8) |
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

| Component | License |
| --- | --- |
| Specification ([`SPEC.md`](SPEC.md)) and [`proposals/`](proposals/) | [Apache-2.0](LICENSE) |
| Meta-schema ([`meta/`](meta/)) | [Apache-2.0](LICENSE) |
| Grammar definitions (Appendix A; [tree-sitter-nova](https://github.com/novafile/tree-sitter-nova); the TextMate grammars in [vscode-novafile](https://github.com/novafile/vscode-novafile)) | Apache-2.0 |
| Conformance test vectors ([`conformance/`](conformance/)) | [CC0-1.0](conformance/LICENSE) |
| Examples ([`examples/`](examples/) and the code blocks in `SPEC.md` and `proposals/`) | [CC0-1.0](examples/LICENSE) |
| Parser, serializer and validator code ([novafile/nova](https://github.com/novafile/nova)) | EUPL-1.2 OR MPL-2.0 |

Third-party implementations can therefore reuse the specification, the meta-schema, the grammars and the test vectors without taking on the reference implementation's copyleft terms.

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in this work shall be licensed as above, without any additional terms or conditions.
