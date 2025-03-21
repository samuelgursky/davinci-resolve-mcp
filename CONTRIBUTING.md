# Contributing to DaVinci Resolve MCP Extension

Thank you for considering contributing to the DaVinci Resolve MCP Extension! This document provides guidelines and instructions for contributing to this project.

## Code of Conduct

Please be respectful and considerate of others when contributing to this project. We aim to foster an inclusive and welcoming community.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/your-username/davinci-resolve-mcp.git`
3. Create a branch for your changes: `git checkout -b your-feature-branch`

## Development Environment Setup

1. Ensure you have Python 3.6+ installed
2. Set up the DaVinci Resolve scripting environment as described in the README.md
3. Install the project in development mode:
   ```
   pip install -e .
   ```

## Project Structure

- `src/`: Core implementation files
- `tests/`: Test scripts for verification
- `examples/`: Example usage scripts
- `docs/`: Documentation files
- `scripts/`: Utility scripts for project maintenance

## Coding Style Guidelines

We follow these guidelines:

- Use PEP 8 style guide for Python code
- Use descriptive variable names
- Write docstrings for all functions, classes, and modules
- Include type hints where appropriate
- Use 4 spaces for indentation (not tabs)

## Testing

Before submitting a pull request, please:

1. Run the existing tests to ensure they still pass:
   ```
   python -m tests.test_timeline_functions
   python -m tests.test_project_settings
   python -m tests.test_playback_functions
   ```

2. Add tests for any new functionality

3. Verify that your changes work with both recent versions of DaVinci Resolve

## Documentation

When adding new features or changing existing ones:

1. Update docstrings and comments in the code
2. Update the [Master Feature Tracking Document](MASTER_DAVINCI_RESOLVE_MCP.md) with status information
3. Add examples for new functionality in the `examples/` directory

## Pull Request Process

1. Update the README.md and documentation with details of your changes
2. Update the [Master Feature Tracking Document](MASTER_DAVINCI_RESOLVE_MCP.md) with appropriate status indicators
3. Make sure all tests pass
4. Create a pull request against the `main` branch

## Feature Requests and Bug Reports

Please use the GitHub issue templates for feature requests and bug reports.

## Status Indicators

When implementing or modifying features, use these status indicators in the code and documentation:

- ✅ Working - Feature is implemented and tested successfully
- ⚠️ Partial - Feature is implemented but has limitations or edge cases
- ❌ Not Working - Feature is implemented but not functioning correctly
- 🔄 In Progress - Feature is currently being worked on
- 📝 Planned - Feature is planned for future implementation
- 🧪 Needs Testing - Feature is implemented but needs testing

## License

By contributing to this project, you agree that your contributions will be licensed under the project's MIT License. 