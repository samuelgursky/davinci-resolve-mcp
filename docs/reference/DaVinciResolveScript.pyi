''' Type stubs for DaVinciResolveScript, the DaVinci Resolve Python scripting API. '''

from typing import TypedDict, Literal, TypeAlias

ClipColor = Literal['Orange', 'Apricot', 'Yellow', 'Lime', 'Olive', 'Green', 'Teal', 'Navy', 'Blue', 'Purple', 'Violet', 'Pink', 'Tan', 'Beige', 'Brown', 'Chocolate']
FlagColor = Literal['Blue', 'Cyan', 'Green', 'Yellow', 'Red', 'Pink', 'Purple', 'Fuchsia', 'Rose', 'Lavender', 'Sky', 'Mint', 'Lemon', 'Sand', 'Cocoa', 'Cream']
MarkerColor = Literal['Blue', 'Cyan', 'Green', 'Yellow', 'Red', 'Pink', 'Purple', 'Fuchsia', 'Rose', 'Lavender', 'Sky', 'Mint', 'Lemon', 'Sand', 'Cocoa', 'Cream']
MarkType = Literal['video', 'audio', 'all']
TrackType = Literal['video', 'audio', 'subtitle']

KeyframeMode: TypeAlias = float
"""One of the resolve.* constants: KEYFRAME_MODE_ALL, KEYFRAME_MODE_COLOR, KEYFRAME_MODE_SIZING"""
CloudSettingKey: TypeAlias = float
"""One of the resolve.* constants: CLOUD_SETTING_PROJECT_NAME, CLOUD_SETTING_PROJECT_MEDIA_PATH, CLOUD_SETTING_IS_COLLAB, CLOUD_SETTING_SYNC_MODE, CLOUD_SETTING_IS_CAMERA_ACCESS"""
CloudSyncMode: TypeAlias = float
"""One of the resolve.* constants: CLOUD_SYNC_NONE, CLOUD_SYNC_PROXY_ONLY, CLOUD_SYNC_PROXY_AND_ORIG"""
AudioSyncSettingKey: TypeAlias = float
"""One of the resolve.* constants: AUDIO_SYNC_MODE, AUDIO_SYNC_CHANNEL_NUMBER, AUDIO_SYNC_RETAIN_EMBEDDED_AUDIO, AUDIO_SYNC_RETAIN_VIDEO_METADATA"""
AudioSyncMode: TypeAlias = float
"""One of the resolve.* constants: AUDIO_SYNC_WAVEFORM, AUDIO_SYNC_TIMECODE, AUDIO_SYNC_IN, AUDIO_SYNC_OUT, AUDIO_SYNC_MARKER"""
AudioSyncChannel: TypeAlias = float
"""One of the resolve.* constants: AUDIO_SYNC_CHANNEL_AUTOMATIC, AUDIO_SYNC_CHANNEL_MIX"""
MulticamAngleSyncMode: TypeAlias = float
"""One of the resolve.* constants: MULTICAM_ANGLE_SYNC_IN, MULTICAM_ANGLE_SYNC_OUT, MULTICAM_ANGLE_SYNC_TIMECODE, MULTICAM_ANGLE_SYNC_AUDIO, MULTICAM_ANGLE_SYNC_MARKER"""
MulticamAngleNameMode: TypeAlias = float
"""One of the resolve.* constants: MULTICAM_ANGLE_NAME_SEQUENTIAL, MULTICAM_ANGLE_NAME_ANGLE, MULTICAM_ANGLE_NAME_CAMERA, MULTICAM_ANGLE_NAME_CLIP, MULTICAM_ANGLE_NAME_FILE"""
MulticamDetectMode: TypeAlias = float
"""One of the resolve.* constants: MULTICAM_DETECT_BY_CAMERA_NUMBER, MULTICAM_DETECT_BY_ANGLE, MULTICAM_DETECT_BY_REEL_NUMBER, MULTICAM_DETECT_BY_REEL_NAME, MULTICAM_DETECT_BY_ROLL_CARD, MULTICAM_DETECT_NONE"""
MulticamAudioMode: TypeAlias = float
"""One of the resolve.* constants: MULTICAM_AUDIO_ADAPTIVE, MULTICAM_AUDIO_SOURCE, MULTICAM_AUDIO_REFERENCE, MULTICAM_AUDIO_ALL"""
CloudSyncStatus: TypeAlias = float
"""One of the resolve.* constants: CLOUD_SYNC_DEFAULT, CLOUD_SYNC_DOWNLOAD_IN_QUEUE, CLOUD_SYNC_DOWNLOAD_IN_PROGRESS, CLOUD_SYNC_DOWNLOAD_SUCCESS, CLOUD_SYNC_DOWNLOAD_FAIL, CLOUD_SYNC_DOWNLOAD_NOT_FOUND, CLOUD_SYNC_UPLOAD_IN_QUEUE, CLOUD_SYNC_UPLOAD_IN_PROGRESS, CLOUD_SYNC_UPLOAD_SUCCESS, CLOUD_SYNC_UPLOAD_FAIL, CLOUD_SYNC_UPLOAD_NOT_FOUND, CLOUD_SYNC_SUCCESS"""
SlateMarkerColor: TypeAlias = float
"""One of the resolve.* constants: MARKER_NONE, MARKER_BLUE, MARKER_CYAN, MARKER_GREEN, MARKER_YELLOW, MARKER_RED, MARKER_PINK, MARKER_PURPLE, MARKER_FUCHSIA, MARKER_ROSE, MARKER_LAVENDER, MARKER_SKY, MARKER_MINT, MARKER_LEMON, MARKER_SAND, MARKER_COCOA, MARKER_CREAM"""
NormalizeAudioSetLevelMode: TypeAlias = float
"""One of the resolve.* constants: NORMALIZE_AUDIO_SET_LEVEL_RELATIVE, NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT"""
AutoAlignSyncUsing: TypeAlias = float
"""One of the resolve.* constants: AUTO_ALIGN_CLIPS_USING_WAVEFORM, AUTO_ALIGN_CLIPS_USING_TIMECODE"""
AutoAlignUseTrack: TypeAlias = float
"""One of the resolve.* constants: AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_MIX, AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_AUTOMATIC"""
TimelineExportType: TypeAlias = float
"""One of the resolve.* constants: EXPORT_AAF, EXPORT_DRT, EXPORT_EDL, EXPORT_FCP_7_XML, EXPORT_FCPXML_1_8, EXPORT_FCPXML_1_9, EXPORT_FCPXML_1_10, EXPORT_HDR_10_PROFILE_A, EXPORT_HDR_10_PROFILE_B, EXPORT_TEXT_CSV, EXPORT_TEXT_TAB, EXPORT_DOLBY_VISION_VER_2_9, EXPORT_DOLBY_VISION_VER_4_0, EXPORT_DOLBY_VISION_VER_5_1, EXPORT_OTIO, EXPORT_ALE, EXPORT_ALE_CDL"""
TimelineExportSubtype: TypeAlias = float
"""One of the resolve.* constants: EXPORT_NONE, EXPORT_AAF_NEW, EXPORT_AAF_EXISTING, EXPORT_CDL, EXPORT_SDL, EXPORT_MISSING_CLIPS"""
SubtitleSettingKey: TypeAlias = float
"""One of the resolve.* constants: SUBTITLE_LANGUAGE, SUBTITLE_CAPTION_PRESET, SUBTITLE_CHARS_PER_LINE, SUBTITLE_LINE_BREAK, SUBTITLE_GAP"""
AutoCaptionLanguage: TypeAlias = float
"""One of the resolve.* constants: AUTO_CAPTION_AUTO, AUTO_CAPTION_MANDARIN_SIMPLIFIED, AUTO_CAPTION_DUTCH, AUTO_CAPTION_ENGLISH, AUTO_CAPTION_FINNISH, AUTO_CAPTION_FRENCH, AUTO_CAPTION_GERMAN, AUTO_CAPTION_HINDI, AUTO_CAPTION_INDONESIAN, AUTO_CAPTION_ITALIAN, AUTO_CAPTION_JAPANESE, AUTO_CAPTION_KOREAN, AUTO_CAPTION_MALAY, AUTO_CAPTION_NORWEGIAN, AUTO_CAPTION_POLISH, AUTO_CAPTION_PORTUGUESE, AUTO_CAPTION_ROMANIAN, AUTO_CAPTION_RUSSIAN, AUTO_CAPTION_SPANISH, AUTO_CAPTION_SWEDISH, AUTO_CAPTION_TURKISH, AUTO_CAPTION_VIETNAMESE, AUTO_CAPTION_TAMIL, AUTO_CAPTION_THAI, AUTO_CAPTION_DANISH, AUTO_CAPTION_MANDARIN_TRADITIONAL"""
AutoCaptionPreset: TypeAlias = float
"""One of the resolve.* constants: AUTO_CAPTION_SUBTITLE_DEFAULT, AUTO_CAPTION_TELETEXT, AUTO_CAPTION_NETFLIX"""
AutoCaptionLineBreak: TypeAlias = float
"""One of the resolve.* constants: AUTO_CAPTION_LINE_SINGLE, AUTO_CAPTION_LINE_DOUBLE"""
DolbyVisionAnalysisType: TypeAlias = float
"""One of the resolve.* constants: DLB_BLEND_SHOTS"""
DynamicZoomEase: TypeAlias = float
"""One of the resolve.* constants: DYNAMIC_ZOOM_EASE_LINEAR, DYNAMIC_ZOOM_EASE_IN, DYNAMIC_ZOOM_EASE_OUT, DYNAMIC_ZOOM_EASE_IN_AND_OUT"""
CompositeMode: TypeAlias = float
"""One of the resolve.* constants: COMPOSITE_NORMAL, COMPOSITE_ADD, COMPOSITE_SUBTRACT, COMPOSITE_DIFF, COMPOSITE_MULTIPLY, COMPOSITE_SCREEN, COMPOSITE_OVERLAY, COMPOSITE_HARDLIGHT, COMPOSITE_SOFTLIGHT, COMPOSITE_DARKEN, COMPOSITE_LIGHTEN, COMPOSITE_COLOR_DODGE, COMPOSITE_COLOR_BURN, COMPOSITE_EXCLUSION, COMPOSITE_HUE, COMPOSITE_SATURATE, COMPOSITE_COLORIZE, COMPOSITE_LUMA_MASK, COMPOSITE_DIVIDE, COMPOSITE_LINEAR_DODGE, COMPOSITE_LINEAR_BURN, COMPOSITE_LINEAR_LIGHT, COMPOSITE_VIVID_LIGHT, COMPOSITE_PIN_LIGHT, COMPOSITE_HARD_MIX, COMPOSITE_LIGHTER_COLOR, COMPOSITE_DARKER_COLOR, COMPOSITE_FOREGROUND, COMPOSITE_ALPHA, COMPOSITE_INVERTED_ALPHA, COMPOSITE_LUM, COMPOSITE_INVERTED_LUM"""
RetimeProcess: TypeAlias = float
"""One of the resolve.* constants: RETIME_USE_PROJECT, RETIME_NEAREST, RETIME_FRAME_BLEND, RETIME_OPTICAL_FLOW"""
MotionEstimation: TypeAlias = float
"""One of the resolve.* constants: MOTION_EST_USE_PROJECT, MOTION_EST_STANDARD_FASTER, MOTION_EST_STANDARD_BETTER, MOTION_EST_ENHANCED_FASTER, MOTION_EST_ENHANCED_BETTER, MOTION_EST_SPEED_WARP_FASTER, MOTION_EST_SPEED_WARP_BETTER, MOTION_EST_METAL"""
Scaling: TypeAlias = float
"""One of the resolve.* constants: SCALE_USE_PROJECT, SCALE_CROP, SCALE_FIT, SCALE_FILL, SCALE_STRETCH"""
ResizeFilter: TypeAlias = float
"""One of the resolve.* constants: RESIZE_FILTER_USE_PROJECT, RESIZE_FILTER_SHARPER, RESIZE_FILTER_SMOOTHER, RESIZE_FILTER_BICUBIC, RESIZE_FILTER_BILINEAR, RESIZE_FILTER_BESSEL, RESIZE_FILTER_BOX, RESIZE_FILTER_CATMULL_ROM, RESIZE_FILTER_CUBIC, RESIZE_FILTER_GAUSSIAN, RESIZE_FILTER_LANCZOS, RESIZE_FILTER_MITCHELL, RESIZE_FILTER_NEAREST_NEIGHBOR, RESIZE_FILTER_QUADRATIC, RESIZE_FILTER_SINC, RESIZE_FILTER_LINEAR"""
CacheMode: TypeAlias = float
"""One of the resolve.* constants: CACHE_AUTO_ENABLED, CACHE_DISABLED, CACHE_ENABLED"""
DialogueLevelerMode: TypeAlias = float
"""One of the resolve.* constants: DIALOGUE_LEVELER_MODE_ALLOW_WIDER_DYNAMICS, DIALOGUE_LEVELER_MODE_OPTIMIZE_MODERATE_LEVELS, DIALOGUE_LEVELER_MODE_MORE_LIFT_FOR_LOW_LEVELS, DIALOGUE_LEVELER_MODE_LIFT_SOFT_WHISPERY_SOURCES"""
FlattenMulticamGrade: TypeAlias = float
"""One of the resolve.* constants: FLATTEN_MULTICAM_COPY_GRADE, FLATTEN_MULTICAM_RETAIN_GRADE_FROM_ANGLE"""
ExportLutType: TypeAlias = float
"""One of the resolve.* constants: EXPORT_LUT_17PTCUBE, EXPORT_LUT_33PTCUBE, EXPORT_LUT_65PTCUBE, EXPORT_LUT_PANASONICVLUT"""
SmartSwitchQuality: TypeAlias = float
"""One of the resolve.* constants: SMART_SWITCH_QUALITY_FASTER, SMART_SWITCH_QUALITY_BETTER"""
SmartSwitchWideAngleFrequency: TypeAlias = float
"""One of the resolve.* constants: SMART_SWITCH_WIDE_ANGLE_FREQ_LOW, SMART_SWITCH_WIDE_ANGLE_FREQ_MEDIUM, SMART_SWITCH_WIDE_ANGLE_FREQ_HIGH"""
SmartSwitchAnalysisMode: TypeAlias = float
"""One of the resolve.* constants: SMART_SWITCH_ANALYSIS_MODE_NONE, SMART_SWITCH_ANALYSIS_MODE_DETECT_WIDE_ANGLE, SMART_SWITCH_ANALYSIS_MODE_AUDIO_ONLY"""
CloneChecksumType: TypeAlias = float
"""One of the resolve.* constants: CLONE_CHECKSUM_TYPE_NONE, CLONE_CHECKSUM_TYPE_FILESIZE, CLONE_CHECKSUM_TYPE_CRC32, CLONE_CHECKSUM_TYPE_MD5, CLONE_CHECKSUM_TYPE_SHA256, CLONE_CHECKSUM_TYPE_SHA512, CLONE_CHECKSUM_TYPE_XXH_64"""

class AAFImportOptions(TypedDict, total=False):
	autoImportSourceClipsIntoMediaPool: bool
	"""Import source clips into media pool (default: True)"""
	ignoreFileExtensionsWhenMatching: bool
	"""Ignore file extensions when matching (default: False)"""
	linkToSourceCameraFiles: bool
	"""Link to source camera files (default: False)"""
	useSizingInfo: bool
	"""Use sizing information (default: False)"""
	importMultiChannelAudioTracksAsLinkedGroups: bool
	"""Import multi-channel audio tracks as linked groups (default: False)"""
	insertAdditionalTracks: bool
	"""Insert additional tracks (default: True)"""
	insertWithOffset: str
	"""Insert with timecode offset, e.g. '00:00:00:00' (applies when insertAdditionalTracks is False)"""
	sourceClipsPath: str
	"""Filesystem path to search for source clips if media is inaccessible"""
	sourceClipsFolders: list[Folder]
	"""Media Pool folders to search for source clips"""

class AppendClipInfo(TypedDict, total=False):
	mediaPoolItem: 'MediaPoolItem'
	"""MediaPoolItem object to append"""
	startFrame: float
	"""Source start frame (optional)"""
	endFrame: float
	"""Source end frame (optional)"""
	mediaType: int
	"""1 - Video only, 2 - Audio only (optional)"""
	trackIndex: int
	"""Destination track index (optional)"""
	recordFrame: float
	"""Record frame position (optional)"""

class AudioSyncSettings(TypedDict, total=False):
	syncMode: AudioSyncMode
	"""Default: resolve.AUDIO_SYNC_TIMECODE"""
	channelNumber: int | AudioSyncChannel
	"""For AUDIO_SYNC_WAVEFORM mode: channel offset, 1 to min channel count across input clips (default: 1)"""
	retainEmbeddedAudio: bool
	"""Keep original embedded audio (default: False)"""
	retainVideoMetadata: bool
	"""Keep video metadata (default: False)"""

class AutoAlignOptions(TypedDict, total=False):
	SyncUsing: AutoAlignSyncUsing
	"""Default: resolve.AUTO_ALIGN_CLIPS_USING_TIMECODE"""
	UseTrack: int | AutoAlignUseTrack
	"""For USING_WAVEFORM mode: track index, 1, 2, ... (default: 1)"""

class AutoCaptionSettings(TypedDict, total=False):
	language: AutoCaptionLanguage
	"""Default: resolve.AUTO_CAPTION_AUTO"""
	captionPreset: AutoCaptionPreset
	"""Default: resolve.AUTO_CAPTION_SUBTITLE_DEFAULT"""
	charsPerLine: int
	"""Max characters per line, 1 to 60 (default: 42, varies by preset/language)"""
	lineBreak: AutoCaptionLineBreak
	"""Default: resolve.AUTO_CAPTION_LINE_SINGLE"""
	gap: int
	"""Gap between subtitles in frames, 0 to 10 (default: 0)"""

