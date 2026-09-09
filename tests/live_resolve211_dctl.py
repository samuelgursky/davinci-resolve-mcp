"""Native validation only: no DCTL installation or project mutation.
Usage: python tests/live_resolve211_dctl.py
"""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

MULTILINE='__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B)\n{\n    return make_float3(p_R, p_G, p_B);\n}\n'
ONE_LINE='__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B) { return make_float3(p_R, p_G, p_B); }'


def main():
    import src.server as s
    from src.granular import resolve_211 as g
    rows=[]
    for name,source in [('multiline',MULTILINE),('one_line',ONE_LINE),('invalid','not a DCTL')]:
        raw=s.get_resolve().ValidateDCTL(source)
        compound=s.dctl('validate_native',{'source':source})
        granular=g.validate_dctl_native(source)
        for result in [compound,granular]:
            assert result.get('diagnostic')==raw and result.get('valid') is (raw is None),result
        rows.append({'case':name,'valid':raw is None,'diagnostic':raw})
    assert rows[0]['valid'] and not rows[2]['valid']
    print(json.dumps({'version':s.get_resolve().GetVersionString(),'results':rows},indent=2))


if __name__=='__main__':main()
