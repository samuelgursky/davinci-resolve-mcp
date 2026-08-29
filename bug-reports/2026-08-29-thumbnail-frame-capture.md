## Bug: timeline_frame capture(quality="frame") fails with unexpected keyword argument

**Environment**
- DaVinci Resolve 21.0.4.5 (free edition, via in-app bridge)
- Windows 11
- Server: davinci-resolve-mcp compound server (installed via install.py)

**Steps to reproduce**
1. Set current timeline
2. Call `timeline_frame(action="capture", params={"frame": <any frame>, "quality": "frame"})`

**Expected**
Frame-exact capture of the processed output (per docs: "Captures Resolve's
processed output — grade, Fusion, titles, transitions").

**Actual**
Consistent error on every call:
`_BoundMethod.__call__() got an unexpected keyword argument 'isInteractiveMode'`

quality="thumbnail" works but returns a black frame for a Fusion/Text+ title
clip (GetCurrentClipThumbnailImage limitation, separately known).

Looks like a keyword-argument call against a Resolve API bound method that
only accepts positional args on this build/edition.
