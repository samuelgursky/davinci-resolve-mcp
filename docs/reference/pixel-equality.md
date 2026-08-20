# Pixel equality: GUI vs headless rendered frames

Frames are compared after decoding (ffmpeg `framemd5`), so container metadata cannot influence the result. `effective` is the within-mode control: whether the effect changed the picture at all relative to `plain`. An effect that is not effective makes its mode comparison meaningless, and is called out rather than counted as a pass.

| effect | effective (GUI) | effective (headless) | pixels identical across modes |
| --- | --- | --- | --- |
| plain | — | — | **identical** |
| transform | True | True | **identical** |
| cdl | True | True | **identical** |
| lut | True | True | **identical** |
| fusion_comp | True | True | **identical** |