class CDL(TypedDict, total=False):
	NodeIndex: int
	"""Target node index, 1 <= NodeIndex <= total number of nodes"""
	Slope: str
	"""RGB slope values as space-separated string, e.g. '0.5 0.4 0.2'"""
	Offset: str
	"""RGB offset values as space-separated string, e.g. '0.4 0.3 0.2'"""
	Power: str
	"""RGB power values as space-separated string, e.g. '0.6 0.7 0.8'"""
	Saturation: float
	"""Saturation value, e.g. 0.65"""

ClipProperties = TypedDict('ClipProperties', {
	'Alpha mode': str,  # Alpha mode, e.g. 'None', 'Straight', 'Premultiplied'
	'Audio Bit Depth': str,  # Audio bit depth, e.g. '24'
	'Audio Ch': str,  # Number of audio channels, e.g. '2'
	'Audio Codec': str,  # Audio codec, e.g. 'AAC', 'Linear PCM'
	'Audio Offset': str,  # Audio offset value
	'Bit Depth': str,  # Video bit depth, e.g. '10'
	'Clip Color': ClipColor | Literal[''],  # Clip color, e.g. 'Orange', 'Teal'. Empty when no color is set
	'Clip Directory': str,  # Directory path of the clip
	'Clip Name': str,  # User-assigned clip name
	'Cloud Sync': str,  # Cloud sync status as string
	'Data Level': str,  # Data level, e.g. 'Auto', 'Full', 'Video'
	'Date Added': str,  # Date clip was added to media pool
	'Date Created': str,  # Date clip was created
	'Date Modified': str,  # Date clip was last modified
	'Drop frame': str,  # Drop frame setting, e.g. '0', '1'
	'Duration': str,  # Duration in timecode, e.g. '00:00:10:00'
	'Enable Deinterlacing': str,  # Deinterlacing enabled, e.g. '0', '1'
	'End TC': str,  # End timecode, e.g. '01:00:10:00'
	'FPS': float,  # Frame rate, e.g. 23.976, 25.0
	'Field Dominance': str,  # Field dominance, e.g. 'Progressive'
	'File Name': str,  # Source file name
	'File Path': str,  # Full path to source file
	'Flags': str,  # Flag colors assigned to the clip
	'Format': str,  # File format, e.g. 'QuickTime', 'MXF'
	'Frames': str,  # Total frame count
	'IDT': str,  # ACES Input Device Transform
	'In': str,  # Mark in point
	'Input Color Space': str,  # Input color space, e.g. 'Rec.709'
	'Input Gamma': str,  # Input gamma, e.g. 'Gamma 2.4'
	'Input LUT': str,  # Input LUT filename
	'Input Sizing Preset': str,  # Sizing preset name
	'Noise Reduction': str,  # Noise reduction value
	'Offline Reference': str,  # Offline reference path
	'Online Status': str,  # Online/offline status
	'Out': str,  # Mark out point
	'PAR': str,  # Pixel aspect ratio
	'Proxy': str,  # Proxy status
	'Proxy Media Path': str,  # Path to proxy media
	'Reel Name': str,  # Reel name
	'Resolution': str,  # Resolution, e.g. '1920x1080'
	'Sample Rate': str,  # Audio sample rate, e.g. '48000'
	'Sharpness': str,  # Sharpness value
	'Start': str,  # Start frame number
	'Start TC': str,  # Start timecode, e.g. '01:00:00:00'
	'Super Scale': int,  # Super Scale multiplier (1=off, 2=2x, 3=3x, 4=4x)
	'SuperScale Noise Reduction': str,  # Super Scale noise reduction value
	'SuperScale Sharpness': str,  # Super Scale sharpness value
	'Synced Audio': str,  # Synced audio filename
	'Type': str,  # Clip type, e.g. 'Video', 'Audio', 'Video + Audio'
	'Usage': str,  # Number of times clip is used in timelines
	'Video Codec': str,  # Video codec, e.g. 'H.264', 'Apple ProRes 422 HQ'
}, total=False)

class CloneStatus(TypedDict, total=False):
	JobStatus: str
	"""'Complete', 'Cloning', 'Cancelled', or 'Failed'. If no clone job has been started yet, this is 'Complete'"""
	CompletionPercentage: float
	"""Progress from 0.0 to 100.0"""
	Error: str
	"""Error message (set when JobStatus is 'Failed')"""

class CloneToolSettings(TypedDict, total=False):
	PreserveFolderName: bool
	"""Preserve folder name (default: False)"""
	ChecksumType: CloneChecksumType
	"""Default: resolve.CLONE_CHECKSUM_TYPE_MD5"""

class CloudSettings(TypedDict, total=False):
	projectName: str
	"""Project name"""
	projectMediaPath: str
	"""Local media storage path"""
	isCollab: bool
	"""Enable live collaboration mode"""
	syncMode: CloudSyncMode
	"""Media sync mode of the cloud project"""
	isCameraAccess: bool
	"""Enable camera access"""

class CompoundClipOptions(TypedDict, total=False):
	startTimecode: str
	"""Start timecode, e.g. '00:00:00:00'"""
	name: str
	"""Compound clip name"""

class CreateTimelineClipInfo(TypedDict, total=False):
	mediaPoolItem: 'MediaPoolItem'
	"""MediaPoolItem object to append"""
	startFrame: float
	"""Source start frame (optional)"""
	endFrame: float
	"""Source end frame (optional)"""
	recordFrame: float
	"""Record frame position (optional)"""

class DatabaseInfo(TypedDict, total=False):
	DbType: str
	"""'Disk' or 'PostgreSQL'"""
	DbName: str
	"""Name"""
	IpAddress: str
	"""IP address of the PostgreSQL server, e.g. '127.0.0.1' (optional)"""

class DeblurOptions(TypedDict, total=False):
	FileName: str
	"""Output file name pattern (default: '%{Source Name} Deblur')"""
	Format: str
	"""Output format, e.g. 'mov', 'mp4'"""
	Codec: str
	"""Output codec, e.g. 'H264', 'H265', 'ProRes422'"""
	EncodingProfile: str
	"""Encoding profile, e.g. 'Main10' (H.264/H.265 only)"""
	Encoder: str
	"""'Native' or 'MainConcept' (H.265 only)"""
	UseExtremeMode: bool
	"""Use extreme deblur mode (default: True)"""
	UseMarkInMarkOut: bool
	"""Only process mark in/out range (default: True)"""
	RenderAtSourceRes: bool
	"""Render at source resolution (default: False)"""
	UseMoreGpuMemory: bool
	"""Use more GPU memory for processing (default: False)"""

class EncryptDCTLOptions(TypedDict, total=False):
	Name: str | None
	"""Output filename (default: input filename)"""
	Expiry: str | None
	"""Valid ISO 8601 string (default: no expiry if empty value)"""
	OutputFolder: str | None
	"""Output folder (default: user's home folder)"""

class FadeInfo(TypedDict, total=False):
	FadeIn: int
	"""Duration in frames"""
	FadeOut: int
	"""Duration in frames"""

class FloatingWindowParams(TypedDict, total=False):
	left: float
	"""Left edge offset in pixels"""
	right: float
	"""Right edge offset in pixels"""
	top: float
	"""Top edge offset in pixels"""
	bottom: float
	"""Bottom edge offset in pixels"""

class ImportClipInfo(TypedDict, total=False):
	FilePath: str
	"""File path (supports %0Nd frame pattern for image sequences)"""
	StartIndex: int
	"""Start frame index for image sequences (optional)"""
	EndIndex: int
	"""End frame index for image sequences (optional)"""

class ImportOptions(TypedDict, total=False):
	timelineName: str
	"""Name for the created timeline (not valid for DRT import)"""
	importSourceClips: bool
	"""Import source clips into media pool (default: True, not valid for DRT)"""
	sourceClipsPath: str
	"""Filesystem path to search for source clips if media is inaccessible"""
	sourceClipsFolders: list[Folder]
	"""Media Pool folders to search for source clips if importSourceClips is False"""
	interlaceProcessing: bool
	"""Enable interlace processing (AAF import only)"""

MarkInOutRange = TypedDict('MarkInOutRange', {
	'in': int,  # Record frame relative to timeline start, e.g. 10
	'out': int,  # Record frame relative to timeline start, e.g. 320
}, total=False)

class MarkInOut(TypedDict, total=False):
	video: MarkInOutRange
	"""Video mark in/out range"""
	audio: MarkInOutRange
	"""Audio mark in/out range"""

class MarkerInfo(TypedDict, total=False):
	color: MarkerColor
	"""Color name, e.g. 'Blue', 'Green'"""
	duration: int
	"""Duration in frames, e.g. 1"""
	note: str
	"""Text note"""
	name: str
	"""Name, e.g. 'Marker 1'"""
	customData: str
	"""Custom data field not exposed via UI"""

class MediaStorageItemInfo(TypedDict, total=False):
	media: str
	"""File/folder path"""
	startFrame: int
	"""Start frame (optional)"""
	endFrame: int
	"""End frame (optional)"""

class MulticamOptions(TypedDict, total=False):
	name: str
	"""Clip name (auto-generated from first clip if omitted)"""
	startTimecode: str
	"""Start timecode, default: '01:00:00:00'"""
	frameRate: float
	"""Frame rate, e.g. 23.976 (default: project timeline frame rate)"""
	angleSyncMode: MulticamAngleSyncMode
	"""Default: resolve.MULTICAM_ANGLE_SYNC_TIMECODE"""
	channelConfig: int | AudioSyncChannel
	"""Audio channel for sync: 1-8 (angleSyncMode=MULTICAM_ANGLE_SYNC_AUDIO only)"""
	multicamAudioMode: MulticamAudioMode
	"""Default: resolve.MULTICAM_AUDIO_SOURCE"""
	angleNameMode: MulticamAngleNameMode
	"""Default: resolve.MULTICAM_ANGLE_NAME_SEQUENTIAL"""
	splitAtGaps: bool
	"""Split at gaps (angleSyncMode=MULTICAM_ANGLE_SYNC_AUDIO only, default: False)"""
	useFullClipExtents: bool
	"""Use full clip extents (default: False)"""
	createBinForSourceClips: bool
	"""Create bin for source clips (default: True)"""
	detectSameCameraClipsMode: MulticamDetectMode
	"""Default: resolve.MULTICAM_DETECT_NONE"""

class NormalizeAudioOptions(TypedDict, total=False):
	normalizationMode: str
	"""Mode name from GetNormalizeAudioModes() (default: 'Sample Peak Program')"""
	targetLevel: float
	"""Target level in dBFS, e.g. -9.0"""
	targetLoudness: float
	"""Target loudness in LKFS, e.g. -24.0"""
	setLevelMode: NormalizeAudioSetLevelMode
	"""Default: resolve.NORMALIZE_AUDIO_SET_LEVEL_RELATIVE"""

class OutputBlanking(TypedDict, total=False):
	Top: int
	"""Top blanking in pixels"""
	Bottom: int
	"""Bottom blanking in pixels"""
	Left: int
	"""Left blanking in pixels"""
	Right: int
	"""Right blanking in pixels"""

class ProjectAttributes(TypedDict, total=False):
	lastModifiedDate: str
	"""Last modified date in ISO 8601 format, e.g. '2024-06-15T09:30:00+05:30'"""
	creationDate: str
	"""Creation date in ISO 8601 format, e.g. '2024-06-15T09:30:00+05:30'"""
	notes: str
	"""Project notes"""
	liveCollaborationMode: str
	"""'multi_user' or 'single_user'"""

