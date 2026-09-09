"""Native DCTL diagnostics are evidence; never reformat the user's shader source."""


def native_dctl_result(resolve, source):
    diagnostic=resolve.ValidateDCTL(source)
    if diagnostic is not None and not isinstance(diagnostic,str):
        return {'error':'ValidateDCTL returned an unexpected diagnostic type'}
    return {'valid':diagnostic is None,'diagnostic':diagnostic,'checker':'resolve_native'}
