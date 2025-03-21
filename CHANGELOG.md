# Changelog

All notable changes to the DaVinci Resolve MCP framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2023-03-22

### Added
- Timeline marker functions
  - Added support for getting timeline markers
  - Added support for adding, updating, and deleting markers
  - Added support for batch operations like deleting markers by color
- Advanced media pool functions
  - Added folder hierarchy navigation
  - Added folder path creation and management
  - Added support for bulk operations on clips
  - Added smart bins management
- Color correction functions
  - Added node management (add, select, delete, reset)
  - Added primary color correction controls
  - Added node labeling and coloring
  - Added LUT import and application
- Comprehensive documentation
  - Added DOCUMENTATION.md with detailed usage examples
  - Added CONTRIBUTING.md with contribution guidelines
  - Added NEXT_STEPS.md roadmap document
  - Enhanced MASTER_DAVINCI_RESOLVE_MCP.md with all new functions

### Changed
- Improved test coverage with unit tests for all new functions
- Enhanced example scripts to demonstrate new functionality
- Restructured codebase with modular organization
- Updated README.md with new function documentation

### Fixed
- Various issues with timeline manipulation
- Improved error handling in media pool operations
- Fixed inconsistencies in clip property management

### Removed
- Removed experimental XML export functions pending further development
- Removed incomplete timecode export utilities
- Cleaned up unused test scripts

## [1.0.0] - 2023-01-15

### Added
- Initial release of the DaVinci Resolve MCP framework
- Core MCP server and client functionality
- Basic timeline operations
- Basic media pool operations
- Project management functions
- Playback control functions 