class ProjectSettings(TypedDict, total=False):
	timelineResolutionWidth: str
	"""e.g. '1920'"""
	timelineResolutionHeight: str
	"""e.g. '1080'"""
	timelinePixelAspectRatio: str
	"""'square', 'cinemascope', '16_9' or '4_3'"""
	timelineFrameRate: float | str
	"""Returned as a number, e.g. 23.976. Set as a string, e.g. '23.976' or '29.97 DF'"""
	timelineDropFrameTimecode: str
	"""'0' or '1'"""
	timelineInterlaceProcessing: str
	"""'0' or '1'"""
	timelinePlaybackFrameRate: str
	"""Read-only. e.g. '24'"""
	timelineOutputResMatchTimelineRes: str
	"""'0' or '1'"""
	timelineOutputResolutionWidth: str
	"""e.g. '1920'"""
	timelineOutputResolutionHeight: str
	"""e.g. '1080'"""
	timelineOutputPixelAspectRatio: str
	"""'square', 'cinemascope', '16_9' or '4_3'"""
	timelineInputResMismatchBehavior: str
	"""'centerCrop', 'scaleToFit', 'scaleToCrop' or 'stretch'"""
	timelineOutputResMismatchBehavior: str
	"""'centerCrop', 'scaleToFit', 'scaleToCrop' or 'stretch'"""
	timelineFrameRateMismatchBehavior: str
	"""e.g. 'resolve'"""
	timelineInputResMismatchUseCustomPreset: str
	"""'0' or '1'"""
	timelineInputResMismatchCustomPreset: str
	"""Input sizing preset name"""
	timelineOutputResMismatchUseCustomPreset: str
	"""'0' or '1'"""
	timelineOutputResMismatchCustomPreset: str
	"""Output sizing preset name"""
	timelineSampleRate: str
	"""Audio sample rate in Hz, e.g. '48000'"""
	timelineSaveThumbsInProject: str
	"""'0' or '1'"""
	imageRetimeInterpolation: str
	"""'nearest', 'frameBlend' or 'opticalFlow'"""
	imageMotionEstimationMode: str
	"""e.g. 'standardFaster'"""
	imageMotionEstimationRange: str
	"""'small', 'medium' or 'larger'"""
	imageResizeMode: str
	"""e.g. 'sharper'"""
	imageDeinterlaceQuality: str
	"""'normal' or 'high'"""
	imageEnableFieldProcessing: str
	"""'0' or '1'"""
	perfCacheClipsLocation: str
	"""Cache files directory path"""
	perfOptimisedMediaOn: str
	"""'0' or '1'"""
	perfProxyMediaMode: str
	"""'0' disabled, '1' when available, '2' when source not available"""
	perfRenderCacheMode: str
	"""'none', 'smart' or 'user'"""
	perfOptimizedResolutionRatio: str
	"""e.g. 'auto', 'original', 'half' or 'quarter'"""
	perfAutoRenderCacheEnable: str
	"""'0' or '1'"""
	perfAutoRenderCacheAfterTime: str
	"""Idle time in seconds before caching starts, e.g. '5'"""
	perfAutoRenderCacheTransition: str
	"""'0' or '1'"""
	perfAutoRenderCacheComposite: str
	"""'0' or '1'"""
	perfAutoRenderCacheFuEffect: str
	"""'0' or '1'"""
	perfOptimisedCodec: str
	"""Read-only. Optimized media codec name"""
	perfProxyResolutionRatio: str
	"""'original', 'half' or 'quarter'"""
	perfRenderCacheCodec: str
	"""Read-only. Render cache codec name"""
	isAutoColorManage: str
	"""'0' or '1'"""
	rcmPresetMode: str
	"""'SDR' or 'HDR' when isAutoColorManage is '1', otherwise e.g. 'SDR Rec.709' or 'Custom'"""
	separateColorSpaceAndGamma: str
	"""'0' or '1'"""
	colorScienceMode: str
	"""'davinciYRGB', 'davinciYRGBColorManaged', 'davinciYRGBColorManagedv2', 'acescc' or 'acescct'"""
	colorSpaceTimeline: str
	"""Timeline color space, e.g. 'Rec.709'"""
	colorSpaceTimelineGamma: str
	"""Timeline gamma, e.g. 'Gamma 2.4'"""
	colorSpaceInput: str
	"""Input color space"""
	colorSpaceInputGamma: str
	"""Input gamma"""
	colorSpaceOutput: str
	"""Output color space"""
	colorSpaceOutputGamma: str
	"""Output gamma"""
	colorSpaceOutputToneMapping: str
	"""'None', 'Simple', 'Luminance Mapping', 'DaVinci', 'Saturation Preserving' or 'RED IPP2'"""
	inputDRT: str
	"""'None', 'Simple', 'Luminance Mapping', 'DaVinci', 'Saturation Preserving' or 'RED IPP2'"""
	outputDRT: str
	"""'None', 'Simple', 'Luminance Mapping', 'DaVinci', 'Saturation Preserving' or 'RED IPP2'"""
	useInverseDRT: str
	"""'0' or '1'"""
	timelineWorkingLuminanceMode: str
	"""e.g. 'SDR 100', 'HDR 1000', 'HDR ER 1000/4000' or 'Custom'"""
	timelineWorkingLuminance: str
	"""Working luminance in nits, e.g. '1000'"""
	inputDRTSatRolloffStart: str
	"""Input saturation rolloff start in nits, e.g. '10000'"""
	inputDRTSatRolloffLimit: str
	"""Input saturation rolloff limit in nits, e.g. '10000'"""
	outputDRTSatRolloffStart: str
	"""Output saturation rolloff start in nits, e.g. '10000'"""
	outputDRTSatRolloffLimit: str
	"""Output saturation rolloff limit in nits, e.g. '10000'"""
	colorSpaceOutputGamutMapping: str
	"""'None', 'Saturation Mapping' or 'RED IPP2 Gamut Mapping'"""
	imageResizingGamma: str
	"""'Timeline', 'Log', 'Linear', 'Linear - Tone Mapped', 'Gamma' or 'Gamma - Tone Mapped'"""
	graphicsWhiteLevel: str
	"""Graphics white level in nits, e.g. '200'"""
	useCATransform: str
	"""'0' or '1'"""
	disableFusionToneMapping: str
	"""'0' or '1'"""
	useColorSpaceAwareGradingTools: str
	"""'0' or '1'"""
	colorAcesIDT: str
	"""ACES Input Device Transform"""
	colorAcesGamutCompressType: str
	"""ACES gamut compression type"""
	colorAcesODT: str
	"""ACES Output Device Transform"""
	colorAcesNodeLUTProcessingSpace: str
	"""'projectSetting', 'acesccAp1' or 'acesAp0Linear'"""
	colorSpaceOutputToneLuminanceMax: str
	"""Max output luminance in nits, e.g. '1000'"""
	colorSpaceOutputGamutSaturationKnee: str
	"""Saturation knee, e.g. '0.9'"""
	colorSpaceOutputGamutSaturationMax: str
	"""Saturation max, e.g. '1'"""
	colorKeyframeDynamicsStartProfile: str
	"""Keyframe dynamics start profile, e.g. '1'"""
	colorKeyframeDynamicsEndProfile: str
	"""Keyframe dynamics end profile, e.g. '1'"""
	colorLuminanceMixerDefaultZero: str
	"""'0' or '1'"""
	colorUseLegacyLogGrades: str
	"""'0', '1' or '2'"""
	colorUseContrastSCurve: str
	"""'0' or '1'"""
	colorUseStereoConvergenceForEffects: str
	"""'0' or '1'"""
	colorUseLocalVersionsAsDefault: str
	"""'0' or '1'"""
	colorUseBGRPixelOrderForDPX: str
	"""'0' or '1'"""
	colorGalleryStillsLocation: str
	"""Gallery stills directory path"""
	colorGalleryStillsNamingEnabled: str
	"""'0' or '1'"""
	colorGalleryStillsNamingPattern: str
	"""Gallery stills naming pattern"""
	colorGalleryStillsNamingCustomPattern: str
	"""Gallery stills custom naming pattern"""
	colorGalleryStillsNamingWithStillNumber: str
	"""'0' or '1'"""
	colorVersion1Name: str
	"""Name of color version 1"""
	colorVersion2Name: str
	"""Name of color version 2"""
	colorVersion3Name: str
	"""Name of color version 3"""
	colorVersion4Name: str
	"""Name of color version 4"""
	colorVersion5Name: str
	"""Name of color version 5"""
	colorVersion6Name: str
	"""Name of color version 6"""
	colorVersion7Name: str
	"""Name of color version 7"""
	colorVersion8Name: str
	"""Name of color version 8"""
	colorVersion9Name: str
	"""Name of color version 9"""
	colorVersion10Name: str
	"""Name of color version 10"""
	hdrMasteringOn: str
	"""'0' or '1'"""
	hdrMasteringLuminanceMax: str
	"""Mastering luminance max in nits, e.g. '1000'"""
	hdrDolbyControlsOn: str
	"""'0' or '1'"""
	hdrDolbyVersion: str
	"""'2.9' or '4.0'"""
	hdrDolbyAnalysisTuning: str
	"""'Legacy', 'Most Mapping', 'More Mapping', 'Balanced', 'Less Mapping' or 'Least Mapping'"""
	hdrDolbyMasterDisplay: str
	"""Dolby Vision master display name"""
	hdr10PlusControlsOn: str
	"""'0' or '1'"""
	audioOutputHasTimecode: str
	"""'0' or '1'"""
	videoMonitorFormat: str
	"""e.g. 'HD 1080i 50'"""
	videoMonitorUseStereoSDI: str
	"""'0' or '1'"""
	videoMonitorUse444SDI: str
	"""'0' or '1'"""
	videoMonitorSDIConfiguration: str
	"""'single_link', 'dual_link' or 'quad_link'"""
	videoDataLevels: str
	"""'Video' or 'Full'"""
	videoDataLevelsRetainSubblockAndSuperWhiteData: str
	"""'0' or '1'"""
	videoMonitorBitDepth: str
	"""e.g. '10'"""
	videoMonitorScaling: str
	"""'basic' or 'bilinear'"""
	videoMonitorUseHDROverHDMI: str
	"""'0' or '1'"""
	videoMonitorUseMatrixOverrideFor422SDI: str
	"""'0' or '1'"""
	videoMonitorMatrixOverrideFor422SDI: str
	"""'Rec.601', 'Rec.709' or 'Rec.2020'"""
	videoDeckFormat: str
	"""Read-only. e.g. 'HD 1080i 50'"""
	videoDeckUseStereoSDI: str
	"""'0' or '1'"""
	videoMonitorUseLevelA: str
	"""'0' or '1'"""
	videoDeckUse444SDI: str
	"""'0' or '1'"""
	videoDeckSDIConfiguration: str
	"""'single_link', 'dual_link' or 'quad_link'"""
	videoDeckBitDepth: str
	"""e.g. '10'"""
	videoDeckUseAudoEdit: str
	"""'0' or '1'"""
	videoDeckNonAutoEditFrames: str
	"""Number of frames, e.g. '30'"""
	videoDeckPrerollSec: str
	"""Preroll in seconds, e.g. '5'"""
	videoDeckOutputSyncSource: str
	"""Output sync source name"""
	videoDeckAdd32Pulldown: str
	"""'0' or '1'"""
	videoCaptureMode: str
	"""Capture mode, e.g. '0'"""
	videoCaptureFormat: str
	"""Read-only. e.g. 'HD 1080i 50'"""
	videoCaptureCodec: str
	"""Read-only. Capture codec name"""
	videoCaptureIngestHandles: str
	"""Number of handle frames, e.g. '0'"""
	audioCaptureNumChannels: str
	"""Number of audio channels, e.g. '2'"""
	videoPlayoutMode: str
	"""Playout mode, e.g. '0'"""
	videoPlayoutShowSourceTimecode: str
	"""'0' or '1'"""
	videoPlayoutShowLTC: str
	"""'0' or '1'"""
	videoPlayoutLTCFramesOffset: str
	"""LTC offset in frames, e.g. '0'"""
	videoPlayoutAudioFramesOffset: str
	"""Audio offset in frames, e.g. '0'"""
	audioPlayoutNumChannels: str
	"""Number of audio channels, e.g. '2'"""
	videoPlayoutBatchHeadDuration: str
	"""Head duration in frames, e.g. '0'"""
	videoPlayoutBatchTailDuration: str
	"""Tail duration in frames, e.g. '0'"""
	limitBroadcastSafeOn: str
	"""'0' or '1'"""
	limitBroadcastSafeLevels: str
	"""Broadcast safe levels, e.g. '-20 - 120'"""
	limitAudioMeterLUFS: str
	"""Loudness standard, e.g. '-23'"""
	limitAudioMeterLoudnessScale: str
	"""Loudness scale, e.g. '18_scale'"""
	limitAudioMeterAlignLevel: str
	"""Align level in dB, e.g. '-20'"""
	limitAudioMeterHighLevel: str
	"""High level in dB, e.g. '-10'"""
	limitAudioMeterLowLevel: str
	"""Low level in dB, e.g. '-30'"""
	limitAudioMeterDisplayMode: str
	"""Audio meter display mode"""
	limitSubtitleCPL: str
	"""Max characters per line, e.g. '60'"""
	limitSubtitleCaptionDurationSec: str
	"""Max caption duration in seconds, e.g. '3'"""
	superScale: int
	"""0=Auto, 1=none, 2=2x, 3=3x, 4=4x"""
	superScaleSharpness: str
	"""'0' or '1'"""
	superScaleNoiseReduction: str
	"""'0' or '1'"""
	superScaleSharpnessStrength: str
	"""Read-only. Sharpness strength, e.g. '0.5'"""
	superScaleNoiseReductionStrength: str
	"""Read-only. Noise reduction strength, e.g. '0.5'"""
	transcriptionLanguage: str
	"""Language code, e.g. 'en'"""
	speakerDetection: str
	"""'0' or '1'"""
	nodeStackLayers: str
	"""Number of node stack layers, e.g. '1'"""
	cloudProjectMediaLocation: str
	"""Cloud project media directory path"""
	projectMediaLocation: str
	"""Project media directory path"""

class ProjectSettingsPresetInfo(TypedDict, total=False):
	Name: str
	"""Preset name"""
	Width: int
	"""Resolution width, e.g. 1920"""
	Height: int
	"""Resolution height, e.g. 1080"""

class QuickExportRenderSettings(TypedDict, total=False):
	TargetDir: str
	"""Output directory path"""
	CustomName: str
	"""Custom output filename"""
	VideoQuality: int
	"""Bit rate limit (0 = automatic)"""
	EnableUpload: bool
	"""Enable direct upload for supported web presets (default: False)"""

class QuickExportRenderStatus(TypedDict, total=False):
	JobStatus: str
	"""'Render Complete', 'Render Failed', 'Render Cancelled', 'Upload Completed', 'Upload Failed' or 'Upload Cancelled'"""
	CompletionPercentage: int
	"""Completion percentage"""
	TimeTakenToRenderInMs: int
	"""Time taken to render (set on completion)"""
	Error: str
	"""Error details (set on failure)"""

class RenderJobInfo(TypedDict, total=False):
	JobId: str
	"""Unique job identifier"""
	RenderJobName: str
	"""Job display name"""
	TimelineName: str
	"""Source timeline name"""
	TargetDir: str
	"""Output directory path"""
	IsExportVideo: bool
	"""Video export enabled"""
	IsExportAudio: bool
	"""Audio export enabled"""
	FormatWidth: int
	"""Output width in pixels"""
	FormatHeight: int
	"""Output height in pixels"""
	FrameRate: str
	"""Frame rate, e.g. '23.976'"""
	PixelAspectRatio: float
	"""Pixel aspect ratio"""
	MarkIn: int
	"""Mark in frame"""
	MarkOut: int
	"""Mark out frame"""
	AudioBitDepth: int
	"""Audio bit depth, e.g. 16, 24"""
	AudioSampleRate: int
	"""Audio sample rate, e.g. 48000"""
	ExportAlpha: bool
	"""Alpha channel export enabled"""
	AlphaMode: int
	"""0 = Premultiplied, 1 = Straight (set when ExportAlpha is True)"""
	OutputFilename: str
	"""Output file name(s)"""
	RenderMode: str
	"""'Single clip' or 'Individual clips'"""
	PresetName: str
	"""Render preset name"""
	VideoFormat: str
	"""Video format name, e.g. 'QuickTime'"""
	VideoCodec: str
	"""Video codec name"""
	AudioCodec: str
	"""Audio codec name"""
	EncodingProfile: str
	"""Encoding profile, e.g. 'Main10'"""
	MultiPassEncode: bool
	"""Multi-pass encoding enabled"""
	NetworkOptimization: bool
	"""Network optimization enabled"""
	UploadStatus: str
	"""Upload status (if applicable)"""
	ClipStartFrame: int
	"""Clip start frame number"""
	TimelineStartTimecode: str
	"""Timeline start timecode, e.g. '01:00:00:00'"""
	ReplaceExistingFilesInPlace: bool
	"""Replace existing files in place"""

class RenderJobStatus(TypedDict, total=False):
	JobStatus: str
	"""Current status, one of 'Ready', 'Ready for background render', 'Rendering', 'Complete', 'Cancelled', 'Background Render Cancelled', 'Failed', 'Ready to remotely render' or 'Remote Render Cancelled'"""
	CompletionPercentage: int
	"""Completion percentage"""
	TimeTakenToRenderInMs: int
	"""Time taken to complete render, set for 'Complete' jobs"""
	EstimatedTimeRemainingInMs: int
	"""Time remaining to render, set for 'Rendering' jobs"""
	Error: str
	"""Error details, set for 'Failed' jobs"""

class RenderSettings(TypedDict, total=False):
	SelectAllFrames: bool
	"""Select all frames (MarkIn/MarkOut ignored when True)"""
	MarkIn: int
	"""Render mark in frame"""
	MarkOut: int
	"""Render mark out frame"""
	TargetDir: str
	"""Output directory path"""
	CustomName: str
	"""Custom output filename"""
	UseUniqueFilenames: bool
	"""Enable unique filenames"""
	UniqueFilenameStyle: int
	"""0 = Prefix, 1 = Suffix"""
	ExportVideo: bool
	"""Enable video export"""
	ExportAudio: bool
	"""Enable audio export"""
	FormatWidth: int
	"""Output width in pixels"""
	FormatHeight: int
	"""Output height in pixels"""
	FrameRate: float
	"""Frame rate, e.g. 23.976, 24.0"""
	PixelAspectRatio: str
	"""SD: '16_9' or '4_3'; other: 'square' or 'cinemascope'"""
	VideoQuality: int | str
	"""0 = automatic, int > 0 = bit rate, or 'Least'/'Low'/'Medium'/'High'/'Best'"""
	AudioFormat: str
	"""Audio format, e.g. 'mp3' (only if ExportVideo is False)"""
	AudioCodec: str
	"""Audio codec, e.g. 'aac'"""
	AudioBitDepth: int
	"""Audio bit depth, e.g. 16, 24"""
	AudioSampleRate: int
	"""Audio sample rate, e.g. 48000"""
	ColorSpaceTag: str
	"""Color space, e.g. 'Same as Project', 'AstroDesign'"""
	GammaTag: str
	"""Gamma, e.g. 'Same as Project', 'ACEScct'"""
	ExportAlpha: bool
	"""Enable alpha channel export"""
	AlphaMode: int
	"""0 = Premultiplied, 1 = Straight (requires ExportAlpha True)"""
	EncodingProfile: str
	"""Encoding profile, e.g. 'Main10' (H.264/H.265 only)"""
	MultiPassEncode: bool
	"""Multi-pass encoding (H.264 only)"""
	NetworkOptimization: bool
	"""Network optimization (QuickTime/MP4 only)"""
	ClipStartFrame: int
	"""Clip start frame number"""
	TimelineStartTimecode: str
	"""Timeline start timecode, e.g. '01:00:00:00'"""
	ReplaceExistingFilesInPlace: bool
	"""Replace existing files in place"""
	ExportSubtitle: bool
	"""Enable subtitle export"""
	SubtitleFormat: str
	"""'BurnIn', 'EmbeddedCaptions' or 'SeparateFile'"""
	UseFullExtents: bool
	"""Use full extents of clips"""
	AddFrameHandles: int
	"""Frame handles count >= 0 (ignored if UseFullExtents is True)"""
	DataBurnIn: str
	"""Data burn-in preset, e.g. 'Same as project', 'None'"""

class ResolutionInfo(TypedDict, total=False):
	Width: int
	"""Resolution width in pixels"""
	Height: int
	"""Resolution height in pixels"""

class SmartSwitchSettings(TypedDict, total=False):
	minEditDuration: float
	"""Minimum edit duration in seconds, 0.5 to 10.0 (default: 1.0)"""
	editChangeDelay: float
	"""Edit change delay in seconds, 0.0 to 2.0 (default: 0.3)"""
	isAutoDetectWideAngle: bool
	"""Auto-detect wide angle from analysis (default: True)"""
	analysisMode: SmartSwitchAnalysisMode
	"""Overrides isAutoDetectWideAngle"""
	wideAngleID: str
	"""Wide angle name, or 'None' to disable (used when isAutoDetectWideAngle is False)"""
	wideAngleFrequency: SmartSwitchWideAngleFrequency
	"""Default: resolve.SMART_SWITCH_WIDE_ANGLE_FREQ_MEDIUM"""
	isUseWideAngleForIntroOutro: bool
	"""Use wide angle for intro/outro (default: True)"""
	isUseWideAngleForSilence: bool
	"""Use wide angle for silence (default: True)"""
	switchOnVideoOnly: bool
	"""Switch on video only, not supported in adaptive/source mode (default: False)"""
	quality: SmartSwitchQuality
	"""Default: resolve.SMART_SWITCH_QUALITY_BETTER"""

class SpeechSettings(TypedDict, total=False):
	TextInput: str
	"""Input text to synthesize (max 350 chars)"""
	VoiceModel: str
	"""Voice model name, e.g. 'Female 1', 'Male 1', 'Custom Voice'"""
	CustomVoiceFile: str
	"""Full path to custom voice file (required when VoiceModel is 'Custom Voice')"""
	Speed: float
	"""Speed adjustment, -10.0 to 10.0"""
	Variation: float
	"""Variation amount, 0.0 to 1.0"""
	Pitch: float
	"""Pitch adjustment, -2.0 to 2.0"""
	GenerationID: int
	"""Generation ID for reproducibility (> 0)"""
	Filename: str
	"""Output filename"""
	AddToTimeline: bool
	"""Add generated audio to timeline (default: False)"""
	AudioTrack: int
	"""Target audio track number (0 = new track)"""

class SpeedOptions(TypedDict, total=False):
	Percentage: float
	"""Speed in percentage, e.g. 110.0 (0.0 = freeze frame)"""
	PitchCorrection: bool
	"""Pitch correction of linked audio (default: clip's existing state)"""
	StretchKeyframesToFit: bool
	"""Stretch keyframes to fit (default: False)"""
	RippleTimeline: bool
	"""Ripple timeline (default: False)"""

class TakeInfo(TypedDict, total=False):
	startFrame: int
	"""Take start frame"""
	endFrame: int
	"""Take end frame"""
	mediaPoolItem: 'MediaPoolItem'
	"""Take media pool item"""

class ThumbnailData(TypedDict, total=False):
	width: int
	"""Width in pixels"""
	height: int
	"""Height in pixels"""
	format: str
	"""Image format, e.g. 'RGB 8 bit'"""
	data: str
	"""Base64-encoded image data"""

