"""Lossless syntax normalization for canonical news, never fact/JSON repair.

Only a complete code fence or identical repeated objects is removable. Never
select the first of conflicting objects or ignore prose. No network or logging.
"""
import json
import re


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('ai_object_required')
        result[key]=value
    return result


def _constant(_):raise ValueError('ai_object_required')


def parse(content):
    decoder=json.JSONDecoder(object_pairs_hook=_pairs,parse_constant=_constant)
    try:return decoder.decode(content),None
    except json.JSONDecodeError as original:
        if len(content)>65536:raise
        value=content.strip()
        fence=re.fullmatch(r'```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```',value,re.I)
        if fence:value=fence[1].strip()
        objects=[];position=0
        try:
            while position<len(value) and len(objects)<3:
                item,position=decoder.raw_decode(value,position)
                if not isinstance(item,dict):raise original
                objects.append(item)
                while position<len(value) and value[position].isspace():position+=1
        except json.JSONDecodeError:raise original from None
        # JSON serialization distinguishes true from 1 and does not discard keys.
        if (not objects or position!=len(value) or
                len({json.dumps(v,sort_keys=True,ensure_ascii=True) for v in objects})!=1):
            raise original
        if not fence and len(objects)==1:raise original
        return objects[0],('fenced_identical_objects' if fence and len(objects)>1 else
                           'code_fence' if fence else 'identical_objects')
