"""Transactional sandbox event store, portable across SQLite and PostgreSQL.

Connections are injected; no production config/.env discovery. No trading writes.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import re
import uuid
from .model import fingerprint, text, timestamp, anchors


class Store:
    def __init__(self, connect, *, sandbox=False, production=False):
        if not sandbox and not production: raise ValueError('phase2_requires_isolated_sandbox')
        if sandbox and production: raise ValueError('conflicting_store_modes')
        self.connect=connect
        self.production=production

    @contextmanager
    def transaction(self, write=False):
        c=self.connect()
        try:
            if write:
                if getattr(c,'_backend','sqlite')=='postgres':
                    # Transaction only covers state changes, never HTTP/LLM.
                    c.execute('SELECT pg_advisory_xact_lock(719329,2)')
                else: c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:c.close()

    def install(self):
        if self.production: raise ValueError('use_numbered_production_migration')
        with self.transaction(True) as c:
            if getattr(c,'_backend','sqlite')=='postgres':
                schema=c.execute('SELECT current_schema() AS name').fetchone()['name']
                if not schema.startswith(('test_','news_phase2_')):
                    raise ValueError('production_schema_forbidden')
            # SQLite sandbox MUST be a fresh isolated file, never legacy DB.
            else:
                names={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if names-{'sqlite_sequence'} and any(not n.startswith('ne_') for n in names-{'sqlite_sequence'}):
                    raise ValueError('production_sqlite_forbidden')
            for statement in (Path(__file__).with_name('schema.sql').read_text()).split(';'):
                if statement.strip():c.execute(statement)

    def metric(self,c,stage,result,at,event_id=None,provider_id=None,**data):
        c.execute('INSERT INTO ne_metrics VALUES(?,?,?,?,?,?,?)',
                  (uuid.uuid4().hex,event_id,provider_id,stage,result,at,json.dumps(data,sort_keys=True)))

    def event(self,event_id):
        with self.transaction() as c:
            r=c.execute('SELECT * FROM ne_events WHERE event_id=?',(event_id,)).fetchone()
            if not r:return None
            body=json.loads(r['body_json'])
            body.update(analysis_status=r['status'],non_publication_reason=r['reason'])
            return {**dict(r),'body':body}

    def ingest(self,source,identities,reason=None):
        collected=timestamp(source.collected_at)
        published=timestamp(source.published_at)
        # Formatting and collection dates alone never create source revisions.
        content=fingerprint([text(source.title),text(source.source_excerpt),source.claims])
        source_key=fingerprint([source.provider_id,source.source_id,content])
        keys=anchors(source,identities)
        with self.transaction(True) as c:
            if c.execute('SELECT 1 FROM ne_withdrawals WHERE provider_id=? AND source_id=?',
                         (source.provider_id,source.source_id)).fetchone():
                self.metric(c,'ingest','source_withdrawn',collected,provider_id=source.provider_id)
                return None
            seen=c.execute('SELECT event_id FROM ne_sources WHERE source_key=?',(source_key,)).fetchone()
            if seen:
                self.metric(c,'ingest','unchanged_source',collected,seen['event_id'],source.provider_id,ai_calls_avoided=0)
                return seen['event_id']
            ids={r['event_id'] for key in keys for r in c.execute('SELECT event_id FROM ne_anchors WHERE anchor=?',(key,))}
            if len(ids)>1:
                # Never silently merge two already-published stories; hold bridge.
                c.execute('INSERT INTO ne_quarantine VALUES(?,?,?,?,?) ON CONFLICT(source_key) DO NOTHING',
                          (source_key,json.dumps(source.data()),'ambiguous_event_bridge',json.dumps(sorted(ids)),collected))
                self.metric(c,'ingest','ambiguous_event_bridge',collected,provider_id=source.provider_id)
                return None
            event_id=next(iter(ids),uuid.uuid4().hex)
            old=c.execute('SELECT * FROM ne_events WHERE event_id=?',(event_id,)).fetchone()
            if not old:
                c.execute('INSERT INTO ne_events VALUES(?,?,?,?,?,?,?)',(event_id,'{}','', 'pending',reason,collected,collected))
            data=source.data()
            data.update(published_at=published,collected_at=collected)
            # Keep every revision; active evidence uses the newest seen revision
            # of each provider item, not a mixture of its old and corrected text.
            c.execute('UPDATE ne_sources SET active=0 WHERE event_id=? AND provider_id=? AND source_id=?',
                      (event_id,source.provider_id,source.source_id))
            c.execute('''INSERT INTO ne_sources(source_key,event_id,provider_id,content_hash,body_json,collected_at,source_id,active)
                VALUES(?,?,?,?,?,?,?,1)''',(source_key,event_id,source.provider_id,content,json.dumps(data),collected,source.source_id))
            for key in keys:c.execute('INSERT INTO ne_anchors VALUES(?,?) ON CONFLICT(anchor) DO NOTHING',(key,event_id))
            sources=[json.loads(r['body_json']) for r in c.execute('SELECT body_json FROM ne_sources WHERE event_id=? AND active=1 ORDER BY source_key',(event_id,))]
            normalized,conflicts=combine(sources)
            version=fingerprint([{'text':v['text'].lower(),'claims':v['claims']} for v in normalized])
            prior=json.loads(old['body_json']) if old else {}
            changed=not old or old['evidence_version']!=version
            material=not old or material_change(prior.get('normalized_evidence',[]),normalized)
            status='blocked' if reason else 'pending'
            if old and not changed:status=old['status']; reason=old['reason']
            elif old and not material and not reason:
                started=c.execute('SELECT 1 FROM ne_analysis WHERE event_id=? LIMIT 1',(event_id,)).fetchone()
                if started:status='needs_material_review'; reason='new_text_materiality_unverified'
            if conflicts:status='blocked';reason='source_conflict'
            if old and old['reason']=='source_retracted':status='blocked';reason='source_retracted'
            from .queue_health import ACTIVE, entered_at
            queue_entered_at = None
            if status in ACTIVE:
                if old and old['status'] in ACTIVE:
                    # A poll, new attribution, version update or claim must not
                    # reset the clock while work is continuously outstanding.
                    v=c.execute('SELECT created_at FROM ne_versions WHERE event_id=? AND version=?',
                                (event_id,old['evidence_version'])).fetchone()
                    queue_entered_at=entered_at({**dict(old),'version_created_at':v['created_at'] if v else None})
                else:
                    queue_entered_at=collected
            body=dict(event_id=event_id,canonical_event_id=event_id,providers=sorted({s['provider_id'] for s in sources}),
                sources=sources,source_urls=sorted({s['url'] for s in sources}),source_type=sorted({s['source_type'] for s in sources}),
                publisher=sorted({s['publisher'] for s in sources}),
                published_at=min([s['published_at'] for s in sources]+([prior['published_at']] if prior else [])),
                collected_at=collected,title=source.title,source_excerpt=source.source_excerpt,
                normalized_evidence=normalized,tickers=sorted(v['ticker'] for v in identities),
                company_identity=identities,cik=sorted({v['cik'] for v in identities if v.get('cik')}),
                event_type=prior.get('event_type') if source.event_type=='unknown' else source.event_type,provenance=[{'provider_id':s['provider_id'],'url':s['url'],
                    'published_at':s['published_at'],'collected_at':s['collected_at'],'rights':s['rights']} for s in sources],
                content_hash=content,evidence_version=version,analysis_status=status,
                non_publication_reason=reason,conflicts=conflicts,queue_entered_at=queue_entered_at)
            c.execute('UPDATE ne_events SET body_json=?,evidence_version=?,status=?,reason=?,updated_at=? WHERE event_id=?',
                      (json.dumps(body),version,status,reason,collected,event_id))
            c.execute('INSERT INTO ne_versions VALUES(?,?,?,?) ON CONFLICT(event_id,version) DO NOTHING',
                      (event_id,version,json.dumps(normalized),collected))
            self.metric(c,'ingest','new_event' if not old else 'material_update' if changed and material else 'unverified_update' if changed else 'cross_source_duplicate',
                        collected,event_id,source.provider_id,ai_calls_avoided=int(bool(old and not changed)),conflict=bool(conflicts))
            return event_id

    def withdraw(self,provider_id,source_id,now):
        """Persist a tombstone before new polls can re-introduce a withdrawn item."""
        with self.transaction(True) as c:
            c.execute('INSERT INTO ne_withdrawals VALUES(?,?,?) ON CONFLICT(provider_id,source_id) DO NOTHING',
                      (provider_id,str(source_id),timestamp(now)))
            ids={r['event_id'] for r in c.execute('SELECT event_id FROM ne_sources WHERE provider_id=? AND source_id=?',
                                                (provider_id,str(source_id)))}
            for event_id in ids:
                c.execute('UPDATE ne_sources SET active=0 WHERE event_id=? AND provider_id=? AND source_id=?',
                          (event_id,provider_id,str(source_id)))
                c.execute("UPDATE ne_events SET status='blocked',reason='source_retracted' WHERE event_id=?",(event_id,))
                c.execute("UPDATE ne_delivery SET status='cancelled' WHERE event_id=? AND status='sandbox_pending'",(event_id,))
                self.metric(c,'withdrawal','held_for_review',timestamp(now),event_id,provider_id)


def combine(sources):
    # Identical facts shared across outlets count once in the model input.
    items={}
    claims={}
    for s in sources:
        # Title is source evidence too: headline-only material corrections must
        # never be silently ignored just because the excerpt did not change.
        excerpt=text(s['title'])+'\n'+text(s['source_excerpt'])
        if excerpt:
            key=fingerprint(excerpt.lower())
            entry=items.setdefault(key,{'text':excerpt,'claims':{},'attributions':[]})
            entry['attributions'].append({'provider_id':s['provider_id'],'publisher':s['publisher'],
                'url':s['url'],'trust':s['source_type']})
            # Narrow deterministic contradictions: same sentence frame with
            # different quantities. Never equate different periods/metrics via
            # fuzzy matching. Adapters may supply stronger structured claims.
            grounded={**quantity_claims(excerpt),**s['claims']}
            for k,v in grounded.items():
                # Provider structured facts must supply verbatim grounding.
                if not isinstance(v,dict) or not v.get('quote') or v['quote'] not in excerpt or str(v.get('value','')) not in v['quote']:
                    continue
                entry['claims'][k]=v
                claims.setdefault(k,set()).add(str(v['value']))
    ordered=sorted(items.values(),key=lambda v:fingerprint(v['text'].lower()))
    conflicts=[{'fact':k,'values':sorted(v),'status':'contested',
                'preferred_primary_values':sorted({str(i['claims'][k]['value']) for i in ordered
                    if k in i['claims'] and any(a['trust'] in ('official/regulatory','company official') for a in i['attributions'])})}
               for k,v in claims.items() if len(v)>1]
    return ordered,conflicts


def quantity_claims(excerpt):
    result={}
    for sentence in re.split(r'(?<=[.!?])\s+|\n',excerpt):
        # At least eight words: avoid generic table fragments such as "Price 5".
        if len(sentence.split())<8:continue
        matches=list(re.finditer(r'\b\d+(?:[.,]\d+)*\b',sentence))
        # Multiple numbers can represent dates/periods/comparisons, not a single
        # fact. Hold those for attributed analysis instead of invented mapping.
        if len(matches)!=1:continue
        match=matches[0];frame=sentence[:match.start()].lower()+'#'+sentence[match.end():].lower()
        result['quantity_frame:'+fingerprint(frame)]={'value':match.group(),'quote':sentence}
    return result


def material_change(old,new):
    oldtext={text(v['text']).lower() for v in old}
    additions=[v for v in new if text(v['text']).lower() not in oldtext]
    if not additions:return False
    if not old:return True
    oldclaims={k:str(val['value']) for v in old for k,val in v.get('claims',{}).items()}
    for v in additions:
        if any((k in oldclaims and oldclaims[k]!=str(val['value'])) or
               (k not in oldclaims and not k.startswith('quantity_frame:'))
               for k,val in v.get('claims',{}).items()):return True
        if any(a['trust'] in ('official/regulatory','company official') for a in v['attributions']):
            oldvalues=set(oldclaims.values())
            if any(str(val['value']) not in oldvalues for val in v.get('claims',{}).values()):return True
    # New phrasing is not proof of a material new fact; preserve for review.
    return False