class TimelineItemProperties(TypedDict, total=False):
	TransformEnabled: bool
	"""Enable/disable Transform filter section"""
	Pan: float
	"""-4.0*width to 4.0*width"""
	Tilt: float
	"""-4.0*height to 4.0*height"""
	ZoomX: float
	"""0.0 to 100.0"""
	ZoomY: float
	"""0.0 to 100.0"""
	ZoomGang: bool
	"""Gang ZoomX and ZoomY"""
	RotationAngle: float
	"""-360.0 to 360.0"""
	AnchorPointX: float
	"""-4.0*width to 4.0*width"""
	AnchorPointY: float
	"""-4.0*height to 4.0*height"""
	Pitch: float
	"""-1.5 to 1.5"""
	Yaw: float
	"""-1.5 to 1.5"""
	FlipX: bool
	"""Flip horizontally"""
	FlipY: bool
	"""Flip vertically"""
	CroppingEnabled: bool
	"""Enable/disable Cropping filter section"""
	CropLeft: float
	"""0.0 to width"""
	CropRight: float
	"""0.0 to width"""
	CropTop: float
	"""0.0 to height"""
	CropBottom: float
	"""0.0 to height"""
	CropSoftness: float
	"""-100.0 to 100.0"""
	CropRetain: bool
	"""Retain Image Position"""
	DynamicZoomEnabled: bool
	"""Enable/disable Dynamic Zoom filter section"""
	DynamicZoomEase: DynamicZoomEase
	CompositeEnabled: bool
	"""Enable/disable Composite filter section"""
	CompositeMode: CompositeMode
	"""See README.md section 'Looking up Timeline item properties'."""
	Opacity: float
	"""0.0 to 100.0"""
	LensCorrectionEnabled: bool
	"""Enable/disable Lens Correction filter section"""
	Distortion: float
	"""-1.0 to 1.0"""
	RetimeAndScalingEnabled: bool
	"""Enable/disable Retime and Scaling filter section"""
	RetimeProcess: RetimeProcess
	MotionEstimation: MotionEstimation
	Scaling: Scaling
	ResizeFilter: ResizeFilter
	AudioVolumeEnabled: bool
	"""Enable/disable audio volume filter"""
	AudioVolume: float
	"""-100.0 to 30.0 (dB)"""
	AudioPanEnabled: bool
	"""Enable/disable audio pan filter"""
	AudioPan: float
	"""-100.0 to 100.0"""
	AudioPitchEnabled: bool
	"""Enable/disable audio pitch filter"""
	AudioPitchSemiTones: float
	"""-24.0 to 24.0"""
	AudioPitchCents: float
	"""-100.0 to 100.0"""
	AudioVoiceIsolationEnabled: bool
	"""Enable/disable Voice Isolation [Active Timeline Only]"""
	AudioVoiceIsolationAmount: int
	"""0 to 100 (isolation strength) [Active Timeline Only]"""
	AudioDialogueLevelerEnabled: bool
	"""Enable/disable Dialogue Leveler [Active Timeline Only]"""
	AudioDialogueLevelerMode: DialogueLevelerMode
	"""[Active Timeline Only]"""
	AudioDialogueLevelerReduceLoudDialogue: bool
	"""Reduce loud dialogue [Active Timeline Only]"""
	AudioDialogueLevelerLiftSoftDialogue: bool
	"""Lift soft dialogue [Active Timeline Only]"""
	AudioDialogueLevelerBackgroundReduction: bool
	"""Enable background reduction [Active Timeline Only]"""
	AudioDialogueLevelerOutputGain: float
	"""0.0 to 6.0 (dB) [Active Timeline Only]"""

class TimelineSettings(TypedDict, total=False):
	useCustomSettings: str
	"""'0' or '1'"""
	timelineResolutionWidth: str
	"""e.g. '1920'"""
	timelineResolutionHeight: str
	"""e.g. '1080'"""
	timelinePixelAspectRatio: str
	"""e.g. 'square'"""
	timelineInputResMismatchBehavior: str
	"""e.g. 'scaleToCrop'"""
	timelineFrameRate: float | str
	"""Returned as a number, e.g. 23.976. Set as a string, e.g. '23.976' or '29.97 DF'"""
	timelineDropFrameTimecode: str
	"""'0' or '1'"""
	timelineInterlaceProcessing: str
	"""'0' or '1'"""
	timelineOutputResMatchTimelineRes: str
	"""'0' or '1'"""
	timelineOutputResolutionWidth: str
	"""e.g. '1920'"""
	timelineOutputResolutionHeight: str
	"""e.g. '1080'"""
	timelineOutputPixelAspectRatio: str
	"""e.g. 'square'"""
	timelineOutputResMismatchBehavior: str
	"""e.g. 'scaleToCrop'"""
	superScale: int
	"""0=Auto, 1=none, 2=2x, 3=3x, 4=4x"""
	videoMonitorFormat: str
	"""e.g. 'HD 1080i 50'"""
	videoMonitorUse444SDI: str
	"""'0' or '1'"""
	videoMonitorUseLevelA: str
	"""'0' or '1'"""
	videoMonitorUseStereoSDI: str
	"""'0' or '1'"""
	videoMonitorSDIConfiguration: str
	"""SDI config string"""
	videoDataLevels: str
	"""e.g. 'Auto'"""
	videoDataLevelsRetainSubblockAndSuperWhiteData: str
	"""'0' or '1'"""
	videoMonitorBitDepth: str
	"""e.g. '10'"""
	videoMonitorScaling: str
	"""e.g. 'bilinear'"""
	videoMonitorUseHDROverHDMI: str
	"""'0' or '1'"""
	videoMonitorUseMatrixOverrideFor422SDI: str
	"""'0' or '1'"""
	videoMonitorMatrixOverrideFor422SDI: str
	"""Matrix override value"""
	colorScienceMode: str
	"""e.g. 'davinciYRGBColorManagedv2'"""
	acesVersion: str
	"""e.g. 'aces_1.3'"""
	isAutoColorManage: str
	"""'0' or '1'"""
	rcmPresetMode: str
	"""Preset mode string"""
	separateColorSpaceAndGamma: str
	"""'0' or '1'"""
	colorSpaceTimeline: str
	"""e.g. 'Rec.709'"""
	colorSpaceTimelineGamma: str
	"""e.g. 'Gamma 2.4'"""
	colorAcesGamutCompressType: str
	"""Gamut compress type"""
	colorAcesODT: str
	"""ACES Output Device Transform"""
	colorAcesMidGray: str
	"""Mid gray value"""
	colorSpaceOutput: str
	"""Output color space"""
	colorSpaceOutputGamma: str
	"""Output gamma"""
	use203NitsReference: str
	"""'0' or '1'"""
	colorSpaceOutputGamutLimit: str
	"""Clipping color space"""
	colorAcesNodeLUTProcessingSpace: str
	"""Node LUT processing space"""
	hdrMasteringOn: str
	"""'0' or '1'"""
	hdrMasteringLuminanceMax: str
	"""Max luminance value"""
	outputDRT: str
	"""Output DRT string"""
	colorSpaceOutputToneMapping: str
	"""Tone mapping mode"""
	colorSpaceOutputGamutMapping: str
	"""Gamut mapping mode"""
	colorSpaceOutputGamutSaturationKnee: str
	"""Saturation knee value"""
	colorSpaceOutputGamutSaturationMax: str
	"""Saturation max value"""
	useInverseDRT: str
	"""'0' or '1'"""
	colorSpaceOutputToneLuminanceMax: str
	"""Tone luminance max"""
	outputDRTSatRolloffStart: str
	"""Saturation rolloff start"""
	outputDRTSatRolloffLimit: str
	"""Saturation rolloff limit"""
	inputDRT: str
	"""Input DRT string"""
	inputDRTSatRolloffStart: str
	"""Input saturation rolloff start"""
	inputDRTSatRolloffLimit: str
	"""Input saturation rolloff limit"""
	useCATransform: str
	"""'0' or '1'"""
	useColorSpaceAwareGradingTools: str
	"""'0' or '1'"""
	imageResizingGamma: str
	"""Image resizing gamma"""
	graphicsWhiteLevel: str
	"""Graphics white level"""
	timelineWorkingLuminance: str
	"""Working luminance value"""
	timelineWorkingLuminanceMode: str
	"""Working luminance mode"""
	hdrDolbyControlsOn: str
	"""'0' or '1'"""
	hdrDolbyVersion: str
	"""Dolby Vision version"""
	hdrDolbyMasterDisplay: str
	"""Dolby Vision master display"""
	hdrDolbyUseExternalCMU: str
	"""'0' or '1'"""
	hdr10PlusControlsOn: str
	"""'0' or '1'"""
	hdrVividControlsOn: str
	"""'0' or '1'"""
	hdrVividMasterDisplay: str
	"""HDR Vivid master display"""
	disableFusionToneMapping: str
	"""'0' or '1'"""

class Transcription(TypedDict, total=False):
	language: str
	"""Transcription language code"""
	segments: list[TranscriptionSegment]
	"""List of transcription segments"""

class TranscriptionSegment(TypedDict, total=False):
	start: str
	"""Start timecode, e.g. '01:00:02:05'"""
	end: str
	"""End timecode, e.g. '01:00:04:10'"""
	text: str
	"""Concatenated text of all words in segment; '(...)' denotes silence"""
	speaker: str | None
	"""Speaker name if detected, None otherwise"""
	words: list[TranscriptionWord]
	"""Individual words with timing"""

class TranscriptionWord(TypedDict, total=False):
	start: str
	"""Start timecode"""
	end: str
	"""End timecode"""
	text: str
	"""Word text; '(...)' denotes silence"""

class TransitionOptions(TypedDict, total=False):
	type: str
	"""Transition type name, e.g. 'Cross Dissolve'"""
	category: str
	"""Transition category: 'simple', 'fusion', 'ofx' or 'audio'"""
	position: str
	"""Edge of the item to attach the transition to: 'start' or 'end'"""
	alignment: str
	"""Placement relative to the edge: 'left', 'center' or 'right'"""
	duration: int | None
	"""Duration in frames (default: automatically calculated)"""

class VersionInfo(TypedDict, total=False):
	versionName: str
	"""Version name"""
	versionType: int
	"""Version type, 0 = local, 1 = remote"""

class VoiceIsolationState(TypedDict, total=False):
	isEnabled: bool
	"""Enabled flag"""
	amount: int
	"""Amount in range [0, 100]"""

