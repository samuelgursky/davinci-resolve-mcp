"""Remove host identity from saved QA records; never change source media."""
import re
import json
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]


def anonymize_host_paths(value):
    if isinstance(value, dict):
        return {key: ('[project]' if key == 'project' else '[timeline]')
                if key in ('project', 'timeline', 'original_timeline') and isinstance(item, str)
                else anonymize_host_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [anonymize_host_paths(item) for item in value]
    if isinstance(value, str):
        for path, label in ((WORKSPACE, '[workspace]'), (Path.home(), '[home]')):
            spellings = (str(path), path.as_posix())
            for spelling in spellings + tuple(json.dumps(s)[1:-1] for s in spellings):
                value = re.sub(re.escape(spelling), lambda _: label, value, flags=re.IGNORECASE)
    return value


def qa_artifact_path(value):
    """Resolve anonymized workspace paths locally without saving host identity."""
    return Path(str(value).replace('[workspace]', str(WORKSPACE)))
