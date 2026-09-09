# Native Resolve 21.1 DCTL encryption

Compound `dctl encrypt_native` and granular `encrypt_dctl_native` accept
`input_path`, `output_path` and optional `expiry`. Input must be an existing .dctl;
output must be a new .dctle. Existing destinations, including dangling symlinks,
are refused. The source is never modified by the wrapper.

The native Name and OutputFolder options are derived from an isolated staging
file, then the completed file is published to the requested output path. This
avoids native filename surprises: Resolve appends .dctle even when Name already
ends with that suffix. Expiry null/omission means no expiry. Empty string is
normalized to null because native empty-string expiry returned false in the
contributor fixture while null succeeded. Other strings pass through as native
ISO 8601 expiry requests; native failure is preserved.

Resolve-facing staging uses the existing safe-directory helper. A successful
native return must be accompanied by a non-empty regular encrypted file. An
atomic no-replace hard link publishes it; filesystems without that support use
exclusive file creation and copy. A failed copy removes only the new partial
output. An output appearing during encryption is not overwritten. New files
use owner-only permissions where the platform supports them. The result reports
actual path, byte length and SHA-256, not a guessed native filename.

The method has a 21.1 floor. The dctl tool has the destructive-action hook, and
encrypt_native is registered/rated LOW because it only creates new output and
never replaces existing content. Explicit compound dry runs refuse before the
handler. The granular tool declares a write. No DCTL is installed or applied by
this operation.

## Contributor evidence and limits

Contributor-validated on macOS Studio 21.1.0.14 via official MCP probes and both
actual community wrappers, using a synthetic multiline identity shader. Native
omitted/null expiry and a future date succeeded; empty string returned false in
the isolated probe. Both wrappers created 2032-byte files in the tested runs,
returned matching file hashes/sizes, left source bytes unchanged and refused a
repeat export without changing the destination. These byte lengths are observed,
not format requirements. Ciphertext equality across separate encryptions is not
assumed.

Tests exercise output races, missing native output, native false, cross-volume
fallback, failed-copy cleanup, dangling symlinks, bad arguments and write gates.
This is encryption/export evidence, not shader application or rendered-image
acceptance, and not a security assessment of Blackmagic's encryption scheme.

`tests/live_resolve211_encryption.py SOURCE_DCTL OUTPUT_DIR` uses a synthetic
identity source and a fresh output directory. It does not install the results or
change a project. Never substitute someone else's shader without authorization.
