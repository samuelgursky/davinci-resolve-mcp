"""Read Resolve-rendered test frames; requires Pillow and NumPy, never writes media."""
import json
import sys
import numpy as np
from PIL import Image

pixels = np.asarray(Image.open(sys.argv[1]).convert('RGB'))
result = {'width': int(pixels.shape[1]), 'height': int(pixels.shape[0]),
          'nonblack_pixels': int((pixels.max(axis=2) > 30).sum())}
if len(sys.argv) > 2:
    other = np.asarray(Image.open(sys.argv[2]).convert('RGB'))
    result['changed_pixels'] = int(np.any(pixels != other, axis=2).sum())
print(json.dumps(result))
