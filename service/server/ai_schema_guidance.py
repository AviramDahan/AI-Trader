"""Describe trusted numeric bounds; never rescale or accept invalid output."""
import math


def numeric_guidance(schema):
    if not isinstance(schema, dict):
        return ''
    fields = []
    def visit(node, path, depth=0):
        if not isinstance(node, dict) or depth>10:
            return
        if isinstance(node.get('type'),str) and node['type'] in {'number','integer'}:
            limits=[]
            for key, phrase in [('minimum','at least'),('maximum','at most')]:
                value=node.get(key)
                if type(value) in (int,float) and math.isfinite(value):
                    limits.append(f'{phrase} {value}')
            if limits:
                fields.append(f'{path or "result"}: {node["type"]}, ' + ', '.join(limits))
        for name, child in (node.get('properties') or {}).items():
            visit(child, f'{path}.{name}' if path else name, depth+1)
        if isinstance(node.get('items'),dict):
            visit(node['items'], path+'[]', depth+1)
    visit(schema, '')
    if not fields:
        return ''
    return (' Numeric output constraints: ' + '; '.join(fields) +
            '. Use the exact requested scale, never a percentage on a 0-to-100 scale '
            'for a 0-to-1 field. Preserve source facts; these bounds apply only to output fields.')


def repair_guidance(schema, failure):
    # Failure text and model output are deliberately excluded from the prompt.
    import json
    try:
        validator = json.loads(failure).get('validator')
    except (ValueError, TypeError, AttributeError):
        validator = None
    detail = f' The previous result violated {validator}.' if validator in {'minimum', 'maximum', 'type'} else ''
    return ('Return valid JSON matching the required schema; do not invent missing source facts.' +
            detail + numeric_guidance(schema))
