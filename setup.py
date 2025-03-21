#!/usr/bin/env python3
"""
Setup script for DaVinci Resolve MCP
"""

from setuptools import setup, find_packages

setup(
    name="davinci-resolve-mcp",
    version="1.1.0",
    description="Media Control Protocol (MCP) framework for DaVinci Resolve",
    long_description="""
    A Media Control Protocol (MCP) framework for DaVinci Resolve that provides tools for
    accessing and controlling DaVinci Resolve through the Scripting API.
    
    Features include:
    - Project management (listing, info, switching)
    - Timeline operations (clip info, markers, playback control)
    - Media pool access (browsing, folder management, smart bins)
    - Color correction (node management, primary correction, LUTs)
    - Advanced clip and marker operations
    """,
    author="Samuel Gursky",
    author_email="samuelgursky@example.com",
    url="https://github.com/samuelgursky/davinci-resolve-mcp",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        # "mcp>=1.0.0",  # Commented out as package is not available on PyPI
        "pytest>=7.0.0"
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "flake8>=4.0.0",
            "black>=22.0.0",
            "mypy>=0.9.0",
        ]
    },
    python_requires=">=3.6",
    entry_points={
        "console_scripts": [
            "davinci-resolve-mcp=davinci_resolve_mcp.server:run_server",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Multimedia :: Video",
        "Topic :: Software Development :: Libraries",
    ],
    keywords="davinci resolve, video editing, color correction, media management, api, mcp",
    project_urls={
        "Bug Reports": "https://github.com/samuelgursky/davinci-resolve-mcp/issues",
        "Source": "https://github.com/samuelgursky/davinci-resolve-mcp",
        "Documentation": "https://github.com/samuelgursky/davinci-resolve-mcp/blob/main/MASTER_DAVINCI_RESOLVE_MCP.md",
    },
) 