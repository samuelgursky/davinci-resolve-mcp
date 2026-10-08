"""Locate literal text inputs without disconnecting native title animation."""

import re

TEXT_TOOLS = {'TextPlus', 'Text3D', 'sText', 'MultiText'}
TEXT_MODIFIERS = {'StyledTextFollower': 'Text', 'PublishText': 'Value'}


def title_text_keys(tool):
    """Read and write use the same native MultiText ordering, without clone slots."""
    reg = (tool.GetAttrs() or {}).get('TOOLS_RegID')
    if reg in TEXT_TOOLS - {'MultiText'}:
        return ['StyledText']
    if reg != 'MultiText':
        return []
    inputs = {v.GetAttrs().get('INPS_ID'): v for v in (tool.GetInputList() or {}).values()}
    keys = sorted((k for k in inputs if isinstance(k,str) and re.fullmatch(r'TextValue\d+',k)),
                  key=lambda k:int(k[len('TextValue'):]))
    order = tool.GetInput('TextOrder')
    if isinstance(order,dict):
        ordered = ['TextValue'+str(int(value)) for _,value in sorted(order.items())
                   if isinstance(value,(int,float)) and value == int(value)]
        keys = list(dict.fromkeys([k for k in ordered if k in keys] + keys))
    # TextValueN is the list label, not the rendered text. Actual text controls
    # can be absent from GetInputList when another MultiText row is selected.
    return ['Text'+k[len('TextValue'):]+'.StyledText' for k in keys
            if tool.GetInput('TextEnabled'+k[len('TextValue'):]) != 0]


def title_text_targets(comp):
    """Return observed literal targets plus skipped connected/expression inputs.

    A Follower's base text is its `Text` input, not its owner's connected
    `StyledText`. Keep all follower/keyframe connections intact.
    """
    targets, skipped, seen = [], [], set()
    for tool in (comp.GetToolList(False) or {}).values():
        attrs = tool.GetAttrs() or {}
        if attrs.get('TOOLS_RegID') not in TEXT_TOOLS:
            continue
        if attrs.get('TOOLS_RegID') == 'MultiText':
            inputs = {v.GetAttrs().get('INPS_ID'): v for v in (tool.GetInputList() or {}).values()}
            for key in title_text_keys(tool):
                inp = inputs.get(key)
                if inp is None:
                    inp = getattr(tool, key, None)
                if not inp or (inp.GetAttrs() or {}).get('INPS_ID') != key:
                    skipped.append({'owner':attrs.get('TOOLS_Name'), 'reason':f'{key} unavailable'})
                    continue
                index = key[len('Text'):-len('.StyledText')]
                if tool.GetInput('TextEnabled' + index) == 0 or tool.GetInput('TextLocked' + index) == 1:
                    skipped.append({'owner':attrs.get('TOOLS_Name'), 'reason':f'{key} disabled/locked; retained'})
                    continue
                if inp.GetExpression() or inp.GetConnectedOutput():
                    skipped.append({'owner':attrs.get('TOOLS_Name'), 'reason':f'{key} connected/expression retained'})
                    continue
                if isinstance(tool.GetInput(key), str):
                    targets.append({'tool':tool, 'tool_name':attrs.get('TOOLS_Name'),
                                    'input':key, 'owner':attrs.get('TOOLS_Name')})
            continue
        owner = attrs.get('TOOLS_Name')
        current, key = tool, 'StyledText'
        visited = set()
        for _ in range(12):
            attrs = current.GetAttrs() or {}
            name = attrs.get('TOOLS_Name')
            if name in visited:
                skipped.append({'owner': owner, 'reason': 'text modifier cycle'})
                break
            visited.add(name)
            inputs = {v.GetAttrs().get('INPS_ID'): v for v in (current.GetInputList() or {}).values()}
            inp = inputs.get(key)
            if not inp:
                skipped.append({'owner': owner, 'reason': f'{name}.{key} unavailable'})
                break
            if inp.GetExpression():
                skipped.append({'owner': owner, 'reason': f'{name}.{key} expression retained'})
                break
            output = inp.GetConnectedOutput()
            if output:
                modifier = output.GetTool()
                mod_attrs = modifier.GetAttrs() if modifier else {}
                mod_key = TEXT_MODIFIERS.get((mod_attrs or {}).get('TOOLS_RegID'))
                if not mod_key:
                    skipped.append({'owner': owner, 'reason': 'unsupported connected text modifier retained'})
                    break
                current, key = modifier, mod_key
                continue
            if not isinstance(current.GetInput(key), str):
                skipped.append({'owner': owner, 'reason': f'{name}.{key} is not literal text'})
                break
            identity = (name, key)
            if identity not in seen:
                seen.add(identity)
                targets.append({'tool': current, 'tool_name': name, 'input': key, 'owner': owner})
            break
    return targets, skipped
