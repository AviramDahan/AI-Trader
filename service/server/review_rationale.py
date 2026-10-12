"""Price facts and bounded rationale checks, never an action/level generator."""
import copy
import json
import math
import re
from decimal import Decimal

from final_ai import PROPERTIES, SchemaFailure, validate_schema

VERSION = 'entry_price_contract_v1'
RELATIONS = ('equal','above','below','unknown')
CONCERNS = ('none','quote_above_planned_entry','quote_below_planned_entry','comparison_unavailable')
PROTECTED = ('action','confidence','news_sentiment','news_relevance','time_horizon')
SCHEMA = {'type':'object','additionalProperties':False,
    'properties':{**copy.deepcopy(PROPERTIES),
        'entry_price_relation':{'type':'string','enum':list(RELATIONS)},
        'entry_price_concern':{'type':'string','enum':list(CONCERNS)}},
    'required':[*PROPERTIES,'entry_price_relation','entry_price_concern']}


def price_facts(candidate,context):
    """Only compare this review's verified quote with its saved plan, not daily close."""
    out=dict(version=VERSION,status='UNKNOWN',relation='unknown',quote_price=None,
             planned_entry=None,quote_at=None,basis='review_quote_vs_validated_plan_entry')
    plan=candidate.get('validated_target_plan') or {}
    quote=context.get('entry_quote') or {}
    if not isinstance(plan,dict) or not isinstance(quote,dict):return out
    values=(quote.get('price'),plan.get('entry'))
    if (not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0 for v in values)
        or values[0]!=candidate.get('entry') or not quote.get('as_of')):
        return out
    # The quote's own gate remains unchanged. Facts cannot turn an inconsistent,
    # future or stale timestamp into a verified price comparison.
    from review_evidence import instant
    try:
        age=(instant(context['prepared_at'])-instant(quote['as_of'])).total_seconds()
        if not 0<=age<=720:return out
    except (ValueError,TypeError,KeyError):return out
    live,planned=map(lambda v:Decimal(str(v)),values)
    out.update(status='VERIFIED',relation='equal' if live==planned else 'above' if live>planned else 'below',
               quote_price=values[0],planned_entry=values[1],quote_at=quote['as_of'])
    return out


# This intentionally recognizes ONLY the observed concrete English comparison,
# not broad sentiment, targets, conditionals, "extended" or trading instructions.
# It can reject a known contradiction; it can never authorize or change a trade.
PRICE_ASSERTION=re.compile(r'\b(?:the\s+)?(?:quote|current\s+price|live\s+quote|entry\s+quote)\s+'
    r'(?:is|trades|sits)\s+(?:already\s+)?(above|below|higher\s+than|lower\s+than)\s+'
    r'(?:the\s+)?planned\s+entry\b',re.I)
NONASSERTION=re.compile(r'\b(?:if|unless|whether|no|not|never|hypothetical|could|would)\b',re.I)


def contradictory_price_statement(reason,relation):
    if relation=='unknown':return None
    text=str(reason)
    for match in PRICE_ASSERTION.finditer(text):
        prefix=re.split(r'[.;!?\n]',text[:match.start()])[-1]
        if NONASSERTION.search(prefix):continue
        claimed='above' if match.group(1).lower() in ('above','higher than') else 'below'
        if claimed!=relation:return claimed
    return None


class RationaleFailure(SchemaFailure):
    def __init__(self,kind,facts,value):
        super().__init__('entry_rationale_'+kind)
        self.entry_rationale_failure=dict(version=VERSION,kind=kind,expected_relation=facts['relation'])
        locked={k:value[k] for k in PROTECTED}
        self.repair_instruction=json.dumps(dict(
            task='Correct only the factual entry assessment and explanation; no new decision.',
            locked_decision=locked,entry_price_facts=facts,
            constraints=['Copy all locked_decision fields EXACTLY, including HOLD and scores.',
                'Return the complete required schema. Do not change action to obtain acceptance.',
                'Daily reference close is historical context, not planned entry.',
                'Do not claim above/below planned entry contrary to entry_price_facts.',
                'Keep other valid HOLD grounds; never invent relative volume or confirmation.']))


class Validator:
    """Callable with a request schema; one shared retry budget stays in final_ai."""
    response_schema=SCHEMA

    def __init__(self,facts,base_validator):
        self.facts=copy.deepcopy(facts)
        self.base_validator=base_validator
        self.locked=None

    def schema_repair_instruction(self,value):
        """Lock a well-formed original decision even if the new facts are absent.

        Invalid JSON/invalid core fields cannot provide a decision to preserve.
        This never guesses them. A direction conflict remains non-repairable.
        """
        if not isinstance(value,dict):return None
        core={k:value[k] for k in PROPERTIES if k in value}
        try:validate_schema(core)
        except SchemaFailure:return None
        core=self.base_validator(core)
        if self.locked is None:self.locked={k:core[k] for k in PROTECTED}
        return RationaleFailure('missing_or_invalid_assessment',self.facts,
            dict(core,**self.locked)).repair_instruction

    def __call__(self,value):
        value=self.base_validator(value)  # Direction/score guards remain first.
        if self.locked is not None and any(value[k]!=v for k,v in self.locked.items()):
            raise ValueError('rationale_repair_changed_decision')
        relation=self.facts['relation']
        concern=value['entry_price_concern']
        expected={'none':None,'quote_above_planned_entry':'above',
                  'quote_below_planned_entry':'below','comparison_unavailable':'unknown'}[concern]
        kind=('comparison_mismatch' if value['entry_price_relation']!=relation else
              'unsupported_price_concern' if expected is not None and expected!=relation else
              'unsupported_price_statement' if contradictory_price_statement(value['reason'],relation) else None)
        if kind:
            self.locked={k:value[k] for k in PROTECTED}
            raise RationaleFailure(kind,self.facts,value)
        result=dict(value)
        result['entry_rationale']=dict(version=VERSION,
            status='REPAIRED' if self.locked is not None else 'VERIFIED' if relation!='unknown' else 'UNVERIFIABLE',
            price_relation=relation,price_concern=concern,
            prose_check_scope='KNOWN_EXPLICIT_PRICE_COMPARISON_ONLY')
        return result
