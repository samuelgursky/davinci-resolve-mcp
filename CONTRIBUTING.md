# Contributing to DaVinci Resolve MCP

Thank you for your interest in contributing to the DaVinci Resolve Media Control Protocol (MCP) framework! This document outlines the process for contributing to this project and helps ensure a smooth collaboration.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing Requirements](#testing-requirements)
- [Documentation Guidelines](#documentation-guidelines)
- [Feature Requests](#feature-requests)
- [Bug Reports](#bug-reports)

## Code of Conduct

This project and everyone participating in it is governed by our Code of Conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** to your local machine
3. **Set up the development environment**:
   ```bash
   git clone https://github.com/YOUR-USERNAME/davinci-resolve-mcp.git
   cd davinci-resolve-mcp
   pip install -e ".[dev]"
   ```
4. **Create a new branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Workflow

1. **Make changes** to the codebase
2. **Add tests** for any new functionality
3. **Ensure all tests pass**:
   ```bash
   pytest
   ```
4. **Update documentation** as needed
5. **Commit your changes** with clear, descriptive messages:
   ```bash
   git commit -m "Add feature X that does Y"
   ```
6. **Push your branch** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
7. **Create a pull request** from your fork to the main repository

## Pull Request Process

1. Ensure your PR includes **appropriate tests** for any new functionality
2. Update the **documentation** with details of changes
3. The PR should work on **Python 3.6+**
4. Include a clear **description of the changes** in your PR
5. Link any related **issues** in the PR description
6. PRs require approval from at least one maintainer before merging

## Coding Standards

We follow standard Python conventions with a few specific requirements:

1. **Style**: We use [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guidelines
2. **Linting**: Run `flake8` before submitting code
3. **Type hints**: Use Python type hints for function parameters and return values
4. **Docstrings**: Use Google style docstrings
5. **Function naming**:
   - All MCP functions should be prefixed with `mcp_`
   - Use clear, descriptive names

Example:

```python
def mcp_get_timeline_markers() -> Dict[str, Any]:
    """
    Get all markers in the current timeline.
    
    Returns:
        Dict[str, Any]: A dictionary containing all timeline markers.
            Format: {
                "markers": [
                    {
                        "frame": int,
                        "color": str,
                        "name": str,
                        "note": str,
                        "duration": int
                    },
                    ...
                ]
            }
    """
    # Implementation
```

## Testing Requirements

1. **Unit tests** are required for all new functionality
2. **Min coverage**: Aim for at least 80% test coverage for new code
3. **Test organization**: 
   - Place tests in the `tests/` directory
   - Name test files with `test_` prefix
   - Name test functions with `test_` prefix
4. **Mock DaVinci Resolve**: Use mocking to test without requiring Resolve

Example test:

```python
def test_mcp_get_timeline_markers():
    # Setup mock
    mock_timeline = MagicMock()
    mock_timeline.GetMarkers.return_value = {
        "1000": {
            "color": "Blue",
            "name": "Test Marker",
            "note": "Test Note",
            "duration": 0
        }
    }
    
    # Test function with mock
    with patch('module.get_resolve', return_value=mock_resolve):
        result = mcp_get_timeline_markers()
    
    # Assertions
    assert len(result["markers"]) == 1
    assert result["markers"][0]["frame"] == 1000
    assert result["markers"][0]["color"] == "Blue"
```

## Documentation Guidelines

1. **Function documentation**:
   - Update `MASTER_DAVINCI_RESOLVE_MCP.md` with new functions
   - Include STATUS tags for implementation status
   - Document parameters, return values, and examples
   
2. **Example scripts**:
   - Add example scripts in the `examples/` directory
   - Make examples executable
   - Include comprehensive comments
   
3. **README updates**:
   - Keep the README.md updated with new features
   - Ensure the feature list is current

## Feature Requests

1. Check existing issues to see if the feature has been requested
2. Use the feature request template when opening a new issue
3. Clearly describe the proposed functionality
4. Explain why this feature would be useful
5. If possible, outline how it might be implemented

## Bug Reports

1. Check existing issues to see if the bug has been reported
2. Use the bug report template when opening a new issue
3. Include:
   - DaVinci Resolve version
   - Python version
   - OS version
   - Clear steps to reproduce
   - Expected vs. actual behavior
   - Screenshots if applicable
   - Any error messages or logs

Thank you for contributing to DaVinci Resolve MCP! 