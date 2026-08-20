# Timeline round-trip fidelity: export, re-import, compare

`exact` = every item's record start, duration and **source in-point** survived, with all media linked. Anything else is unusable for an iterative edit loop.

| format | link strategy | GUI | headless |
| --- | --- | --- | --- |
| drt | reuse_pool | exact | exact |
| fcpxml_1_10 | reuse_pool | exact | exact |
| fcpxml_1_10 | import_source | exact | exact |
| fcp7xml | reuse_pool | exact | exact |
| fcp7xml | import_source | exact | exact |
| aaf | reuse_pool | exact | exact |
| aaf | import_source | exact | exact |
| otio | reuse_pool | exact-but-4-offline | exact-but-4-offline |
| otio | import_source | exact | exact |
| edl | reuse_pool | exact | exact |
| edl | import_source | exact | exact |
