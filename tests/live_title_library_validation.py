"""Installed-library acceptance on an already-open synthetic MCP_QA_* project.

Never launches/quits Resolve. Persists a report after every case and restores the
original timeline/page/playhead. Native presets remain local, not redistributed.
"""
import argparse
import json
import sys
import time
import uuid
import subprocess
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils.platform import setup_environment
from src.utils.title_library import list_title_presets
from src.utils.subtitle_live import _inventory
from src.utils.title_controls import title_text_targets
from src.utils.qa_privacy import anonymize_host_paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--category', choices=['all', 'title', 'subtitle'], default='all')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--only', nargs='+', help='Retest exact names or full template IDs')
    parser.add_argument('--retest-report', help='Retest failures, uncovered text and shape/3D/follower layouts')
    parser.add_argument('--output-dir')
    parser.add_argument('--image-python', default=sys.executable,
                        help='Python with Pillow and NumPy for independent frame metrics')
    args = parser.parse_args()
    subprocess.run([args.image_python, '-I', '-c', 'import PIL,numpy'], check=True)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf8', errors='replace')
    setup_environment()
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    if not resolve:
        raise RuntimeError('Existing Studio unavailable; no launch attempted')
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project or not project.GetName().startswith('MCP_QA_'):
        raise RuntimeError('This harness requires a disposable MCP_QA_* project')
    from src import server
    server.resolve = resolve
    server._launch_resolve = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Launch forbidden'))
    original = project.GetCurrentTimeline()
    tc, page = original.GetCurrentTimecode(), resolve.GetCurrentPage()
    run = uuid.uuid4().hex[:8]
    folder = Path(server._resolve_safe_dir(args.output_dir or str(ROOT / 'logs' / f'title-library-{run}'))).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    catalog = list_title_presets()
    presets = [p for p in catalog['presets'] if args.category == 'all'
               or (p['category'] == 'title') == (args.category == 'title')]
    if args.limit:
        presets = presets[:args.limit]
    if args.only:
        presets = [p for p in presets if p['name'] in args.only or p['template_id'] in args.only]
    if args.retest_report:
        previous = json.loads(Path(args.retest_report).read_text(encoding='utf8'))
        selected = {c['template_id'] for c in previous['cases'] if c.get('status') != 'passed'
                    or (c['category'] == 'title' and (not any(x.get('input') == 'StyledText' for x in c.get('properties', []))
                        or any('.StyledText:' in str(x) for x in c.get('warnings', []))))}
        with zipfile.ZipFile(catalog['archive']) as zipped:
            for p in presets:
                if p['category'] == 'title':
                    definition = zipped.read(p['template_id'][len('Templates/'):] + '.setting').decode('utf8',errors='replace')
                    if re.search(r'=\s*(?:sText|Text3D|MultiText|StyledTextFollower)\s*\{', definition):
                        selected.add(p['template_id'])
                else:
                    definition = zipped.read(p['template_id'][len('Templates/'):] + '.setting').decode('utf8',errors='replace')
                    if re.search(r'Type1\s*=\s*Input\s*\{\s*Value\s*=\s*[12]',definition):
                        selected.add(p['template_id'])
        presets = [p for p in presets if p['template_id'] in selected]
    report = {'resolve': resolve.GetVersionString(), 'project': project.GetName(),
              'catalog': catalog, 'run': run, 'cases': [], 'complete': False,
              'verification': 'native_application_and_sampled_frames_only', 'restart_required': False}

    def save():
        pending = folder / 'report.pending.json'
        pending.write_text(json.dumps(anonymize_host_paths(report), indent=2, default=str), encoding='utf8')
        pending.replace(folder / 'report.json')

    def capture(case, label, frame, fps=30):
        # timeline_frame does a native single-frame Deliver render with subtitle
        # BurnIn. It also bypasses thumbnail/viewer-cache ambiguity.
        # Native insertion can leave the playhead exactly at the exclusive end,
        # where restoring that timecode is refused. Park inside the test first.
        seconds, fraction = divmod(frame, fps)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        timecode = f'{hours:02d}:{minutes:02d}:{seconds:02d}:{fraction:02d}'
        assert project.GetCurrentTimeline().SetCurrentTimecode(timecode)
        image = server.timeline_frame('capture', {'frame': frame, 'format': 'png', 'quality': 'frame'})
        if isinstance(image, (dict, list)):
            raise RuntimeError(f'Native render failed: {image}')
        path = folder / f"{case['index']:03d}-{label}.png"
        path.write_bytes(image.data)
        metrics = json.loads(subprocess.check_output([args.image_python, '-I',
            str(ROOT / 'scripts/title_frame_metrics.py'), str(path)], text=True))
        case.setdefault('frames', []).append({'path': str(path), 'frame': frame, **metrics})
        return path

    try:
        for index, preset in enumerate(presets, 1):
            active_project = resolve.GetProjectManager().GetCurrentProject()
            if not active_project or active_project.GetUniqueId() != project.GetUniqueId():
                raise RuntimeError('Active project changed; stopping before further QA mutations')
            case = {**preset, 'index': index, 'application': False, 'property_readback': False,
                    'render_samples': False, 'properties': [], 'warnings': []}
            report['cases'].append(case)
            started = time.monotonic()
            try:
                if preset['category'] == 'title':
                    timeline = project.GetMediaPool().CreateEmptyTimeline(f'MCP Title {run} {index:03d} {preset["name"]}')
                    assert timeline and project.SetCurrentTimeline(timeline)
                    # Use a landscape frame for ordinary titles and lower thirds.
                    timeline.SetSetting('useCustomSettings', '1')
                    timeline.SetSetting('timelineResolutionWidth', '1920')
                    timeline.SetSetting('timelineResolutionHeight', '1080')
                    assert timeline.SetCurrentTimecode('01:00:00:00')
                    inserted = server.timeline('insert_fusion_title', {'name': preset['template_id']})
                    assert inserted.get('success'), inserted
                    items = timeline.GetItemListInTrack('video', 1)
                    assert len(items) == 1
                    item = items[0]
                    comp = item.GetFusionCompByIndex(1)
                    assert comp and comp.GetData('TEMPLATE_ID') == preset['template_id']
                    case['application'] = True
                    case['timeline'] = timeline.GetName()
                    case['timeline_id'] = timeline.GetUniqueId()
                    start, end = int(item.GetStart()), int(item.GetEnd())
                    baseline = capture(case, 'before', start + (end-start)//2)
                    targets, skipped = title_text_targets(comp)
                    case['text_targets'] = [{k:v for k,v in target.items() if k != 'tool'} for target in targets]
                    case['warnings'].extend(skipped)
                    for target_index, target in enumerate(targets):
                        tool, key = target['tool'], target['input']
                        before = tool.GetInput(key)
                        result = (server.timeline('set_title_text', {'clip_id': item.GetUniqueId(), 'text':'MCP TEST'})
                                  if target_index == 0 else server.fusion_comp('safe_set_inputs',
                                  {'clip_id': item.GetUniqueId(), 'tool_name': target['tool_name'], 'inputs': {key:'MCP TEST'}}))
                        actual = tool.GetInput(key)
                        case['properties'].append({'tool':target['tool_name'], 'input':key,
                            'before':before, 'requested':'MCP TEST', 'actual':actual,
                            'verified':actual == 'MCP TEST', 'result':result})
                    for tool in (comp.GetToolList(False) or {}).values():
                        attrs = tool.GetAttrs() or {}
                        if attrs.get('TOOLS_RegID') not in ('TextPlus', 'Text3D', 'sText'):
                            continue
                        # Inspect connections/expressions before touching any
                        # controls; never flatten a connected animated input.
                        inputs = {v.GetAttrs().get('INPS_ID'): v for v in (tool.GetInputList() or {}).values()}
                        changes, previous = {}, {}
                        colour = [('Red1', 0.15), ('Green1', 0.85), ('Blue1', 1.0)]
                        for key, value in [('Size', 0.075)] + colour:
                            inp = inputs.get(key)
                            if not inp:
                                continue
                            if inp.GetConnectedOutput() or inp.GetExpression():
                                case['warnings'].append(f'{attrs.get("TOOLS_Name")}.{key}: connected/expression; retained')
                                continue
                            before = tool.GetInput(key)
                            if before is None:
                                continue
                            if key == 'Size' and attrs.get('TOOLS_RegID') == 'Text3D' and isinstance(before, (float, int)):
                                value = before * 1.1
                            changes[key], previous[key] = value, before
                        if not changes:
                            continue
                        result = server.fusion_comp('safe_set_inputs', {
                            'clip_id': item.GetUniqueId(), 'tool_name': attrs['TOOLS_Name'],
                            'inputs': changes})
                        for key, value in changes.items():
                            # Independent native readback as well as public result.
                            actual = tool.GetInput(key)
                            ok = actual == value or (isinstance(actual, (int, float))
                                                     and isinstance(value, (int, float)) and abs(actual-value)<1e-6)
                            case['properties'].append({'tool': attrs['TOOLS_Name'], 'input': key,
                                                       'before': previous[key], 'requested': value,
                                                       'actual': actual, 'verified': ok, 'result': result})
                    case['property_readback'] = bool(targets) and all(x['verified'] for x in case['properties'])
                    after = capture(case, 'after', start + (end-start)//2)
                    comparison = json.loads(subprocess.check_output([args.image_python, '-I',
                        str(ROOT / 'scripts/title_frame_metrics.py'), str(baseline), str(after)], text=True))
                    case['changed_pixels'] = comparison['changed_pixels']
                    capture(case, 'early', start + max(1, (end-start)//10))
                    capture(case, 'late', end - max(2, (end-start)//10))
                    # Entry/exit samples may legitimately be blank. The settled
                    # before/after must be visible and show the requested edit.
                    case['render_samples'] = (all(f['nonblack_pixels'] > 100 for f in case['frames'][:2])
                                              and case['changed_pixels'] > 100)
                    exported = folder / f'{index:03d}-native.drt'
                    assert timeline.Export(str(exported), resolve.EXPORT_DRT), 'Native export failed'
                    case['export'] = str(exported)
                else:
                    assert project.SetCurrentTimeline(original)
                    before_inventory = _inventory(original)
                    inputs = {'size': 0.06, 'position': [0.5, 0.25],
                              'textRed': 0.15, 'textGreen': 0.85, 'textBlue': 1.0}
                    with zipfile.ZipFile(catalog['archive']) as zipped:
                        definition = zipped.read(preset['template_id'][len('Templates/'):] + '.setting').decode('utf8',errors='replace')
                    if re.search(r'Type1\s*=\s*Input\s*\{\s*Value\s*=\s*[12]',definition):
                        inputs['textFillMode'] = 'solid'
                        case['warnings'].append('Explicit solid-fill replacement for colour test; native gradient reference retained')
                    result = server.timeline_ai('set_subtitle_preset', {
                        'preset': preset['template_id'],
                        'revision_name': f'MCP Subtitle {run} {index:03d} {preset["name"]}',
                        'inputs': inputs})
                    case['action'] = result
                    assert result.get('success'), result
                    timeline = project.GetCurrentTimeline()
                    assert _inventory(timeline) == before_inventory
                    case['application'] = True
                    case['property_readback'] = True
                    case['timeline'] = timeline.GetName()
                    case['timeline_id'] = timeline.GetUniqueId()
                    for label, frame in [('word-one', 108200), ('word-two', 108220), ('gap', 108180)]:
                        capture(case, label, frame)
                    case['render_samples'] = (case['frames'][0]['nonblack_pixels'] > 100
                                              and case['frames'][1]['nonblack_pixels'] > 100
                                              and case['frames'][2]['nonblack_pixels'] == 0)
                    case['properties'] = result['patch']['after']
                case['status'] = 'passed' if (case['application'] and case['property_readback'] and case['render_samples']) else 'needs_review'
            except Exception as exc:
                case['status'] = 'failed'
                case['error'] = str(exc) or type(exc).__name__
            finally:
                case['duration_seconds'] = round(time.monotonic()-started, 2)
                save()
                try:
                    assert project.SetCurrentTimeline(original)
                except Exception as exc:
                    case['restoration_error'] = str(exc) or type(exc).__name__
                    report['session_failure'] = case['restoration_error']
                    save()
                    raise
                print(json.dumps({'index': index, 'total': len(presets), 'name': preset['name'],
                                  'category': preset['category'], 'status': case['status'],
                                  'error': case.get('error'), 'seconds': case['duration_seconds']}), flush=True)
        report['complete'] = True
    finally:
        try:
            assert project.SetCurrentTimeline(original)
            assert original.SetCurrentTimecode(tc), 'Original playhead restoration failed'
            report['restoration'] = {'timeline': project.GetCurrentTimeline().GetUniqueId() == original.GetUniqueId(),
                                     'timecode': original.GetCurrentTimecode(), 'page_requested': page}
            if page:
                report['restoration']['page_result'] = resolve.OpenPage(page)
        except Exception as exc:
            report['restoration_error'] = str(exc) or type(exc).__name__
            report['complete'] = False
        save()
        print('REPORT ' + anonymize_host_paths(str(folder / 'report.json')), flush=True)


if __name__ == '__main__':
    main()
