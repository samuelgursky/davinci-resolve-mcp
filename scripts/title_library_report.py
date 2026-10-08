"""Build local test matrices/contact sheets from Resolve-rendered QA frames."""
import argparse
import html
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.qa_privacy import anonymize_host_paths, qa_artifact_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('reports', nargs='+')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = {}
    versions = []
    sessions = []
    for filename in args.reports:
        report = json.loads(Path(filename).read_text(encoding='utf8'))
        versions.append(report.get('resolve'))
        sessions.append({'report': str(Path(filename).resolve()), 'complete': report.get('complete'),
                         'session_failure': report.get('session_failure'),
                         'restart_required': report.get('restart_required'),
                         'restoration': report.get('restoration'),
                         'restoration_error': report.get('restoration_error')})
        for case in report['cases']:
            cases[case['template_id']] = case
    ordered = sorted(cases.values(), key=lambda c: (c['category'], c['name']))
    counts = Counter(c['status'] for c in ordered)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 18) if Path('C:/Windows/Fonts/arial.ttf').is_file() else ImageFont.load_default()
    sheets = []
    for category in sorted({c['category'] for c in ordered}):
        subset = [c for c in ordered if c['category'] == category]
        for offset in range(0, len(subset), 12):
            sheet = Image.new('RGB', (1440, 1240), '#171a22')
            draw = ImageDraw.Draw(sheet)
            for cell, case in enumerate(subset[offset:offset+12]):
                x, y = cell % 3 * 480, cell // 3 * 310
                frame = next((f for f in case.get('frames', []) if '-after.' in f['path'] or '-word-one.' in f['path']), None)
                if frame:
                    img = Image.open(qa_artifact_path(frame['path'])).convert('RGB')
                    if category != 'title':
                        # Subtitle captions occupy a small part of a vertical
                        # frame. Show a labelled detail; keep full frames linked.
                        bounds = img.getbbox()
                        if bounds:
                            img = img.crop((max(0,bounds[0]-48),max(0,bounds[1]-48),
                                            min(img.width,bounds[2]+48),min(img.height,bounds[3]+48)))
                    img.thumbnail((470, 265))
                    sheet.paste(img, (x+(480-img.width)//2, y+(265-img.height)//2))
                draw.text((x+8, y+270), case['name'][:46], font=font, fill='white')
                draw.text((x+8, y+291), case['status'] + (' · caption detail' if category != 'title' else ''), font=font,
                          fill='#7df4b5' if case['status']=='passed' else '#ffc477')
            path = output / f'{category}-{offset//12+1:02d}.jpg'
            sheet.save(path, quality=92)
            sheets.append(str(path))
    rows = []
    frame_dir = output / 'frames'
    frame_dir.mkdir(exist_ok=True)
    for case_index, case in enumerate(ordered, 1):
        links = []
        for frame_index, frame in enumerate(case.get('frames', []), 1):
            source = qa_artifact_path(frame['path']).resolve()
            name = f'{case_index:03d}-{frame_index:02d}{source.suffix.lower()}'
            target = frame_dir / name
            if source != target:
                # Only copy generated QA renders; source media is never read or
                # transformed here. The HTML and frames travel as one folder.
                shutil.copy2(source, target)
            links.append(f'<a href="frames/{html.escape(name)}">frame {frame["frame"]}</a>')
        frames = ' '.join(links)
        rows.append('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in
            [case['category'],case['name'],case['status'],case.get('application'),
             case.get('property_readback'),case.get('render_samples'),case.get('changed_pixels',''),
             case.get('error','')])+f'<td>{frames}</td></tr>')
    (output/'index.html').write_text(f'''<!doctype html><meta charset="utf-8"><title>Resolve title acceptance</title>
<style>body{{background:#161922;color:#eee;font:15px system-ui;padding:24px}}table{{border-collapse:collapse}}td,th{{border:1px solid #444;padding:8px}}a{{color:#7dccff}}img{{max-width:100%}}</style>
<h1>Resolve title acceptance</h1><p>{len(ordered)} tested: {html.escape(str(dict(counts)))}. Studio {html.escape(str(versions))}.</p>
<p>Native application, literal property readback and sampled rendered frames. These checks do not certify every control, frame, platform or third-party effect.</p>
<p>{html.escape('Session failures: ' + '; '.join(s['session_failure'] for s in sessions if s['session_failure'])) if any(s['session_failure'] for s in sessions) else 'No session failure recorded.'}</p>
<table><tr><th>Category</th><th>Preset</th><th>Status</th><th>Applied</th><th>Properties</th><th>Samples</th><th>Changed pixels</th><th>Error</th><th>Native frames</th></tr>{''.join(rows)}</table>
{''.join(f'<h2>{Path(s).stem}</h2><img src="{Path(s).name}">' for s in sheets)}''',encoding='utf8')
    (output/'matrix.json').write_text(json.dumps(anonymize_host_paths({'counts':dict(counts),'versions':versions,'sessions':sessions,'cases':ordered,'sheets':sheets}),indent=2),encoding='utf8')
    print(json.dumps(anonymize_host_paths({'count':len(ordered),'statuses':dict(counts),'sheets':sheets,'html':str(output/'index.html')})))


if __name__ == '__main__':
    main()