class Resolve:
	"""The Resolve application: pages, the current project and application-wide presets."""
	KEYFRAME_MODE_ALL: KeyframeMode
	KEYFRAME_MODE_COLOR: KeyframeMode
	KEYFRAME_MODE_SIZING: KeyframeMode
	CLOUD_SETTING_PROJECT_NAME: CloudSettingKey
	CLOUD_SETTING_PROJECT_MEDIA_PATH: CloudSettingKey
	CLOUD_SETTING_IS_COLLAB: CloudSettingKey
	CLOUD_SETTING_SYNC_MODE: CloudSettingKey
	CLOUD_SETTING_IS_CAMERA_ACCESS: CloudSettingKey
	CLOUD_SYNC_NONE: CloudSyncMode
	CLOUD_SYNC_PROXY_ONLY: CloudSyncMode
	CLOUD_SYNC_PROXY_AND_ORIG: CloudSyncMode
	AUDIO_SYNC_MODE: AudioSyncSettingKey
	AUDIO_SYNC_CHANNEL_NUMBER: AudioSyncSettingKey
	AUDIO_SYNC_RETAIN_EMBEDDED_AUDIO: AudioSyncSettingKey
	AUDIO_SYNC_RETAIN_VIDEO_METADATA: AudioSyncSettingKey
	AUDIO_SYNC_WAVEFORM: AudioSyncMode
	AUDIO_SYNC_TIMECODE: AudioSyncMode
	AUDIO_SYNC_IN: AudioSyncMode
	AUDIO_SYNC_OUT: AudioSyncMode
	AUDIO_SYNC_MARKER: AudioSyncMode
	AUDIO_SYNC_CHANNEL_AUTOMATIC: AudioSyncChannel
	AUDIO_SYNC_CHANNEL_MIX: AudioSyncChannel
	MULTICAM_ANGLE_SYNC_IN: MulticamAngleSyncMode
	MULTICAM_ANGLE_SYNC_OUT: MulticamAngleSyncMode
	MULTICAM_ANGLE_SYNC_TIMECODE: MulticamAngleSyncMode
	MULTICAM_ANGLE_SYNC_AUDIO: MulticamAngleSyncMode
	MULTICAM_ANGLE_SYNC_MARKER: MulticamAngleSyncMode
	MULTICAM_ANGLE_NAME_SEQUENTIAL: MulticamAngleNameMode
	MULTICAM_ANGLE_NAME_ANGLE: MulticamAngleNameMode
	MULTICAM_ANGLE_NAME_CAMERA: MulticamAngleNameMode
	MULTICAM_ANGLE_NAME_CLIP: MulticamAngleNameMode
	MULTICAM_ANGLE_NAME_FILE: MulticamAngleNameMode
	MULTICAM_DETECT_BY_CAMERA_NUMBER: MulticamDetectMode
	MULTICAM_DETECT_BY_ANGLE: MulticamDetectMode
	MULTICAM_DETECT_BY_REEL_NUMBER: MulticamDetectMode
	MULTICAM_DETECT_BY_REEL_NAME: MulticamDetectMode
	MULTICAM_DETECT_BY_ROLL_CARD: MulticamDetectMode
	MULTICAM_DETECT_NONE: MulticamDetectMode
	MULTICAM_AUDIO_ADAPTIVE: MulticamAudioMode
	MULTICAM_AUDIO_SOURCE: MulticamAudioMode
	MULTICAM_AUDIO_REFERENCE: MulticamAudioMode
	MULTICAM_AUDIO_ALL: MulticamAudioMode
	CLOUD_SYNC_DEFAULT: CloudSyncStatus
	CLOUD_SYNC_DOWNLOAD_IN_QUEUE: CloudSyncStatus
	CLOUD_SYNC_DOWNLOAD_IN_PROGRESS: CloudSyncStatus
	CLOUD_SYNC_DOWNLOAD_SUCCESS: CloudSyncStatus
	CLOUD_SYNC_DOWNLOAD_FAIL: CloudSyncStatus
	CLOUD_SYNC_DOWNLOAD_NOT_FOUND: CloudSyncStatus
	CLOUD_SYNC_UPLOAD_IN_QUEUE: CloudSyncStatus
	CLOUD_SYNC_UPLOAD_IN_PROGRESS: CloudSyncStatus
	CLOUD_SYNC_UPLOAD_SUCCESS: CloudSyncStatus
	CLOUD_SYNC_UPLOAD_FAIL: CloudSyncStatus
	CLOUD_SYNC_UPLOAD_NOT_FOUND: CloudSyncStatus
	CLOUD_SYNC_SUCCESS: CloudSyncStatus
	MARKER_NONE: SlateMarkerColor
	MARKER_BLUE: SlateMarkerColor
	MARKER_CYAN: SlateMarkerColor
	MARKER_GREEN: SlateMarkerColor
	MARKER_YELLOW: SlateMarkerColor
	MARKER_RED: SlateMarkerColor
	MARKER_PINK: SlateMarkerColor
	MARKER_PURPLE: SlateMarkerColor
	MARKER_FUCHSIA: SlateMarkerColor
	MARKER_ROSE: SlateMarkerColor
	MARKER_LAVENDER: SlateMarkerColor
	MARKER_SKY: SlateMarkerColor
	MARKER_MINT: SlateMarkerColor
	MARKER_LEMON: SlateMarkerColor
	MARKER_SAND: SlateMarkerColor
	MARKER_COCOA: SlateMarkerColor
	MARKER_CREAM: SlateMarkerColor
	NORMALIZE_AUDIO_SET_LEVEL_RELATIVE: NormalizeAudioSetLevelMode
	NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT: NormalizeAudioSetLevelMode
	AUTO_ALIGN_CLIPS_USING_WAVEFORM: AutoAlignSyncUsing
	AUTO_ALIGN_CLIPS_USING_TIMECODE: AutoAlignSyncUsing
	AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_MIX: AutoAlignUseTrack
	AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_AUTOMATIC: AutoAlignUseTrack
	EXPORT_AAF: TimelineExportType
	EXPORT_DRT: TimelineExportType
	EXPORT_EDL: TimelineExportType
	EXPORT_FCP_7_XML: TimelineExportType
	EXPORT_FCPXML_1_8: TimelineExportType
	EXPORT_FCPXML_1_9: TimelineExportType
	EXPORT_FCPXML_1_10: TimelineExportType
	EXPORT_HDR_10_PROFILE_A: TimelineExportType
	EXPORT_HDR_10_PROFILE_B: TimelineExportType
	EXPORT_TEXT_CSV: TimelineExportType
	EXPORT_TEXT_TAB: TimelineExportType
	EXPORT_DOLBY_VISION_VER_2_9: TimelineExportType
	EXPORT_DOLBY_VISION_VER_4_0: TimelineExportType
	EXPORT_DOLBY_VISION_VER_5_1: TimelineExportType
	EXPORT_OTIO: TimelineExportType
	EXPORT_ALE: TimelineExportType
	EXPORT_ALE_CDL: TimelineExportType
	EXPORT_NONE: TimelineExportSubtype
	EXPORT_AAF_NEW: TimelineExportSubtype
	EXPORT_AAF_EXISTING: TimelineExportSubtype
	EXPORT_CDL: TimelineExportSubtype
	EXPORT_SDL: TimelineExportSubtype
	EXPORT_MISSING_CLIPS: TimelineExportSubtype
	SUBTITLE_LANGUAGE: SubtitleSettingKey
	SUBTITLE_CAPTION_PRESET: SubtitleSettingKey
	SUBTITLE_CHARS_PER_LINE: SubtitleSettingKey
	SUBTITLE_LINE_BREAK: SubtitleSettingKey
	SUBTITLE_GAP: SubtitleSettingKey
	AUTO_CAPTION_AUTO: AutoCaptionLanguage
	AUTO_CAPTION_MANDARIN_SIMPLIFIED: AutoCaptionLanguage
	AUTO_CAPTION_DUTCH: AutoCaptionLanguage
	AUTO_CAPTION_ENGLISH: AutoCaptionLanguage
	AUTO_CAPTION_FINNISH: AutoCaptionLanguage
	AUTO_CAPTION_FRENCH: AutoCaptionLanguage
	AUTO_CAPTION_GERMAN: AutoCaptionLanguage
	AUTO_CAPTION_HINDI: AutoCaptionLanguage
	AUTO_CAPTION_INDONESIAN: AutoCaptionLanguage
	AUTO_CAPTION_ITALIAN: AutoCaptionLanguage
	AUTO_CAPTION_JAPANESE: AutoCaptionLanguage
	AUTO_CAPTION_KOREAN: AutoCaptionLanguage
	AUTO_CAPTION_MALAY: AutoCaptionLanguage
	AUTO_CAPTION_NORWEGIAN: AutoCaptionLanguage
	AUTO_CAPTION_POLISH: AutoCaptionLanguage
	AUTO_CAPTION_PORTUGUESE: AutoCaptionLanguage
	AUTO_CAPTION_ROMANIAN: AutoCaptionLanguage
	AUTO_CAPTION_RUSSIAN: AutoCaptionLanguage
	AUTO_CAPTION_SPANISH: AutoCaptionLanguage
	AUTO_CAPTION_SWEDISH: AutoCaptionLanguage
	AUTO_CAPTION_TURKISH: AutoCaptionLanguage
	AUTO_CAPTION_VIETNAMESE: AutoCaptionLanguage
	AUTO_CAPTION_TAMIL: AutoCaptionLanguage
	AUTO_CAPTION_THAI: AutoCaptionLanguage
	AUTO_CAPTION_DANISH: AutoCaptionLanguage
	AUTO_CAPTION_MANDARIN_TRADITIONAL: AutoCaptionLanguage
	AUTO_CAPTION_SUBTITLE_DEFAULT: AutoCaptionPreset
	AUTO_CAPTION_TELETEXT: AutoCaptionPreset
	AUTO_CAPTION_NETFLIX: AutoCaptionPreset
	AUTO_CAPTION_LINE_SINGLE: AutoCaptionLineBreak
	AUTO_CAPTION_LINE_DOUBLE: AutoCaptionLineBreak
	DLB_BLEND_SHOTS: DolbyVisionAnalysisType
	DYNAMIC_ZOOM_EASE_LINEAR: DynamicZoomEase
	DYNAMIC_ZOOM_EASE_IN: DynamicZoomEase
	DYNAMIC_ZOOM_EASE_OUT: DynamicZoomEase
	DYNAMIC_ZOOM_EASE_IN_AND_OUT: DynamicZoomEase
	COMPOSITE_NORMAL: CompositeMode
	COMPOSITE_ADD: CompositeMode
	COMPOSITE_SUBTRACT: CompositeMode
	COMPOSITE_DIFF: CompositeMode
	COMPOSITE_MULTIPLY: CompositeMode
	COMPOSITE_SCREEN: CompositeMode
	COMPOSITE_OVERLAY: CompositeMode
	COMPOSITE_HARDLIGHT: CompositeMode
	COMPOSITE_SOFTLIGHT: CompositeMode
	COMPOSITE_DARKEN: CompositeMode
	COMPOSITE_LIGHTEN: CompositeMode
	COMPOSITE_COLOR_DODGE: CompositeMode
	COMPOSITE_COLOR_BURN: CompositeMode
	COMPOSITE_EXCLUSION: CompositeMode
	COMPOSITE_HUE: CompositeMode
	COMPOSITE_SATURATE: CompositeMode
	COMPOSITE_COLORIZE: CompositeMode
	COMPOSITE_LUMA_MASK: CompositeMode
	COMPOSITE_DIVIDE: CompositeMode
	COMPOSITE_LINEAR_DODGE: CompositeMode
	COMPOSITE_LINEAR_BURN: CompositeMode
	COMPOSITE_LINEAR_LIGHT: CompositeMode
	COMPOSITE_VIVID_LIGHT: CompositeMode
	COMPOSITE_PIN_LIGHT: CompositeMode
	COMPOSITE_HARD_MIX: CompositeMode
	COMPOSITE_LIGHTER_COLOR: CompositeMode
	COMPOSITE_DARKER_COLOR: CompositeMode
	COMPOSITE_FOREGROUND: CompositeMode
	COMPOSITE_ALPHA: CompositeMode
	COMPOSITE_INVERTED_ALPHA: CompositeMode
	COMPOSITE_LUM: CompositeMode
	COMPOSITE_INVERTED_LUM: CompositeMode
	RETIME_USE_PROJECT: RetimeProcess
	RETIME_NEAREST: RetimeProcess
	RETIME_FRAME_BLEND: RetimeProcess
	RETIME_OPTICAL_FLOW: RetimeProcess
	MOTION_EST_USE_PROJECT: MotionEstimation
	MOTION_EST_STANDARD_FASTER: MotionEstimation
	MOTION_EST_STANDARD_BETTER: MotionEstimation
	MOTION_EST_ENHANCED_FASTER: MotionEstimation
	MOTION_EST_ENHANCED_BETTER: MotionEstimation
	MOTION_EST_SPEED_WARP_FASTER: MotionEstimation
	MOTION_EST_SPEED_WARP_BETTER: MotionEstimation
	MOTION_EST_METAL: MotionEstimation
	SCALE_USE_PROJECT: Scaling
	SCALE_CROP: Scaling
	SCALE_FIT: Scaling
	SCALE_FILL: Scaling
	SCALE_STRETCH: Scaling
	RESIZE_FILTER_USE_PROJECT: ResizeFilter
	RESIZE_FILTER_SHARPER: ResizeFilter
	RESIZE_FILTER_SMOOTHER: ResizeFilter
	RESIZE_FILTER_BICUBIC: ResizeFilter
	RESIZE_FILTER_BILINEAR: ResizeFilter
	RESIZE_FILTER_BESSEL: ResizeFilter
	RESIZE_FILTER_BOX: ResizeFilter
	RESIZE_FILTER_CATMULL_ROM: ResizeFilter
	RESIZE_FILTER_CUBIC: ResizeFilter
	RESIZE_FILTER_GAUSSIAN: ResizeFilter
	RESIZE_FILTER_LANCZOS: ResizeFilter
	RESIZE_FILTER_MITCHELL: ResizeFilter
	RESIZE_FILTER_NEAREST_NEIGHBOR: ResizeFilter
	RESIZE_FILTER_QUADRATIC: ResizeFilter
	RESIZE_FILTER_SINC: ResizeFilter
	RESIZE_FILTER_LINEAR: ResizeFilter
	CACHE_AUTO_ENABLED: CacheMode
	CACHE_DISABLED: CacheMode
	CACHE_ENABLED: CacheMode
	DIALOGUE_LEVELER_MODE_ALLOW_WIDER_DYNAMICS: DialogueLevelerMode
	DIALOGUE_LEVELER_MODE_OPTIMIZE_MODERATE_LEVELS: DialogueLevelerMode
	DIALOGUE_LEVELER_MODE_MORE_LIFT_FOR_LOW_LEVELS: DialogueLevelerMode
	DIALOGUE_LEVELER_MODE_LIFT_SOFT_WHISPERY_SOURCES: DialogueLevelerMode
	FLATTEN_MULTICAM_COPY_GRADE: FlattenMulticamGrade
	FLATTEN_MULTICAM_RETAIN_GRADE_FROM_ANGLE: FlattenMulticamGrade
	EXPORT_LUT_17PTCUBE: ExportLutType
	EXPORT_LUT_33PTCUBE: ExportLutType
	EXPORT_LUT_65PTCUBE: ExportLutType
	EXPORT_LUT_PANASONICVLUT: ExportLutType
	SMART_SWITCH_QUALITY_FASTER: SmartSwitchQuality
	SMART_SWITCH_QUALITY_BETTER: SmartSwitchQuality
	SMART_SWITCH_WIDE_ANGLE_FREQ_LOW: SmartSwitchWideAngleFrequency
	SMART_SWITCH_WIDE_ANGLE_FREQ_MEDIUM: SmartSwitchWideAngleFrequency
	SMART_SWITCH_WIDE_ANGLE_FREQ_HIGH: SmartSwitchWideAngleFrequency
	SMART_SWITCH_ANALYSIS_MODE_NONE: SmartSwitchAnalysisMode
	SMART_SWITCH_ANALYSIS_MODE_DETECT_WIDE_ANGLE: SmartSwitchAnalysisMode
	SMART_SWITCH_ANALYSIS_MODE_AUDIO_ONLY: SmartSwitchAnalysisMode
	CLONE_CHECKSUM_TYPE_NONE: CloneChecksumType
	CLONE_CHECKSUM_TYPE_FILESIZE: CloneChecksumType
	CLONE_CHECKSUM_TYPE_CRC32: CloneChecksumType
	CLONE_CHECKSUM_TYPE_MD5: CloneChecksumType
	CLONE_CHECKSUM_TYPE_SHA256: CloneChecksumType
	CLONE_CHECKSUM_TYPE_SHA512: CloneChecksumType
	CLONE_CHECKSUM_TYPE_XXH_64: CloneChecksumType
	def GetProjectManager(self) -> ProjectManager:
		"""Returns the project manager object for currently open database"""
		...
	def GetMediaStorage(self) -> MediaStorage:
		"""Returns the media storage object to query and act on media locations"""
		...
	def Fusion(self) -> Fusion:
		"""Starting point for Fusion scripts"""
		...
	def GetCurrentProject(self) -> Project:
		"""Returns the currently loaded Resolve project"""
		...
	def GetCurrentTimeline(self) -> Timeline:
		"""Returns the currently loaded timeline"""
		...
	def GetMediaPool(self) -> MediaPool:
		"""Returns the MediaPool object for the current project"""
		...
	def GetGallery(self) -> Gallery:
		"""Returns the Gallery object for the current project"""
		...
	def OpenPage(self, pageName: str) -> bool:
		"""Switches DaVinci Resolve Page. pageName can be: 'media', 'photo', 'cut', 'edit', 'fusion', 'color', 'fairlight', 'deliver'"""
		...
	def GetCurrentPage(self) -> str:
		"""Returns current DaVinci Resolve Page: 'media', 'photo', 'cut', 'edit', 'fusion', 'color', 'fairlight', 'deliver'"""
		...
	def SetHighPriority(self, highPriority: bool) -> bool:
		"""Sets the script execution priority to high or normal"""
		...
	def GetVersion(self) -> list[int | str]:
		"""Returns list of product version fields in [major, minor, patch, build, suffix] format"""
		...
	def GetVersionString(self) -> str:
		"""Returns product version in major.minor.patch[suffix].build format"""
		...
	def GetProductName(self) -> str:
		"""Returns product name"""
		...
	def IsStudio(self) -> bool:
		"""Returns whether this is the Studio version of the product"""
		...
	def GetLayoutPresetList(self) -> list[str]:
		"""Returns a list of available UI layout preset names"""
		...
	def LoadLayoutPreset(self, presetName: str) -> bool:
		"""Loads UI layout from saved preset"""
		...
	def UpdateLayoutPreset(self, presetName: str) -> bool:
		"""Overwrites preset named 'presetName' with current UI layout"""
		...
	def ExportLayoutPreset(self, presetName: str, presetFilePath: str) -> bool:
		"""Exports preset named 'presetName' to path 'presetFilePath'"""
		...
	def DeleteLayoutPreset(self, presetName: str) -> bool:
		"""Deletes preset named 'presetName'"""
		...
	def SaveLayoutPreset(self, presetName: str) -> bool:
		"""Saves current UI layout as a preset"""
		...
	def ImportLayoutPreset(self, presetFilePath: str, presetName: str | None = None) -> bool:
		"""Imports UI layout preset from file"""
		...
	def Quit(self) -> bool:
		"""Quits the Resolve App"""
		...
	def ImportRenderPreset(self, presetPath: str) -> bool:
		"""Import a render preset from a file and select it"""
		...
	def ExportRenderPreset(self, presetName: str, exportPath: str) -> bool:
		"""Export a render preset to a file"""
		...
	def GetBurnInPresetList(self) -> list[str]:
		"""Returns a list of available data burn in preset names"""
		...
	def DeleteBurnInPreset(self, presetName: str) -> bool:
		"""Deletes the named data burn in preset"""
		...
	def ImportBurnInPreset(self, presetPath: str) -> bool:
		"""Import a data burn in preset from a file"""
		...
	def ExportBurnInPreset(self, presetName: str, exportPath: str) -> bool:
		"""Export a data burn in preset to a file"""
		...
	def GetKeyboardPresetList(self) -> list[str]:
		"""Returns a list of available keyboard preset names"""
		...
	def LoadKeyboardPreset(self, presetName: str) -> bool:
		"""Loads the named keyboard preset"""
		...
	def DeleteKeyboardPreset(self, presetName: str) -> bool:
		"""Deletes the named keyboard preset"""
		...
	def GetCurrentKeyboardPreset(self) -> str:
		"""Returns the name of the currently active keyboard preset"""
		...
	def ImportKeyboardPreset(self, filePath: str, presetName: str | None = None) -> bool:
		"""Imports a keyboard preset from file. Uses file base name as preset name if not specified."""
		...
	def ExportKeyboardPreset(self, presetName: str, exportPath: str) -> bool:
		"""Exports the named keyboard preset to the specified file path"""
		...
	def GetKeyframeMode(self) -> int:
		"""Returns the currently set keyframe mode, one of the resolve.KEYFRAME_MODE_* constants. Color Page only."""
		...
	def SetKeyframeMode(self, keyframeMode: KeyframeMode) -> bool:
		"""Set keyframe mode"""
		...
	def GetFairlightPresets(self) -> list[str]:
		"""Returns a list of Fairlight presets by name"""
		...
	def DisableBackgroundTasksForCurrentResolveSession(self):
		"""Disables all background tasks for current Resolve session"""
		...
	def ValidateDCTL(self, dctlSource: str) -> str | None:
		"""Validates DCTL source code. Returns None on success, error string on failure."""
		...
	def EncryptDCTL(self, inputPath: str, encryptDCTLOptions: EncryptDCTLOptions | None = None) -> bool:
		"""Encrypts the DCTL at inputPath and writes it to an output folder."""
		...
	def GetUserPreferencesPresetList(self) -> list[str]:
		"""Returns a list of available user preferences preset names"""
		...
	def LoadUserPreferencesPreset(self, presetName: str) -> bool:
		"""Loads the named user preferences preset"""
		...
	def SaveUserPreferencesPreset(self, presetName: str) -> bool:
		"""Saves current user preferences as a preset with the given name"""
		...
	def DeleteUserPreferencesPreset(self, presetName: str) -> bool:
		"""Deletes the named user preferences preset"""
		...
	def ImportUserPreferencesPreset(self, filePath: str, presetName: str | None = None) -> bool:
		"""Imports a user preferences preset from file. Uses file base name as preset name if not specified."""
		...
	def ExportUserPreferencesPreset(self, presetName: str, exportPath: str) -> bool:
		"""Exports the named user preferences preset to the specified file path"""
		...

class ProjectManager:
	"""Creates, loads and organizes projects, project folders and databases. See README.md section 'Cloud Projects Settings'."""
	def LoadProject(self, projectName: str) -> Project | None:
		"""Loads and returns a project. Returns None if project was not found."""
		...
	def CreateProject(self, projectName: str, mediaLocationPath: str | None = None) -> Project | None:
		"""Creates and returns a project. Returns None if projectName exists."""
		...
	def DeleteProject(self, projectName: str) -> bool:
		"""Delete project in the current folder. Project must not be currently loaded."""
		...
	def SaveProject(self) -> bool:
		"""Saves the currently loaded project with its own name."""
		...
	def GetCurrentProject(self) -> Project:
		"""Returns the currently loaded Resolve project"""
		...
	def CreateFolder(self, folderName: str) -> bool:
		"""Creates a folder. Returns False if it already existed."""
		...
	def GetProjectListInCurrentFolder(self) -> list[str]:
		"""Returns a list of project names in current folder"""
		...
	def GetFolderListInCurrentFolder(self) -> list[str]:
		"""Returns a list of folder names in current folder"""
		...
	def GotoRootFolder(self) -> bool:
		"""Opens root folder in database"""
		...
	def GotoParentFolder(self) -> bool:
		"""Opens parent folder of current folder in database. Returns False if current folder has no parent."""
		...
	def OpenFolder(self, folderName: str) -> bool:
		"""Opens folder"""
		...
	def ImportProject(self, filePath: str, projectName: str | None = None) -> bool:
		"""Imports a project from the file"""
		...
	def ExportProject(self, projectName: str, filePath: str, withStillsAndLUTs = True) -> bool:
		"""Exports project to a file."""
		...
	def ArchiveProject(self, projectName: str, filePath: str, isArchiveSrcMedia = True, isArchiveRenderCache = True, isArchiveProxyMedia = False) -> bool:
		"""Archives project to a file"""
		...
	def RestoreProject(self, filePath: str, projectName: str | None = None) -> bool:
		"""Restores a project from the file"""
		...
	def GetProjectLastModifiedTime(self, projectName: str) -> int:
		"""Returns the last modified time of the project as an epoch timestamp"""
		...
	def GetProjectAttributesInCurrentFolder(self) -> dict[str, ProjectAttributes]:
		"""Returns a dict of project names mapped to their attributes (lastModifiedDate, creationDate, notes, liveCollaborationMode) for all projects in the current folder"""
		...
	def CloseProject(self, project: Project) -> bool:
		"""Closes the specified project without saving"""
		...
	def GetCurrentFolder(self) -> str:
		"""Returns the current folder name"""
		...
	def DeleteFolder(self, folderName: str) -> bool:
		"""Deletes the specified folder"""
		...
	def GetCurrentDatabase(self) -> DatabaseInfo:
		"""Returns a dictionary (with keys 'DbType', 'DbName' and optional 'IpAddress') corresponding to the current database connection"""
		...
	def GetDatabaseList(self) -> list[DatabaseInfo]:
		"""Returns a list of dictionary items (with keys 'DbType', 'DbName' and optional 'IpAddress') corresponding to all the databases added to Resolve"""
		...
	def SetCurrentDatabase(self, dbInfo: DatabaseInfo) -> bool:
		"""Switches current database connection to the database specified by the keys below, and closes any open project"""
		...
	def LoadCloudProject(self, cloudSettings: CloudSettings) -> Project | None:
		"""Loads and returns a cloud project with the given cloud settings. Returns None if not found"""
		...
	def CreateCloudProject(self, cloudSettings: CloudSettings) -> Project | None:
		"""Creates and returns a cloud project"""
		...
	def ImportCloudProject(self, filePath: str, cloudSettings: CloudSettings) -> bool:
		"""Imports a cloud project from the file path with given cloud settings"""
		...
	def RestoreCloudProject(self, folderPath: str, cloudSettings: CloudSettings) -> bool:
		"""Restores a cloud project from the folder path with given cloud settings"""
		...

