# Complex-cut round trip: what each format keeps

Two video tracks, audio, a per-item transform, clip colours, flags, item and timeline markers. `kept` = identical to the reference; `n/a` = the API would not set that dimension, so no format can be blamed for losing it.

| format | mode | cut | tracks | transform | colour | flags | markers | timeline_markers | linkage |
|  --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| drt | gui | kept | kept | kept | kept | kept | kept | kept | kept |
| drt | headless | kept | kept | kept | kept | kept | kept | kept | kept |
| fcpxml_1_10 | gui | kept | lost:2v1a!=2v2a | kept | lost | kept | lost | lost | kept |
| fcpxml_1_10 | headless | kept | lost:2v1a!=2v2a | kept | lost | kept | lost | lost | kept |
| fcp7xml | gui | kept | kept | lost:FlipX | lost | kept | lost | lost | kept |
| fcp7xml | headless | kept | kept | lost:FlipX | lost | kept | lost | lost | kept |
| aaf | gui | kept | kept | lost:all | lost | kept | lost | kept | kept |
| aaf | headless | kept | kept | lost:all | lost | kept | lost | kept | kept |
| otio | gui | lost:source | kept | kept | lost | lost | kept | kept | offline:4 |
| otio | headless | lost:source | kept | kept | lost | lost | kept | kept | offline:4 |
| edl | gui | lost | lost:1v1a!=2v2a | lost:item-count | lost | lost | lost | lost | kept |
| edl | headless | lost | lost:1v1a!=2v2a | lost:item-count | lost | lost | lost | lost | kept |
