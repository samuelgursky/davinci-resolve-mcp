#!/usr/bin/env python3
"""Inventory a shipped Resolve .pyi against executable source references.

Diagnostic only: absence is a candidate gap, presence is NOT wrapper coverage.
Receiver types are not inferred, and arbitrary dynamic dispatch is unresolved.
This complements the legacy README audit without changing its baseline.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory_stub(text: str) -> dict:
    """Preserve class identity, signatures, docs, and typed option fields."""
    methods, options = {}, {}
    for cls in ast.parse(text).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_'):
                key = f'{cls.name}.{node.name}'
                signature = f'{node.name}({ast.unparse(node.args)})'
                if node.returns is not None:
                    signature += f' -> {ast.unparse(node.returns)}'
                row = methods.setdefault(key, {'signatures': [], 'line': node.lineno,
                                                'description': ast.get_docstring(node)})
                row['signatures'].append(signature)
        if any(ast.unparse(base).endswith('TypedDict') for base in cls.bases):
            fields = {}
            for index, node in enumerate(cls.body):
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    doc = None
                    if index + 1 < len(cls.body):
                        following = cls.body[index + 1]
                        if (isinstance(following, ast.Expr) and isinstance(following.value, ast.Constant)
                                and isinstance(following.value.value, str)):
                            doc = following.value.value
                    fields[node.target.id] = {'type': ast.unparse(node.annotation),
                                              'line': node.lineno, 'description': doc}
            options[cls.name] = fields
    if not methods:
        raise ValueError('No public class methods found; refusing an empty API inventory')
    return {'methods': methods, 'option_types': options}


def source_references(text: str) -> list[dict]:
    """Record executable syntax, never docstrings/comments as fake coverage."""
    tree = ast.parse(text)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    refs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            parent = parents.get(node)
            refs.append({'method_name': node.attr, 'line': node.lineno,
                         'receiver': ast.unparse(node.value),
                         'kind': 'call' if isinstance(parent, ast.Call) and parent.func is node else 'attribute'})
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == 'getattr' and len(node.args) > 1
              and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            refs.append({'method_name': node.args[1].value, 'line': node.lineno,
                         'receiver': ast.unparse(node.args[0]), 'kind': 'getattr'})
    return refs


def build_report(stub_text: str, sources: dict[str, str]) -> dict:
    inventory = inventory_stub(stub_text)
    by_name = {}
    for path, text in sorted(sources.items()):
        layer = ('compound' if path == 'src/server.py' else
                 'granular' if path.startswith('src/granular/') else 'helper')
        for ref in source_references(text):
            by_name.setdefault(ref['method_name'], []).append({'path': path, 'layer': layer, **ref})
    for key, method in inventory['methods'].items():
        refs = by_name.get(key.rsplit('.', 1)[1], [])
        method['name_references'] = refs
        method['status'] = 'unresolved_receiver' if refs else 'no_executable_name_reference'
    candidates = [key for key, row in inventory['methods'].items() if not row['name_references']]
    return {'schema_version': 1, 'method_count': len(inventory['methods']),
            'candidate_count': len(candidates), 'candidate_gaps': candidates,
            'limitations': ['References are matched by method name, not receiver type.',
                            'A call/reference does not prove public action or parameter coverage.',
                            'Literal getattr may only probe availability.',
                            'Computed dispatch and equivalent older methods need manual review.',
                            'This inventory does not invoke Resolve or validate behavior.'],
            **inventory}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stub', type=Path, default=ROOT / 'docs/reference/DaVinciResolveScript.pyi')
    parser.add_argument('--source-root', type=Path, default=ROOT / 'src')
    parser.add_argument('--json', action='store_true', help='Print the full method/option/reference inventory')
    args = parser.parse_args()
    paths = sorted(args.source_root.rglob('*.py'))
    if not paths:
        parser.error('No Python source files found; refusing an empty source inventory')
    sources = {'src/' + path.relative_to(args.source_root).as_posix(): path.read_text(encoding='utf-8')
               for path in paths}
    report = build_report(args.stub.read_text(encoding='utf-8'), sources)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['method_count']} class-qualified methods; {report['candidate_count']} candidate gaps")
        for name in report['candidate_gaps']:
            print(name)
        print('Diagnostic only: name references are not proof of wrapper coverage or live behavior.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