class Project:
	"""A project: timelines, settings, presets and render jobs. See README.md section 'Looking up Project and Clip properties'."""
	def GetMediaPool(self) -> MediaPool:
		"""Returns the MediaPool object"""
		...
	def GetCurrentTimeline(self) -> Timeline:
		"""Returns the currently loaded timeline"""
		...
	def SetCurrentTimeline(self, timeline: Timeline) -> bool:
		"""Sets given timeline as current timeline for the project"""
		...
	def GetTimelineCount(self) -> int:
		"""Returns the number of timelines in the project"""
		...
	def GetTimelineByIndex(self, idx: int) -> Timeline | None:
		"""Returns timeline at the given index, 1 <= idx <= project.GetTimelineCount()"""
		...
	def GetGallery(self) -> Gallery:
		"""Returns the Gallery object"""
		...
	def GetName(self) -> str:
		"""Returns project name"""
		...
	def SetName(self, projectName: str) -> bool:
		"""Sets project name if given projectName is unique"""
		...
	def GetProjectSettingsPresetList(self) -> list[ProjectSettingsPresetInfo]:
		"""Returns a list of project settings presets and their information"""
		...
	def SetProjectSettingsPreset(self, presetName: str) -> bool:
		"""Sets project settings preset by given name into project"""
		...
	def DeleteProjectSettingsPreset(self, presetName: str) -> bool:
		"""Deletes the project settings preset with the given name"""
		...
	def SaveCurrentProjectSettingsAsNewPreset(self, presetName: str) -> bool:
		"""Saves the current project settings as a new preset with the given name"""
		...
	def UpdateProjectSettingsPreset(self, presetName: str) -> bool:
		"""Updates the given project settings preset with current settings"""
		...
	def ExportProjectSettingsPreset(self, presetName: str, exportPath: str) -> bool:
		"""Exports the given project settings preset to the specified file path"""
		...
	def ImportProjectSettingsPreset(self, presetFilePath: str, presetName: str | None = None) -> bool:
		"""Imports a project settings preset from file. Uses file base name as preset name if not specified."""
		...
	def GetRenderJobList(self) -> list[RenderJobInfo]:
		"""Returns a list of render jobs and their information"""
		...
	def GetRenderPresetList(self) -> list[str]:
		"""Returns a list of render preset names"""
		...
	def LoadRenderPreset(self, presetName: str) -> bool:
		"""Loads a render preset by name"""
		...
	def SaveAsNewRenderPreset(self, presetName: str) -> bool:
		"""Saves current render settings as a new preset with the given name"""
		...
	def DeleteRenderPreset(self, presetName: str) -> bool:
		"""Deletes given render preset"""
		...
	def UpdateRenderPreset(self, presetName: str) -> bool:
		"""Updates given render preset with current render settings"""
		...
	def SetQuickExportEnabledForRenderPreset(self, presetName: str, isEnabled: bool) -> bool:
		"""Enables or disables quick export for the named render preset"""
		...
	def StartRendering(self, jobIds: list[str], isInteractiveMode = False) -> bool:
		"""Starts rendering jobs indicated by the input job ids"""
		...
	def StopRendering(self):
		"""Stops any current render processes"""
		...
	def IsRenderingInProgress(self) -> bool:
		"""Returns True if a rendering is in progress"""
		...
	def AddRenderJob(self) -> str:
		"""Adds a render job based on current render settings to the render queue"""
		...
	def DeleteRenderJob(self, jobId: str) -> bool:
		"""Deletes render job for input job id"""
		...
	def DeleteAllRenderJobs(self) -> bool:
		"""Deletes all render jobs in the queue"""
		...
	def SetRenderSettings(self, settings: RenderSettings) -> bool:
		"""Sets given settings for rendering"""
		...
	def GetRenderResolutions(self, format: str | None = None, codec: str | None = None) -> list[ResolutionInfo]:
		"""Returns list of resolutions applicable for the given render format and codec"""
		...
	def GetSettings(self) -> ProjectSettings:
		"""Returns a dict with all project settings. See README.md section 'Looking up Project and Clip properties'."""
		...
	def SetSettings(self, settings: ProjectSettings) -> bool:
		"""Sets the project settings with specified dict of setting names and values. See README.md section 'Looking up Project and Clip properties'."""
		...
	def GetRenderJobStatus(self, jobId: str) -> RenderJobStatus:
		"""Returns a dict with job status and completion percentage"""
		...
	def GetQuickExportRenderPresets(self) -> list[str]:
		"""Returns a list of quick export render presets"""
		...
	def RenderWithQuickExport(self, quickExportPresetName: str, presetInfo: QuickExportRenderSettings) -> QuickExportRenderStatus:
		"""Renders current timeline with quick export preset"""
		...
	def GetRenderFormats(self) -> dict:
		"""Returns a dict (format -> file extension) of available render formats"""
		...
	def GetAudioRenderFormats(self) -> dict:
		"""Returns a dict (format -> file extension) of available audio render formats"""
		...
	def GetRenderCodecs(self, renderFormatFileExtension: str) -> dict:
		"""Returns a dict (codec description -> codec name) of available codecs"""
		...
	def GetAudioRenderCodecs(self, audioRenderFormatFileExtension: str) -> dict:
		"""Returns a dict (codec description -> codec name) of available audio codecs for the given format"""
		...
	def GetCurrentRenderFormatAndCodec(self) -> dict[str, str]:
		"""Returns a dict with currently selected format and render codec"""
		...
	def SetCurrentRenderFormatAndCodec(self, format: str, codec: str) -> bool:
		"""Sets given render format and render codec as options for rendering"""
		...
	def GetCurrentRenderMode(self) -> int:
		"""Returns the render mode: 0 - Individual clips, 1 - Single clip"""
		...
	def SetCurrentRenderMode(self, renderMode: int) -> bool:
		"""Sets the render mode: 0 for Individual clips, 1 for Single clip"""
		...
	def RefreshLUTList(self) -> bool:
		"""Refreshes LUT List"""
		...
	def GetUniqueId(self) -> str:
		"""Returns a unique ID for the project item"""
		...
	def InsertAudioToCurrentTrackAtPlayhead(self, mediaPath: str, startOffsetInSamples: int, durationInSamples: int) -> bool:
		"""Inserts the media with startOffset and duration in samples to the current track at the playhead"""
		...
	def LoadBurnInPreset(self, presetName: str) -> bool:
		"""Loads user defined data burn in preset"""
		...
	def ExportCurrentFrameAsStill(self, filePath: str) -> bool:
		"""Exports current frame as still to supplied filePath"""
		...
	def GetColorGroupsList(self) -> list[ColorGroup]:
		"""Returns a list of all group objects in the timeline"""
		...
	def AddColorGroup(self, groupName: str) -> ColorGroup:
		"""Creates a new ColorGroup with unique groupName"""
		...
	def DeleteColorGroup(self, colorGroup: ColorGroup) -> bool:
		"""Deletes the given ColorGroup and sets clips to ungrouped"""
		...
	def ApplyFairlightPresetToCurrentTimeline(self, presetName: str) -> bool:
		"""Applies Fairlight preset to current timeline"""
		...
	def ResetIntellisearchAnalysis(self) -> bool:
		"""Resets intellisearch analysis for the project"""
		...
	def GenerateSpeech(self, speechSettings: SpeechSettings) -> MediaPoolItem:
		"""Generates speech for given speechSettings dict"""
		...

class MediaPool:
	"""The media pool of a project: its folders, its clips and the timelines created from them."""
	def AddSubFolder(self, folder: Folder, name: str) -> Folder:
		"""Adds new subfolder under specified Folder object with the given name"""
		...
	def GetCurrentFolder(self) -> Folder:
		"""Returns currently selected Folder"""
		...
	def RefreshFolders(self) -> bool:
		"""Updates the folders in collaboration mode"""
		...
	def SetCurrentFolder(self, folder: Folder) -> bool:
		"""Sets current folder by given Folder"""
		...
	def GetRootFolder(self) -> Folder:
		"""Returns root Folder of Media Pool"""
		...
	def CreateTimelineFromClips(self, name: str, clipInfos: list[CreateTimelineClipInfo]) -> Timeline:
		"""Creates new timeline with specified name, and appends the specified MediaPoolItem objects"""
		...
	def AppendToTimeline(self, clipInfos: list[AppendClipInfo]) -> list[TimelineItem]:
		"""Appends specified MediaPoolItem objects in the current timeline. Returns the list of appended timelineItems"""
		...
	def CreateEmptyTimeline(self, name: str) -> Timeline:
		"""Adds new timeline with given name"""
		...
	def ImportTimelineFromFile(self, filePath: str, importOptions: ImportOptions | None = None) -> Timeline:
		"""Creates timeline based on parameters within given file (AAF/EDL/XML/FCPXML/DRT/ADL/OTIO) and optional importOptions dict"""
		...
	def DeleteTimelines(self, timelines: list[Timeline]) -> bool:
		"""Deletes specified timelines in the media pool"""
		...
	def ExportMetadata(self, fileName: str, clips: list[MediaPoolItem] | None = None) -> bool:
		"""Exports metadata of specified clips to 'fileName' in CSV format. If no clips are specified, all clips from media pool will be used"""
		...
	def DeleteClips(self, clips: list[MediaPoolItem]) -> bool:
		"""Deletes specified clips or timeline mattes in the media pool"""
		...
	def ImportFolderFromFile(self, filePath: str, sourceClipsPath: str | None = None) -> bool:
		"""Imports a DRB folder from the given file path"""
		...
	def DeleteFolders(self, subfolders: list[Folder]) -> bool:
		"""Deletes specified subfolders in the media pool"""
		...
	def MoveClips(self, clips: list[MediaPoolItem], targetFolder: Folder) -> bool:
		"""Moves specified clips to target folder"""
		...
	def MoveFolders(self, folders: list[Folder], targetFolder: Folder) -> bool:
		"""Moves specified folders to target folder"""
		...
	def GetClipMatteList(self, mediaPoolItem: MediaPoolItem) -> list[str]:
		"""Get mattes for specified MediaPoolItem, as a list of paths to the matte files"""
		...
	def GetTimelineMatteList(self, folder: Folder) -> list[MediaPoolItem]:
		"""Get mattes in specified Folder, as list of MediaPoolItems"""
		...
	def DeleteClipMattes(self, mediaPoolItem: MediaPoolItem, paths: list[str]) -> bool:
		"""Delete mattes based on their file paths, for specified MediaPoolItem"""
		...
	def RelinkClips(self, clips: list[MediaPoolItem], folderPath: str) -> bool:
		"""Update the folder location of specified media pool clips with the specified folder path"""
		...
	def UnlinkClips(self, clips: list[MediaPoolItem]) -> bool:
		"""Unlink specified media pool clips"""
		...
	def ImportMedia(self, clipInfos: list[ImportClipInfo]) -> list[MediaPoolItem]:
		"""Imports specified file/folder paths into current Media Pool folder. Returns a list of the MediaPoolItems created"""
		...
	def GetUniqueId(self) -> str:
		"""Returns a unique ID for the media pool"""
		...
	def CreateStereoClip(self, leftMediaPoolItem: MediaPoolItem, rightMediaPoolItem: MediaPoolItem) -> MediaPoolItem:
		"""Takes in two existing media pool items and creates a new 3D stereoscopic media pool entry replacing the input media"""
		...
	def CreateMulticamClip(self, clips: list[MediaPoolItem], multicamOptions: MulticamOptions) -> list[MediaPoolItem]:
		"""Creates Multicam clips from the specified MediaPoolItems and options"""
		...
	def AutoSyncAudio(self, mediaPoolItems: list[MediaPoolItem], audioSyncSettings: AudioSyncSettings) -> bool:
		"""Syncs audio for specified MediaPoolItems. The list must contain at least one video and one audio clip."""
		...
	def GetSelectedClips(self) -> list[MediaPoolItem]:
		"""Returns the current selected MediaPoolItems"""
		...
	def SetSelectedClip(self, mediaPoolItem: MediaPoolItem) -> bool:
		"""Sets the selected MediaPoolItem to the given MediaPoolItem"""
		...

class MediaPoolItem:
	"""A clip in the media pool. See README.md section 'Looking up Project and Clip properties'."""
	def GetName(self) -> str:
		"""Returns the clip name."""
		...
	def SetName(self, name: str) -> bool:
		"""Sets the clip's name to name(string)."""
		...
	def GetTimeline(self) -> Timeline:
		"""Returns the timeline object if the mpItem is a timeline clip"""
		...
	def GetMetadata(self, metadataType: str | None = None) -> str | dict:
		"""Returns the metadata value for the key 'metadataType'. If no argument is specified, a dict of all set metadata properties is returned."""
		...
	def SetMetadata(self, metadata: dict) -> bool:
		"""Sets the item metadata with specified dict of key-value pairs"""
		...
	def GetThirdPartyMetadata(self, metadataType: str | None = None) -> str | dict:
		"""Returns the third party metadata value for the key 'metadataType'. If no argument, a dict of all set third party metadata properties is returned."""
		...
	def SetThirdPartyMetadata(self, metadata: dict) -> bool:
		"""Sets/Add the item third party metadata with specified dict of key-value pairs"""
		...
	def GetMediaId(self) -> str:
		"""Returns the unique ID for the MediaPoolItem."""
		...
	def AddMarker(self, frameId: int, color: MarkerColor, name: str, note: str, duration: int, customData: str | None = None) -> bool:
		"""Creates a new marker at given frameId position. 'customData' is optional."""
		...
	def DeleteMarkersByColor(self, color: MarkerColor | Literal['All']) -> bool:
		"""Delete all markers of the specified color. 'All' as argument deletes all color markers."""
		...
	def DeleteMarkerAtFrame(self, frameNum: int) -> bool:
		"""Delete marker at frame number from the media pool item."""
		...
	def DeleteMarkerByCustomData(self, customData: str) -> bool:
		"""Delete first matching marker with specified customData."""
		...
	def GetMarkers(self) -> dict[int, MarkerInfo]:
		"""Returns a dict (frameId -> {information}) of all markers."""
		...
	def GetMarkerByCustomData(self, customData: str) -> MarkerInfo:
		"""Returns marker {information} for the first matching marker with specified customData."""
		...
	def UpdateMarkerCustomData(self, frameId: int, customData: str) -> bool:
		"""Updates customData for the marker at given frameId position."""
		...
	def GetMarkerCustomData(self, frameId: int) -> str:
		"""Returns customData string for the marker at given frameId position."""
		...
	def AddFlag(self, color: FlagColor) -> bool:
		"""Adds a flag with given color (string)."""
		...
	def GetFlagList(self) -> list[str]:
		"""Returns a list of flag colors assigned to the item."""
		...
	def ClearFlags(self, color: FlagColor | Literal['All']) -> bool:
		"""Clears the flag of the given color if one exists. An 'All' argument is supported and clears all flags."""
		...
	def GetClipColor(self) -> ClipColor | Literal['']:
		"""Returns the item color as a string."""
		...
	def SetClipColor(self, colorName: ClipColor) -> bool:
		"""Sets the item color based on the colorName (string)."""
		...
	def ClearClipColor(self) -> bool:
		"""Clears the item color."""
		...
	def LinkFullResolutionMedia(self, fullResMediaPath: str) -> bool:
		"""Links proxy media to full resolution media files specified via its path."""
		...
	def LinkProxyMedia(self, proxyMediaFilePath: str) -> bool:
		"""Links proxy media located at path specified by arg 'proxyMediaFilePath' with the current clip."""
		...
	def UnlinkProxyMedia(self) -> bool:
		"""Unlinks any proxy media associated with clip."""
		...
	def ReplaceClip(self, filePath: str) -> bool:
		"""Replaces the underlying asset and metadata of MediaPoolItem with the specified absolute clip path."""
		...
	def ReplaceClipPreserveSubClip(self, filePath: str) -> bool:
		"""Replaces the underlying asset and metadata preserving original sub clip extents."""
		...
	def GetClipProperty(self, propertyName: str | None = None) -> str | ClipProperties:
		"""Returns the property value for the key 'propertyName'. If no argument, a dict of all clip properties is returned."""
		...
	def SetClipProperty(self, propertyName: str, propertyValue: str) -> bool:
		"""Sets the given property to propertyValue (string)."""
		...
	def GetUniqueId(self) -> str:
		"""Returns a unique ID for the media pool item"""
		...
	def TranscribeAudio(self, useSpeakerDetection: bool | None = None, transcribeAsNestedClip = False) -> bool:
		"""Transcribes audio of the MediaPoolItem"""
		...
	def ClearTranscription(self, clearNestedClipTranscription = False) -> bool:
		"""Clears audio transcription of the MediaPoolItem."""
		...
	def PerformAudioClassification(self) -> bool:
		"""Analyzes and classifies the audio of a MediaPoolItem."""
		...
	def ClearAudioClassification(self) -> bool:
		"""Clears audio classification of the MediaPoolItem."""
		...
	def GetAudioMapping(self) -> str:
		"""Returns a string with MediaPoolItem's audio mapping information (JSON format)."""
		...
	def SetAudioMapping(self, audioMapping: str) -> bool:
		"""Sets audio mapping from a JSON string."""
		...
	def GetMarkInOut(self) -> MarkInOut:
		"""Returns dict of in/out marks set."""
		...
	def SetMarkInOut(self, markIn: int, markOut: int, markType: MarkType | None = None) -> bool:
		"""Sets mark in/out of type MarkType (default: 'all')."""
		...
	def ClearMarkInOut(self, markType: MarkType | None = None) -> bool:
		"""Clears mark in/out of type MarkType (default: 'all')."""
		...
	def MonitorGrowingFile(self) -> bool:
		"""Monitor a file as long as it keeps growing."""
		...
	def RemoveMotionBlur(self, deblurOption: DeblurOptions) -> MediaPoolItem:
		"""Apply Motion Deblur on MediaPoolItem, Returns newly created MediaPoolItem."""
		...
	def AnalyzeForIntellisearch(self, identifyFaces: bool, isBetterMode: bool) -> bool:
		"""Perform Intellisearch analysis on the MediaPoolItem."""
		...
	def AnalyzeForSlate(self, markerColor: SlateMarkerColor) -> bool:
		"""Perform Slate analysis on the MediaPoolItem."""
		...
	def GetTranscription(self, useNestedClipTranscription = False) -> Transcription:
		"""Returns transcription data for the media pool item if available."""
		...

