# Changelog

All notable changes to the DaVinci Resolve MCP Server project will be documented in this file.

## [1.3.3] - 2025-03-27

### Fixed
- Improved Windows compatibility for the run-now.bat script:
  - Fixed ANSI color code syntax errors in Windows command prompt
  - Made the npm/Node.js check a warning instead of an error
  - Simplified environment variable handling for better Windows compatibility
  - Fixed command syntax in batch file for more reliable execution
  - Improved DaVinci Resolve process detection for Windows
  - Added support for detecting multiple possible DaVinci Resolve executable names
  - Enhanced batch file error handling and robustness
  - Fixed issue with running the MCP server executable on Windows
  - Increased timeout waiting for DaVinci Resolve to start 
- Added Windows specific templates in config-templates

## [1.3.2] - 2025-03-28

### Added
- Experimental Windows support with platform-specific path detection
- Dynamic environment setup based on operating system
- Platform utility module for handling OS-specific paths and configurations
- Enhanced error messages with platform-specific environment setup instructions
- Windows pre-launch check script (PowerShell) with automatic environment configuration
- Windows batch file launcher for easy execution of the pre-launch check

### Changed
- Refactored path setup code to use platform detection
- Improved logging with platform-specific information
- Updated documentation to reflect Windows compatibility status
- Enhanced README with Windows-specific configuration instructions

### Fixed
- Platform-dependent path issues that prevented Windows compatibility
- Environment variable handling for cross-platform use
- Windows-specific configuration paths for Cursor integration

## [1.3.1] - 2025-03-27

### Added
- Universal launcher script (`mcp_resolve_launcher.sh`) that provides both interactive and command-line interfaces for:
  - Starting and stopping Cursor MCP server
  - Starting and stopping Claude Desktop MCP server
  - Running both servers simultaneously
  - Checking server status
  - Forcing server start even if DaVinci Resolve isn't detected
  - Specifying a project to open on server start
- Improved Claude Desktop integration script with better error handling and force mode
- Enhanced detection for running DaVinci Resolve process

### Changed
- Updated documentation to include new universal launcher functionality
- Improved server startup process with better error handling and logging
- Enhanced cross-client compatibility between Cursor and Claude Desktop
- Relocated and improved marker test script from root to examples/markers directory with better documentation and organization

### Fixed
- Process detection issues when looking for running DaVinci Resolve
- Signal handling in server scripts for cleaner termination

## [1.3.0] - 2025-03-26

### Added
- Support for adding clips to timeline directly by name
- Intelligent marker placement with frame detection
- Enhanced logging and error reporting
- Improved code organization with modular architecture

### Changed
- Reorganized project structure for better maintainability
- Enhanced Claude Desktop integration with better error handling
- Optimized connection to DaVinci Resolve for faster response times
- Updated documentation to include more examples

### Fixed
- Issues with marker placement on empty timelines
- Media pool navigation in complex project structures
- Timing issues when rapidly sending commands to DaVinci Resolve

## [1.1.0] - 2025-03-26

### Added
- Claude Desktop integration with claude_desktop_config.json support
- Consolidated server management script (scripts/server.sh)
- Project structure reorganization for better maintenance
- Configuration templates for easier setup

### Changed
- Moved scripts to dedicated scripts/ directory
- Organized example files into examples/ directory
- Updated README with Claude Desktop instructions
- Updated FEATURES.md to reflect Claude Desktop compatibility

### Fixed
- Environment variable handling in server scripts
- Path references in documentation

## [1.0.0] - 2025-03-24

### Added
- Initial release with Cursor integration
- DaVinci Resolve connection functionality
- Project management features (list, open, create projects)
- Timeline operations (create, list, switch timelines)
- Marker functionality with advanced frame detection
- Media Pool operations (import media, create bins)
- Comprehensive setup scripts
- Pre-launch check script

### Changed
- Switched from original MCP framework to direct JSON-RPC for improved reliability

### Fixed
- Save Project functionality with multi-method approach
- Environment variable setup for consistent connection

## [0.1.0] - 2025-03-26

### Added
- Initial release with core functionality
- Connection to DaVinci Resolve via MCP
- Project management features (list, open, create projects)
- Timeline operations (list, create, switch timelines, add markers)
- Media pool operations (list clips, import media, create bins)
- Setup script for easier installation and configuration
- Comprehensive documentation

### Implemented Features
- [x] **Get Resolve Version** – Resource that returns the Resolve version string
- [x] **Get Current Page** – Resource that identifies which page is currently open in the UI
- [x] **Switch Page** – Tool to change the UI to a specified page

- [x] **List Projects** – Resource that lists available project names
- [x] **Get Current Project Name** – Resource that retrieves the name of the currently open project
- [x] **Open Project** – Tool to open a project by name
- [x] **Create New Project** – Tool to create a new project with a given name
- [x] **Save Project** – Tool to save the current project

- [x] **List Timelines** – Resource that lists all timeline names in the current project
- [x] **Get Current Timeline** – Resource that gets information about the current timeline
- [x] **Create Timeline** – Tool to create a new timeline
- [x] **Set Current Timeline** – Tool to switch to a different timeline by name
- [x] **Add Marker** – Tool to add a marker at a specified time on the current timeline

- [x] **List Media Pool Clips** – Resource that lists clips in the media pool
- [x] **Import Media** – Tool to import a media file into the current project
- [x] **Create Bin** – Tool to create a new bin/folder in the media pool

### Future Work
- [ ] Move Clip to Timeline – Tool to take a clip from the media pool and place it on the timeline
- [ ] Windows and Linux Support
- [ ] Claude Desktop Integration
- [ ] Color Page Operations
- [ ] Fusion Operations

## [0.3.0] - 2025-03-26
### Changed
- Cleaned up project structure by removing redundant test scripts and log files
- Removed duplicate server implementations to focus on the main MCP server
- Consolidated server startup scripts to simplify usage
- Created backup directories for removed files (cleanup_backup and logs_backup)
- Improved marker functionality with better frame detection and clip-aware positioning

### Added
- Implemented "Add Clip to Timeline" feature to allow adding media pool clips to timelines
- Added test script for validating timeline operations
- Added comprehensive marker testing to improve functionality

## [0.3.1] - 2025-03-27
### Enhanced
- Completely overhauled marker functionality:
  - Added intelligent frame selection when frame is not specified
  - Improved error handling for marker placement
  - Added collision detection to avoid overwriting existing markers
  - Added suggestions for alternate frames when a marker already exists
  - Implemented validation to ensure markers are placed on actual clips
  - Better debugging and detailed error messages

### Fixed
- Resolved issue with markers failing silently when trying to place on invalid frames
- Fixed marker placement to only allow adding markers on actual media content

## [0.2.0] - 2025-03-25

### Added
- Added new features and improvements
- Updated documentation

### Implemented Features
- [x] **New Feature 1** – Description of the new feature
- [x] **New Feature 2** – Description of the new feature

### Future Work
- [ ] Task 1 – Description of the task
- [ ] Task 2 – Description of the task
