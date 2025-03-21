# DaVinci Resolve Project Settings API Limitations

## Overview

This document outlines the limitations of the DaVinci Resolve scripting API with regard to project and timeline settings. Based on comprehensive testing, we've identified which settings can be successfully read and modified through the API, and which cannot.

## Analysis Results

Our analysis tested 31 different settings (17 project settings and 14 timeline settings) and found significant limitations in the API's ability to modify these settings.

### Project Settings

| Settings Type | Total Tested | Successfully Modified | Success Rate |
|---------------|--------------|----------------------|-------------|
| Project Settings | 17 | 4 | 23.5% |

### Timeline Settings

| Settings Type | Total Tested | Successfully Modified | Success Rate |
|---------------|--------------|----------------------|-------------|
| Timeline Settings | 14 | 0 | 0% |

## Modifiable Project Settings

The following project settings can be successfully modified through the API:

1. **timelineResolutionWidth** - Project timeline width
2. **timelineResolutionHeight** - Project timeline height
3. **colorScienceMode** - Project color science (e.g., "davinciYRGB")
4. **videoMonitorBitDepth** - Bit depth for video monitoring

## Read-Only Settings

All other tested settings appear to be read-only or exhibit inconsistent behavior when attempting to modify them through the API. This includes:

### Project Settings (Read-Only)

- timelineFrameRate
- timelineUseCustomSettings
- inputColorSpace
- outputColorSpace
- timelineOutputSizing
- videoMonitorWidth
- videoMonitorHeight
- videoMonitorUseRec709A
- videoMonitorUseColorspaceOverride
- audioSampleRate
- superScale
- superScaleQuality
- autoClipColors

### Timeline Settings (All Read-Only)

- frameRate
- width
- height
- useRollingShutter
- useSmoothOpticalFlow
- useDynamicZoomEase
- useSmartcache
- usePerfectResizeNE
- createStereoVersion
- superscaleMethod
- motionEstimation
- resizeFilter
- audioSampleRate
- audioFrameRate

## Likely Causes for API Limitations

1. **API Design Limitations**: The DaVinci Resolve API appears to be designed primarily for reading project and timeline settings, with limited write capabilities.

2. **Protected Settings**: Many settings may be protected to ensure project stability and prevent scripting from causing inconsistent states.

3. **UI-Driven Settings**: Some settings might only be modifiable through the UI, with changes potentially requiring additional validation or related settings adjustments that aren't exposed to the API.

4. **Version-Specific Behavior**: API behavior may vary across DaVinci Resolve versions.

## Recommended Approach

Given these limitations, we recommend the following approach for working with project and timeline settings:

1. **Use the API for Reading**: The API is reliable for reading most settings, so use it to get current values and make decisions based on them.

2. **Focus on Known Modifiable Settings**: When modification is necessary, focus on the few settings that have been verified to work: resolution width/height, color science mode, and video monitor bit depth.

3. **Document Limitations to Users**: Clearly communicate to users which settings can and cannot be modified through the API.

4. **Consider UI Automation**: For critical settings that must be modified but cannot be accessed through the API, UI automation might be an alternative, though significantly more complex solution.

5. **Implement Fallbacks**: When attempting to modify a setting, implement fallback methods and alternate approaches as we've done in the improved implementation.

## Future Improvements

For future development, consider:

1. **Version Testing**: Test across multiple DaVinci Resolve versions to identify version-specific capabilities.

2. **Setting Dependencies**: Investigate dependencies between settings to see if modifying certain settings together improves success rates.

3. **Project Presets**: Use project and render presets as alternative ways to apply settings when direct modification fails.

4. **Feature Requests**: Submit feature requests to Blackmagic Design for improving the scripting API's ability to modify project and timeline settings.

## Conclusion

The DaVinci Resolve scripting API has significant limitations when it comes to modifying project and timeline settings. Our implementation focuses on making the best use of the available capabilities while providing clear feedback when operations aren't possible through the API.

We will continue to update this document as we discover additional techniques or as the API evolves in future versions of DaVinci Resolve. 