class Timeline:
	"""A timeline: tracks, items, markers and export. See README.md section 'Looking up timeline export properties'."""
	def GetName(self) -> str:
		"""Returns the timeline name."""
		...
	def SetName(self, timelineName: str) -> bool:
		"""Sets the timeline name if timelineName (string) is unique."""
		...
	def GetStartFrame(self) -> int:
		"""Returns the frame number at the start of timeline."""
		...
	def GetEndFrame(self) -> int:
		"""Returns the frame number at the end of timeline."""
		...
	def GetTrackCount(self, trackType: TrackType) -> int:
		"""Returns the number of tracks for the given TrackType."""
		...
	def GetItemListInTrack(self, trackType: TrackType, index: int) -> list[TimelineItem]:
		"""Returns a list of timeline items on specified track."""
		...
	def GetSelectedClips(self) -> list[TimelineItem]:
		"""Returns the currently selected timeline items"""
		...
	def GetCurrentTimecode(self) -> str:
		"""Returns a string timecode representation for the current playhead position."""
		...
	def SetCurrentTimecode(self, timecode: str) -> bool:
		"""Sets current playhead position from input timecode."""
		...
	def GetCurrentVideoItem(self) -> TimelineItem | None:
		"""Returns the current video timeline item."""
		...
	def AddMarker(self, frameId: int, color: MarkerColor, name: str, note: str, duration: int, customData: str | None = None) -> bool:
		"""Creates a new marker at given frameId position."""
		...
	def DeleteMarkersByColor(self, color: MarkerColor | Literal['All']) -> bool:
		"""Deletes all timeline markers of the specified color."""
		...
	def DeleteMarkerAtFrame(self, frameNum: int) -> bool:
		"""Deletes the timeline marker at the given frame number."""
		...
	def DeleteMarkerByCustomData(self, customData: str) -> bool:
		"""Delete first matching marker with specified customData."""
		...
	def GetMarkers(self) -> dict[int, MarkerInfo]:
		"""Returns a dict (frameId -> {information}) of all markers."""
		...
	def GetMarkerByCustomData(self, customData: str) -> MarkerInfo:
		"""Returns marker {information} for the first matching marker with specified customData."""
		...
	def UpdateMarkerCustomData(self, frameId: int, customData: str) -> bool:
		"""Updates customData for the marker at given frameId position."""
		...
	def GetMarkerCustomData(self, frameId: int) -> str:
		"""Returns customData string for the marker at given frameId position."""
		...
	def GetCurrentClipThumbnailImage(self) -> ThumbnailData:
		"""Returns a dict with data containing raw thumbnail image data for current media in the Color Page."""
		...
	def AddTrack(self, trackType: TrackType, subTrackType: str | None = None) -> bool:
		"""Adds track of TrackType. Optional argument subTrackType."""
		...
	def DeleteTrack(self, trackType: TrackType, trackIndex: int) -> bool:
		"""Deletes track of trackType and given trackIndex. 1 <= trackIndex <= GetTrackCount(trackType)."""
		...
	def GetTrackSubType(self, trackType: TrackType, trackIndex: int) -> str:
		"""Returns an audio track's format."""
		...
	def SetTrackEnable(self, trackType: TrackType, trackIndex: int, enabled: bool) -> bool:
		"""Enables/Disables track with given trackType and trackIndex"""
		...
	def GetIsTrackEnabled(self, trackType: TrackType, trackIndex: int) -> bool:
		"""Returns True if track with given trackType and trackIndex is enabled."""
		...
	def SetTrackLock(self, trackType: TrackType, trackIndex: int, locked: bool) -> bool:
		"""Locks/Unlocks track with given trackType and trackIndex"""
		...
	def GetIsTrackLocked(self, trackType: TrackType, trackIndex: int) -> bool:
		"""Returns True if track with given trackType and trackIndex is locked."""
		...
	def DeleteClips(self, timelineItems: list[TimelineItem], rippleDelete = False) -> bool:
		"""Deletes specified TimelineItems from the timeline, performing ripple delete if second argument is True."""
		...
	def SetClipsLinked(self, timelineItems: list[TimelineItem], linked: bool) -> bool:
		"""Links or unlinks the specified TimelineItems depending on second argument."""
		...
	def NormalizeAudioLevel(self, timelineItems: list[TimelineItem], normalizeAudioOptions: NormalizeAudioOptions | None = None) -> bool:
		"""Normalizes the audio level of specified TimelineItems using the given normalizeAudioOptions."""
		...
	def AutoAlignClips(self, timelineItems: list[TimelineItem], autoAlignOptions: AutoAlignOptions | None = None) -> bool:
		"""Aligns specified TimelineItems using the given options. Returns True if successful, False otherwise."""
		...
	def GetNormalizeAudioModes(self) -> list[str]:
		"""Returns the list of valid normalizationMode strings for NormalizeAudioLevel."""
		...
	def GetTrackName(self, trackType: TrackType, trackIndex: int) -> str:
		"""Returns the track name for track indicated by trackType and index."""
		...
	def SetTrackName(self, trackType: TrackType, trackIndex: int, name: str) -> bool:
		"""Sets the track name for track indicated by trackType and index."""
		...
	def DuplicateTimeline(self, timelineName: str) -> Timeline:
		"""Duplicates the timeline and returns the created timeline."""
		...
	def GrabStill(self) -> GalleryStill:
		"""Grabs still from the current video clip. Returns a GalleryStill object."""
		...
	def GrabAllStills(self, stillFrameSource: int) -> list[GalleryStill]:
		"""Grabs stills from all clips at 'stillFrameSource' (1=First frame, 2=Middle frame)."""
		...
	def CreateCompoundClip(self, timelineItems: list[TimelineItem], clipInfo: CompoundClipOptions | None = None) -> TimelineItem:
		"""Creates a compound clip of input timeline items."""
		...
	def CreateFusionClip(self, timelineItems: list[TimelineItem]) -> TimelineItem:
		"""Creates a Fusion clip of input timeline items."""
		...
	def Export(self, fileName: str, exportType: TimelineExportType, exportSubtype: TimelineExportSubtype) -> bool:
		"""Exports timeline to 'fileName' as per input exportType & exportSubtype format. See README.md section 'Looking up timeline export properties'."""
		...
	def GetSettings(self) -> TimelineSettings | ProjectSettings:
		"""Returns a dict with all timeline settings, or the project settings when useCustomSettings is '0'. See README.md section 'Looking up Project and Clip properties'."""
		...
	def SetSettings(self, settings: TimelineSettings) -> bool:
		"""Sets the timeline settings with specified dict of setting names and values. See README.md section 'Looking up Project and Clip properties'."""
		...
	def GetStartTimecode(self) -> str:
		"""Returns the start timecode for the timeline."""
		...
	def SetStartTimecode(self, timecode: str) -> bool:
		"""Set the start timecode of the timeline to the string 'timecode'."""
		...
	def ImportIntoTimeline(self, filePath: str, importOptions: AAFImportOptions | None = None) -> bool:
		"""Imports timeline items from an AAF file."""
		...
	def InsertGeneratorIntoTimeline(self, generatorName: str) -> TimelineItem:
		"""Inserts a generator into the timeline."""
		...
	def InsertFusionGeneratorIntoTimeline(self, generatorName: str) -> TimelineItem:
		"""Inserts a Fusion generator into the timeline."""
		...
	def InsertFusionCompositionIntoTimeline(self) -> TimelineItem:
		"""Inserts a Fusion composition into the timeline."""
		...
	def InsertOFXGeneratorIntoTimeline(self, generatorName: str) -> TimelineItem:
		"""Inserts an OFX generator into the timeline."""
		...
	def InsertTitleIntoTimeline(self, titleName: str) -> TimelineItem:
		"""Inserts a title into the timeline."""
		...
	def InsertFusionTitleIntoTimeline(self, titleName: str) -> TimelineItem:
		"""Inserts a Fusion title into the timeline."""
		...
	def CreateSubtitlesFromAudio(self, autoCaptionSettings: AutoCaptionSettings | None = None) -> bool:
		"""Creates subtitles from audio for the timeline."""
		...
	def GetUniqueId(self) -> str:
		"""Returns a unique ID for the timeline"""
		...
	def DetectSceneCuts(self) -> bool:
		"""Detects and makes scene cuts along the timeline."""
		...
	def ConvertTimelineToStereo(self) -> bool:
		"""Converts timeline to stereo."""
		...
	def GetNodeGraph(self) -> Graph:
		"""Returns the timeline's node graph object."""
		...
	def AnalyzeDolbyVision(self, timelineItems: list[TimelineItem], analysisType: DolbyVisionAnalysisType) -> bool:
		"""Analyzes Dolby Vision on clips present on the timeline."""
		...
	def GetMediaPoolItem(self) -> MediaPoolItem | None:
		"""Returns the media pool item corresponding to the timeline"""
		...
	def GetMarkInOut(self) -> MarkInOut:
		"""Returns dict of in/out marks set."""
		...
	def SetMarkInOut(self, markIn: int, markOut: int, markType: MarkType | None = None) -> bool:
		"""Sets mark in/out of type MarkType (default: 'all')"""
		...
	def ClearMarkInOut(self, markType: MarkType | None = None) -> bool:
		"""Clears mark in/out of type MarkType (default: 'all')"""
		...
	def GetVoiceIsolationState(self, trackIndex: int) -> VoiceIsolationState:
		"""Returns the Voice Isolation State as a dict."""
		...
	def SetVoiceIsolationState(self, trackIndex: int, voiceIsolationState: VoiceIsolationState) -> bool:
		"""Sets Voice Isolation state of audio track."""
		...
	def SetOutputBlanking(self, outputBlanking: OutputBlanking) -> bool:
		"""Sets the output blanking for the timeline. Accepts a dictionary with keys 'Top', 'Bottom', 'Left' and 'Right'. The values are in pixels."""
		...
	def GetOutputBlanking(self) -> OutputBlanking:
		"""Returns the output blanking for the timeline as a dictionary with keys 'Top', 'Bottom', 'Left' and 'Right'. The values are in pixels."""
		...

