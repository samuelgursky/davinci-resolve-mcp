# Contributing and Project Layout

Contributor workflow, platform support, security considerations, and the repository layout.

## Contributing

We welcome contributions! The following areas especially need help:

### Help Wanted: Untested API Methods

**5 methods** (1.5%) remain untested against a live DaVinci Resolve instance. If you have access to the required infrastructure or content, we'd love a PR with test confirmation:

1. **Cloud Project Methods** (4 methods) — Need DaVinci Resolve cloud infrastructure:
   - `ProjectManager.CreateCloudProject`
   - `ProjectManager.LoadCloudProject`
   - `ProjectManager.ImportCloudProject`
   - `ProjectManager.RestoreCloudProject`

2. **HDR Analysis** (1 method) — Needs specific content:
   - `Timeline.AnalyzeDolbyVision` — needs HDR/Dolby Vision content

### How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-contribution`)
3. Run the existing test suite to ensure nothing breaks
4. Add your test results or fixes
5. Submit a pull request

### Other Contribution Ideas

- **Windows testing** — All tests were run on macOS; Windows verification welcome
- **Linux testing** — DaVinci Resolve supports Linux; test coverage needed
- **Resolve version compatibility** — Test against Resolve 18.x, 19.0, or newer versions
- **Bug reports** — If a tool returns unexpected results on your setup, file an issue
- **Documentation** — Improve examples, add tutorials, translate docs

## Platform Support

| Platform | Status | Resolve Paths Auto-Detected | Notes |
|----------|--------|----------------------------|-------|
| macOS | ✅ Tested | `/Library/Application Support/Blackmagic Design/...` | Primary development and test platform |
| Windows | ✅ Supported | `C:\ProgramData\Blackmagic Design\...` | Community-tested; installer now emits env + `PYTHONHOME` for Resolve 20.3 multi-Python setups |
| Linux | ⚠️ Experimental | `/opt/resolve/...` | Should work — testing and feedback welcome |

## Security Considerations

This MCP server controls DaVinci Resolve via its Scripting API. Some tools perform actions that are destructive or interact with the host filesystem:

| Tool | Risk | Mitigation |
|------|------|------------|
| `quit_app` / `restart_app` | Terminates the Resolve process — can cause data loss if unsaved changes exist or a render is in progress | MCP clients should require explicit user confirmation before calling these tools. Subprocess calls use hardcoded command lists (no shell injection possible). |
| `export_layout_preset` / `import_layout_preset` / `delete_layout_preset` | Read/write/delete files in the Resolve layout presets directory | Path traversal protection validates all resolved paths stay within the expected presets directory (v2.0.7+). |
| `save_project` | Creates and removes a temporary `.drp` file in the system temp directory | Path is constructed server-side with no LLM-controlled input. |

**Recommendations for MCP client developers:**
- Enable tool-call confirmation prompts for destructive tools (`quit_app`, `restart_app`, `delete_layout_preset`)
- Do not grant blanket auto-approval to all tools in this server

## Project Structure

```
davinci-resolve-mcp/
├── install.py                    # Universal installer (macOS/Windows/Linux)
├── src/
│   ├── server.py                # Compound MCP server — 32 tools (default)
│   ├── resolve_mcp_server.py    # Thin full-server entrypoint — 341 tools
│   ├── granular/                # Modular full-server implementation
│   └── utils/                   # Platform detection, Resolve connection helpers
├── tests/                       # 5-phase live API test suite + Resolve 20 delta (331/331 pass)
├── docs/
│   ├── README.md                 # Documentation index
│   ├── SKILL.md                  # AI assistant operating reference
│   ├── guides/                   # Media analysis and decision guides
│   ├── process/                  # Release and maintenance process docs
│   ├── reference/                # Resolve scripting API reference
│   ├── kernels/                  # Maintained workflow support maps
│   ├── authoring/                # Fuse/DCTL and script authoring references
│   ├── integrations/             # Resolve-hosted integration references
│   └── notes/                    # Resolve developer-package notes
└── examples/                    # MCP prompt recipes for markers, media, and timeline workflows
```
