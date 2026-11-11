# Querying the typed API from inside the server

`resolve_control api_truth` answers *what is broken*. Nothing answered *what
exists*. PR #205 landed Blackmagic's `DaVinciResolveScript.pyi` in
`docs/reference/`, and `scripts/audit_typed_api.py` can turn it into a full
inventory — but only from a shell. An agent talking to this server had no way
to ask what the native API contains.

Blackmagic's own MCP exposes `search_scripting_api` for this. These are the
equivalent, with one addition that matters more here.

## The addition: coverage, not just existence

Every result carries `referenced_in_this_server` and the source files that
reference it. That turns a lookup into a parity check — *does the native API
have it, and do we wrap it?* — which is the question the whole 21.1 audit was
built to answer, and it was previously only answerable by grepping.

The flag counts **executable syntax only**: attribute access, calls, and
`getattr(obj, "Name")`. A method named in a docstring or a comment is not
coverage. Treating prose as coverage is the specific mistake this repo's audits
exist to avoid, so the flag is built the same way `scripts/audit_typed_api.py`
builds its source references.

## Actions and tools

Compound `resolve_control`, none of which need a Resolve connection:

- `search_api(pattern, kind?, limit?)` — case-insensitive regex over
  class-qualified method names, signatures, TypedDict names, field names and
  descriptions. `kind` is `all`, `methods` or `options`. Results are capped and
  the response declares `truncated` rather than silently cutting.
- `describe_api(symbol)` — one `Class.Method`, an unambiguous bare method name,
  or a TypedDict name. An ambiguous bare name lists the candidates instead of
  guessing.
- `api_surface()` — counts and the object list.

All three take `source` (v5.1.0, #356): `auto` (the default) reads the stub the
installed Resolve writes next to its scripting API and falls back to the copy
shipped in `docs/reference`; `shipped` always reads the shipped copy;
`installed` refuses instead of falling back. Every reply carries `stub` (the
path that answered) and `stub_source` (`installed` or `shipped`).

Granular twins: `search_resolve_api`, `describe_resolve_api`,
`get_resolve_api_surface`. Tool count 384 → 387. The granular tools carry the read-only annotation, since
for the granular server the MCP annotation is the signal a client reads.

## Self-consistency

On the shipped stub the parser reports **410 methods, 46 TypedDicts, 513
fields**, independently matching the inventory published in
`resolve-211-typed-api.md` and the disposition ledgers built during the 21.1
audit. That agreement is asserted in `tests/test_typed_api_search.py` with
`source='shipped'`, so a stub refresh that changes the surface will fail the
suite rather than drift quietly, and the assertion does not depend on which
Resolve is installed on the test machine.

## Scope

None of this queries a running Resolve; it parses a stub file, and it reports a
missing stub rather than guessing. With the default `auto`, a machine whose
Resolve installs a stub answers from that build. The contributor of #356
measured Studio 21.2.0.6 on Windows at 530 methods against the shipped 410. A
Resolve that installs no stub, such as 19.x, falls back to the shipped copy,
which describes 21.1.0.14. Results can therefore differ between machines;
`stub_source` says which inventory answered, and `source='shipped'` gives the
pinned one. Refreshing the shipped stub is the existing documented process in
`resolve-211-typed-api.md`.