class TimelineItem:
	"""A clip, title, generator or transition on a timeline track. See README.md section 'Looking up Timeline item properties'."""
	def GetType(self) -> str:
		"""Returns the type of the item: 'video', 'audio', 'generator' or 'transition'"""
		...
	def AddTransition(self, transitionOptions: TransitionOptions) -> TimelineItem | None:
		"""Adds a transition of the given type/category to the start or end of this item. Returns the created transition item or None on failure."""
		...
	def GetName(self) -> str:
		"""Returns the item name"""
		...
	def SetName(self, name: str) -> bool:
		"""Sets the clip's name to name."""
		...
	def GetStart(self, subframePrecision = False) -> float:
		"""Returns the start frame position on the timeline. Returns fractional frames if subframe_precision is True"""
		...
	def GetEnd(self, subframePrecision = False) -> float:
		"""Returns the end frame position on the timeline. Returns fractional frames if subframe_precision is True"""
		...
	def GetSourceStartFrame(self) -> int:
		"""Returns the start frame position of the media pool clip in the timeline clip"""
		...
	def GetSourceEndFrame(self) -> int:
		"""Returns the end frame position of the media pool clip in the timeline clip"""
		...
	def GetSourceStartTime(self) -> float:
		"""Returns the start time position of the media pool clip in the timeline clip"""
		...
	def GetSourceEndTime(self) -> float:
		"""Returns the end time position of the media pool clip in the timeline clip"""
		...
	def GetDuration(self, subframePrecision = False) -> float:
		"""Returns the item duration. Returns fractional frames if subframe_precision is True"""
		...
	def GetLeftOffset(self, subframePrecision = False) -> float:
		"""Returns the maximum extension by frame for clip from left side. Returns fractional frames if subframe_precision is True"""
		...
	def GetRightOffset(self, subframePrecision = False) -> float:
		"""Returns the maximum extension by frame for clip from right side. Returns fractional frames if subframe_precision is True"""
		...
	def GetFusionCompCount(self) -> int:
		"""Returns number of Fusion compositions associated with the timeline item"""
		...
	def GetFusionCompNameList(self) -> list[str]:
		"""Returns a list of Fusion composition names associated with the timeline item"""
		...
	def GetFusionCompByIndex(self, compIndex: int) -> FusionComp | None:
		"""Returns the Fusion composition object based on given index. 1 <= compIndex <= timelineItem.GetFusionCompCount()"""
		...
	def GetFusionCompByName(self, compName: str) -> FusionComp | None:
		"""Returns the Fusion composition object based on given name"""
		...
	def AddFusionComp(self) -> FusionComp:
		"""Adds a new Fusion composition associated with the timeline item"""
		...
	def GetMediaPoolItem(self) -> MediaPoolItem | None:
		"""Returns the media pool item corresponding to the timeline item if one exists"""
		...
	def AddMarker(self, frameId: int, color: MarkerColor, name: str, note: str, duration: int, customData: str | None = None) -> bool:
		"""Creates a new marker at given frameId position and with given marker information. 'customData' is optional and helps to attach user specific data to the marker"""
		...
	def DeleteMarkersByColor(self, color: MarkerColor | Literal['All']) -> bool:
		"""Deletes all markers of the specified color from the timeline item. 'All' as argument deletes all color markers"""
		...
	def DeleteMarkerAtFrame(self, frameNum: int) -> bool:
		"""Deletes marker at frame number from the timeline item"""
		...
	def DeleteMarkerByCustomData(self, customData: str) -> bool:
		"""Deletes first matching marker with specified customData"""
		...
	def GetMarkers(self) -> dict[int, MarkerInfo]:
		"""Returns a dict (frameId -> {information}) of all markers and dicts with their information"""
		...
	def GetMarkerByCustomData(self, customData: str) -> MarkerInfo:
		"""Returns marker {information} for the first matching marker with specified customData"""
		...
	def UpdateMarkerCustomData(self, frameId: int, customData: str) -> bool:
		"""Updates customData (string) for the marker at given frameId position. CustomData is not exposed via UI and is useful for scripting developer to attach any user specific data to markers"""
		...
	def GetMarkerCustomData(self, frameId: int) -> str:
		"""Returns customData string for the marker at given frameId position"""
		...
	def SetProperties(self, properties: TimelineItemProperties) -> bool:
		"""Sets the item properties with specified dict of property keys and values. See README.md section 'Looking up Timeline item properties'."""
		...
	def GetProperties(self) -> TimelineItemProperties:
		"""Returns a dict with all supported item properties. See README.md section 'Looking up Timeline item properties'."""
		...
	def SetSpeed(self, speedOptions: SpeedOptions) -> bool:
		"""Sets the Clip Speed"""
		...
	def GetSpeed(self) -> SpeedOptions:
		"""Returns the clip speed options"""
		...
	def AddFlag(self, color: FlagColor) -> bool:
		"""Adds a flag with given color (string)"""
		...
	def GetFlagList(self) -> list[str]:
		"""Returns a list of flag colors assigned to the item"""
		...
	def ClearFlags(self, color: FlagColor | Literal['All']) -> bool:
		"""Clears flags of the specified color. An 'All' argument is supported to clear all flags"""
		...
	def GetStereoConvergenceValues(self) -> dict[int, float]:
		"""Returns a dict (offset -> value) of keyframe offsets and respective convergence values"""
		...
	def GetStereoLeftFloatingWindowParams(self) -> dict[int, FloatingWindowParams]:
		"""For the LEFT eye -> returns a dict (offset -> dict) of keyframe offsets and respective floating window params"""
		...
	def GetStereoRightFloatingWindowParams(self) -> dict[int, FloatingWindowParams]:
		"""For the RIGHT eye -> returns a dict (offset -> dict) of keyframe offsets and respective floating window params"""
		...
	def GetClipColor(self) -> ClipColor | Literal['']:
		"""Returns the item color as a string"""
		...
	def SetClipColor(self, colorName: ClipColor) -> bool:
		"""Sets the item color based on the colorName (string)"""
		...
	def ClearClipColor(self) -> bool:
		"""Clears the item color"""
		...
	def ImportFusionComp(self, path: str) -> FusionComp:
		"""Imports a Fusion composition from given file path by creating and adding a new composition for the item"""
		...
	def ExportFusionComp(self, path: str, compIndex: int) -> bool:
		"""Exports the Fusion composition based on given index to the path provided"""
		...
	def DeleteFusionCompByName(self, compName: str) -> bool:
		"""Deletes the named Fusion composition"""
		...
	def LoadFusionCompByName(self, compName: str) -> FusionComp:
		"""Loads the named Fusion composition as the active composition"""
		...
	def RenameFusionCompByName(self, oldName: str, newName: str) -> bool:
		"""Renames the Fusion composition identified by oldName"""
		...
	def RenameVersionByName(self, oldName: str, newName: str, versionType: int) -> bool:
		"""Renames the color version identified by oldName and versionType (0 - local, 1 - remote)"""
		...
	def DeleteVersionByName(self, versionName: str, versionType: int) -> bool:
		"""Deletes a color version by name and versionType (0 - local, 1 - remote)"""
		...
	def LoadVersionByName(self, versionName: str, versionType: int) -> bool:
		"""Loads a named color version as the active version. versionType: 0 - local, 1 - remote"""
		...
	def AddVersion(self, versionName: str, versionType: int) -> bool:
		"""Adds a new color version for a video clip based on versionType (0 - local, 1 - remote)"""
		...
	def GetVersionNameList(self, versionType: int) -> list[str]:
		"""Returns a list of all color versions for the given versionType (0 - local, 1 - remote)"""
		...
	def SetCDL(self, CDL: CDL) -> bool:
		"""Sets CDL values on the node. Keys of map are: 'NodeIndex', 'Slope', 'Offset', 'Power', 'Saturation'"""
		...
	def AddTake(self, mediaPoolItem: MediaPoolItem, startFrame: int | None = None, endFrame: int | None = None) -> bool:
		"""Adds mediaPoolItem as a new take. Initializes a take selector for the timeline item if needed. By default, the full clip extents is added. startFrame and endFrame are optional arguments used to specify the extents"""
		...
	def GetSelectedTakeIndex(self) -> int:
		"""Returns the index of the currently selected take, or 0 if the clip is not a take selector"""
		...
	def GetTakesCount(self) -> int:
		"""Returns the number of takes in take selector, or 0 if the clip is not a take selector"""
		...
	def GetTakeByIndex(self, idx: int) -> TakeInfo | None:
		"""Returns a dict with take info for specified index"""
		...
	def DeleteTakeByIndex(self, idx: int) -> bool:
		"""Deletes a take by index, 1 <= idx <= number of takes"""
		...
	def SelectTakeByIndex(self, idx: int) -> bool:
		"""Selects a take by index, 1 <= idx <= number of takes"""
		...
	def FinalizeTake(self) -> bool:
		"""Finalizes take selection"""
		...
	def CopyGrades(self, tgtTimelineItems: list[TimelineItem]) -> bool:
		"""Copies the current node stack layer grade to the same layer for each item in tgtTimelineItems."""
		...
	def GetClipEnabled(self) -> bool:
		"""Gets clip enabled status"""
		...
	def SetClipEnabled(self, enabled: bool) -> bool:
		"""Sets clip enabled based on argument"""
		...
	def GetCurrentVersion(self) -> VersionInfo:
		"""Returns the current version of the video clip. The returned value will have the keys versionName and versionType (0 - local, 1 - remote)"""
		...
	def UpdateSidecar(self) -> bool:
		"""Updates sidecar file for BRAW clips or RMD file for R3D clips"""
		...
	def GetUniqueId(self) -> str:
		"""Returns a unique ID for the timeline item"""
		...
	def LoadBurnInPreset(self, presetName: str) -> bool:
		"""Loads user defined data burn in preset for clip when supplied presetName (string)."""
		...
	def CreateMagicMask(self, mode: str) -> bool:
		"""Creates a magic mask. mode can be 'F' (forward), 'B' (backward), or 'BI' (bidirectional)"""
		...
	def RegenerateMagicMask(self) -> bool:
		"""Regenerates the magic mask"""
		...
	def Stabilize(self) -> bool:
		"""Performs stabilization on the clip"""
		...
	def SmartReframe(self) -> bool:
		"""Performs Smart Reframe."""
		...
	def GetNodeGraph(self, layerIdx: int | None = None) -> Graph:
		"""Returns the clip's node graph object at layerIdx (int, optional). Returns the first layer if layerIdx is skipped. 1 <= layerIdx <= project.GetSetting('nodeStackLayers')"""
		...
	def GetColorGroup(self) -> ColorGroup | None:
		"""Returns the clip's color group if one exists"""
		...
	def AssignToColorGroup(self, colorGroup: ColorGroup) -> bool:
		"""Assigns the clip to the given ColorGroup. ColorGroup must be an existing group in the current project"""
		...
	def RemoveFromColorGroup(self) -> bool:
		"""Removes the clip from its ColorGroup"""
		...
	def ExportLUT(self, exportType: ExportLutType, path: str) -> bool:
		"""Exports a LUT of the size given by 'exportType', saving it in the provided 'path'"""
		...
	def GetLinkedItems(self) -> list[TimelineItem]:
		"""Returns a list of linked timeline items"""
		...
	def GetTrackTypeAndIndex(self) -> list[str | int]:
		"""Returns a list of two values that correspond to the TimelineItem's trackType (string) and trackIndex (int) respectively"""
		...
	def GetSourceAudioChannelMapping(self) -> str:
		"""Returns a string with TimelineItem's audio mapping information"""
		...
	def SetSourceAudioChannelMapping(self, audioMapping: str) -> bool:
		"""Sets source audio channel mapping from a JSON string."""
		...
	def GetIsColorOutputCacheEnabled(self) -> bool:
		"""Returns if the cache corresponding to cache_type is enabled"""
		...
	def GetIsFusionOutputCacheEnabled(self) -> str:
		"""Returns if the cache corresponding to cache_type is enabled (or auto)"""
		...
	def SetColorOutputCache(self, enabled: bool) -> bool:
		"""Sets caching to enabled or disabled. Equivalent to clip context menu action 'Render Cache Color Output'"""
		...
	def SetFusionOutputCache(self, cacheValue: str) -> bool:
		"""Sets caching to auto, enabled or disabled. Equivalent to clip context menu action 'Render Cache Fusion Output'"""
		...
	def GetVoiceIsolationState(self) -> VoiceIsolationState:
		"""Returns the Voice Isolation State as a dict {isEnabled, amount}, of the timelineItem"""
		...
	def SetVoiceIsolationState(self, state: VoiceIsolationState) -> bool:
		"""Sets Voice Isolation state of the timelineItem to the given VoiceIsolationState of {isEnabled (bool), amount (int)}. amount is in range of [0, 100]."""
		...
	def ResetAllNodeColors(self) -> bool:
		"""Resets node color for all nodes in the active version of the clip."""
		...
	def SetOutputBlanking(self, outputBlanking: OutputBlanking) -> bool:
		"""Sets the output blanking for the clip. Accepts a dictionary with keys 'Top', 'Bottom', 'Left' and 'Right'. The values are in pixels."""
		...
	def GetOutputBlanking(self) -> OutputBlanking:
		"""Returns the output blanking for the clip as a dictionary with keys 'Top', 'Bottom', 'Left' and 'Right'. The values are in pixels. The dictionary will be empty if the timeline's output blanking is used."""
		...
	def SetUseTimelineForOutputBlanking(self, useTimelineOutputBlanking: bool) -> bool:
		"""Sets the flag to use the timeline's output blanking for the clip."""
		...
	def GetUseTimelineForOutputBlanking(self) -> bool:
		"""Gets the flag to use the timeline's output blanking for the clip."""
		...
	def PerformMulticamSmartSwitch(self, smartSwitchSettings: SmartSwitchSettings) -> bool:
		"""Performs Multicam SmartSwitch on the multicam TimelineItem using the given smartSwitchSettings"""
		...
	def FlattenMulticam(self, gradeOption: FlattenMulticamGrade) -> bool:
		"""Flattens the multicam TimelineItem, using the grade source specified by gradeOption"""
		...
	def GetFades(self) -> FadeInfo:
		"""Returns a dict {FadeIn, FadeOut} of the fade durations (in frames) for the item's video or audio fader"""
		...
	def SetFades(self, fades: FadeInfo) -> bool:
		"""Sets the fade durations (in frames) for the item's video or audio fader from a dict {FadeIn, FadeOut}"""
		...

class ColorGroup:
	"""A group of clips sharing a pre-clip and a post-clip grade."""
	def GetName(self) -> str:
		"""Returns the name of the ColorGroup"""
		...
	def SetName(self, groupName: str) -> bool:
		"""Renames ColorGroup to groupName"""
		...
	def GetClipsInTimeline(self, timeline: Timeline | None = None) -> list[TimelineItem]:
		"""Returns a list of TimelineItems in the ColorGroup for the given Timeline"""
		...
	def GetPreClipNodeGraph(self) -> Graph:
		"""Returns the ColorGroup Pre-clip graph"""
		...
	def GetPostClipNodeGraph(self) -> Graph:
		"""Returns the ColorGroup Post-clip graph"""
		...

class Folder:
	"""A media pool folder: its clips, its subfolders and their analysis."""
	def GetName(self) -> str:
		"""Returns the media folder name"""
		...
	def GetSubFolderList(self) -> list[Folder]:
		"""Returns a list of subfolders in the folder"""
		...
	def GetClipList(self) -> list[MediaPoolItem]:
		"""Returns a list of clips (items) within the folder"""
		...
	def GetIsFolderStale(self) -> bool:
		"""Returns true if folder is stale in collaboration mode"""
		...
	def GetUniqueId(self) -> str:
		"""Returns a unique ID for the media pool folder"""
		...
	def Export(self, filePath: str) -> bool:
		"""Exports the folder as a DRB file to filePath"""
		...
	def TranscribeAudio(self, useSpeakerDetection: bool | None = None, transcribeAsNestedClip = False) -> bool:
		"""Transcribes audio of the MediaPoolItems within the folder and nested folders."""
		...
	def ClearTranscription(self) -> bool:
		"""Clears audio transcription of the MediaPoolItems within the folder and nested folders."""
		...
	def PerformAudioClassification(self) -> bool:
		"""Analyzes and classifies the audio of the MediaPoolItems within the folder and nested folders into categories and subcategories"""
		...
	def ClearAudioClassification(self) -> bool:
		"""Clears audio classification of the MediaPoolItems within the folder and nested folders"""
		...
	def RemoveMotionBlur(self, deblurOption: DeblurOptions | None = None) -> list[list[MediaPoolItem]]:
		"""Apply Motion Deblur on MediaPoolItems in Folder, Returns a list of original to newly created MediaPoolItems"""
		...
	def AnalyzeForIntellisearch(self, identifyFaces: bool, isBetterMode: bool) -> bool:
		"""Perform Intellisearch analysis to all the MediaPoolItems in the folder."""
		...
	def AnalyzeForSlate(self, markerColor: SlateMarkerColor) -> bool:
		"""Perform Slate analysis with current settings and use the stated markerColor to all the MediaPoolItems in the folder."""
		...

class Gallery:
	"""The gallery of a project: its still albums and PowerGrade albums."""
	def GetAlbumName(self, galleryStillAlbum: GalleryStillAlbum) -> str:
		"""Returns the name of a GalleryStillAlbum object"""
		...
	def SetAlbumName(self, galleryStillAlbum: GalleryStillAlbum, albumName: str) -> bool:
		"""Sets the name of a GalleryStillAlbum object"""
		...
	def GetCurrentStillAlbum(self) -> GalleryStillAlbum:
		"""Returns current album as a GalleryStillAlbum object"""
		...
	def SetCurrentStillAlbum(self, galleryStillAlbum: GalleryStillAlbum) -> bool:
		"""Sets current album to the given GalleryStillAlbum object"""
		...
	def CreateGalleryStillAlbum(self) -> GalleryStillAlbum:
		"""Creates a new gallery still album"""
		...
	def CreateGalleryPowerGradeAlbum(self) -> GalleryStillAlbum:
		"""Creates a new gallery power grade album"""
		...
	def GetGalleryStillAlbums(self) -> list[GalleryStillAlbum]:
		"""Returns the gallery still albums as a list of GalleryStillAlbum objects"""
		...
	def GetGalleryPowerGradeAlbums(self) -> list[GalleryStillAlbum]:
		"""Returns the gallery PowerGrade albums as a list of GalleryStillAlbum objects"""
		...

class GalleryStill:
	"""A still of a gallery album, used as a handle by the GalleryStillAlbum functions."""

class GalleryStillAlbum:
	"""An album of gallery stills, which can be labelled, imported and exported."""
	def GetStills(self) -> list[GalleryStill]:
		"""Returns the list of GalleryStill objects in the album"""
		...
	def GetLabel(self, galleryStill: GalleryStill) -> str:
		"""Returns the label of the galleryStill"""
		...
	def SetLabel(self, galleryStill: GalleryStill, label: str) -> bool:
		"""Sets the new label to a GalleryStill object"""
		...
	def ImportStills(self, filePaths: list[str]) -> bool:
		"""Imports GalleryStill from each filePath in the list"""
		...
	def ExportStills(self, galleryStill: list[GalleryStill], folderPath: str, filePrefix: str, format: str) -> bool:
		"""Exports list of GalleryStill objects to a directory"""
		...
	def DeleteStills(self, galleryStill: list[GalleryStill]) -> bool:
		"""Deletes specified list of GalleryStill objects"""
		...

class Graph:
	"""The node graph of a clip or of a color group: its nodes, LUTs and grades. See README.md section 'Cache Mode information'."""
	def GetNumNodes(self) -> int:
		"""Returns the number of nodes in the graph"""
		...
	def SetLUT(self, nodeIndex: int, lutPath: str) -> bool:
		"""Sets LUT on the node mapping the node index provided, 1 <= nodeIndex <= GetNumNodes()"""
		...
	def GetLUT(self, nodeIndex: int) -> str:
		"""Gets relative LUT path based on the node index provided, 1 <= nodeIndex <= GetNumNodes()"""
		...
	def SetNodeCacheMode(self, nodeIndex: int, cacheValue: CacheMode) -> bool:
		"""Sets the cache mode type on the node mapping the node index provided"""
		...
	def GetNodeCacheMode(self, nodeIndex: int) -> int:
		"""Returns the cache mode type on the node mapping the node index provided"""
		...
	def GetNodeLabel(self, nodeIndex: int) -> str:
		"""Returns the label of the node at nodeIndex"""
		...
	def GetToolsInNode(self, nodeIndex: int) -> list[str]:
		"""Returns toolsList of the tools used in the node indicated by given nodeIndex"""
		...
	def SetNodeEnabled(self, nodeIndex: int, isEnabled: bool) -> bool:
		"""Sets the node at the given nodeIndex to isEnabled, 1 <= nodeIndex <= GetNumNodes()"""
		...
	def ApplyArriCdlLut(self) -> bool:
		"""Applies ARRI CDL and LUT."""
		...
	def ApplyGradeFromDRX(self, path: str, gradeMode: int) -> bool:
		"""Loads a still from given file path and applies grade to graph with gradeMode (0=No keyframes, 1=Source Timecode aligned, 2=Start Frames aligned)"""
		...
	def ResetAllGrades(self) -> bool:
		"""Resets all grades in the graph"""
		...

class MediaStorage:
	"""Browses the volumes of the file system and adds media files to the media pool."""
	def GetMountedVolumeList(self) -> list[str]:
		"""Returns list of folder paths corresponding to mounted volumes displayed in Resolve's Media Storage"""
		...
	def GetSubFolderList(self, folderPath: str) -> list[str]:
		"""Returns list of folder paths in the given absolute folder path"""
		...
	def GetFileList(self, folderPath: str) -> list[str]:
		"""Returns list of media and file listings in the given absolute folder path"""
		...
	def RevealInStorage(self, path: str) -> bool:
		"""Expands and displays given file/folder path in Resolve's Media Storage"""
		...
	def AddItemListToMediaPool(self, itemInfos: list[MediaStorageItemInfo]) -> list[MediaPoolItem]:
		"""Adds specified file/folder paths from Media Storage into current Media Pool folder. Returns a list of the MediaPoolItems created"""
		...
	def AddClipMattesToMediaPool(self, mediaPoolItem: MediaPoolItem, paths: list[str], stereoEye: str | None = None) -> bool:
		"""Adds specified media files as mattes for the specified MediaPoolItem. stereoEye is 'left' or 'right' for stereo clips"""
		...
	def AddTimelineMattesToMediaPool(self, paths: list[str]) -> list[MediaPoolItem]:
		"""Adds specified media files as timeline mattes in current media pool folder. Returns a list of created MediaPoolItems"""
		...
	def StartCloneMedia(self, sourceDir: str, targetDirs: str | list[str]) -> bool:
		"""Starts cloning media from sourceDir to targetDirs. Use SetCloneToolSettings to configure PreserveFolderName/ChecksumType beforehand."""
		...
	def SetCloneToolSettings(self, cloneToolSettings: CloneToolSettings | None = None) -> bool:
		"""Sets the PreserveFolderName/ChecksumType options used by subsequent StartCloneMedia calls (and by the Clone Tool UI)."""
		...
	def StopCloneMedia(self) -> bool:
		"""Stops the currently in-progress clone job started via StartCloneMedia. Returns False if no clone job is in progress."""
		...
	def GetCloneStatus(self) -> CloneStatus:
		"""Returns a dict with the status of the current (or most recently started) clone job"""
		...

class Fusion: ...
class FusionComp: ...

def scriptapp(app: str) -> Resolve: ...
