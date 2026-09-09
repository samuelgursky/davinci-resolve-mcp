# Native DCTL validation in Resolve 21.1

Compound `dctl validate_native` and granular `validate_dctl_native` accept a
`source` string and call Resolve.ValidateDCTL. They return `valid`, `diagnostic`
and `checker: resolve_native`. The source is passed unchanged, including its
line layout. Native None means valid; a native string means invalid and is
returned verbatim, including whitespace. An unexpected native result type is a
protocol error, not a claim that the shader validated.

The existing `dctl validate` remains the static offline checker. Native validation
requires running Resolve 21.1 and a callable ValidateDCTL method. It does not
install a DCTL, encrypt it, apply a grade or render the shader. A successful
validation is not rendered-output evidence. The granular tool is read-only and
the compound action is explicitly classified as non-destructive.

## Contributor validation

Contributor-validated on macOS Studio 21.1.0.14 against the official MCP and both
actual community interfaces. The multiline identity fixture returns None. The
same function on one line returns `DCTL Error: main DCTL function does not have
return value.` Invalid source returns `cannot find main DCTL function.` Both
wrappers preserve these diagnostics exactly. The source-layout limitation is
already in api_truth; this wrapper exposes it honestly rather than reformatting
user code to hide it.

`python tests/live_resolve211_dctl.py` compares raw/native and both wrapper
results for all three fixtures. It neither changes projects nor installs files.
Unit tests also cover verbatim CRLF/Unicode source and diagnostic handling,
invalid inputs, missing methods, unexpected native result types, read-only risk
classification and preservation of the static checker route. Encryption and
actual GPU execution remain separate work.
