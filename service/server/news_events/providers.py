"""Adapters only: no topic decisions, trading access or model calls."""
import json
import re
import ssl
import socket
import ipaddress
import http.client
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlencode, urljoin
from .model import Source, canonical_url, timestamp, text, event_type, fingerprint

DNS_POOL=ThreadPoolExecutor(max_workers=3,thread_name_prefix='phase2-provider-dns')
DNS_SLOTS=threading.BoundedSemaphore(3)


def resolve_public(host):
    # Bounded independent slots: one slow provider DNS lookup must not make
    # every other provider inherit Phase 1's single-resolver busy state.
    if not DNS_SLOTS.acquire(blocking=False):raise ProviderFailure('dns_capacity')
    try:future=DNS_POOL.submit(socket.getaddrinfo,host,443,type=socket.SOCK_STREAM)
    except Exception:
        DNS_SLOTS.release();raise ProviderFailure('dns_failed') from None
    future.add_done_callback(lambda _:DNS_SLOTS.release())
    try:return sorted({entry[4][0] for entry in future.result(timeout=3)})
    except (FutureTimeout,OSError):raise ProviderFailure('dns_failed') from None


class ProviderFailure(Exception):
    def __init__(self,reason,http_status=None,retry_after=0,terminal=False):
        self.reason,self.http_status,self.retry_after,self.terminal=reason,http_status,retry_after,terminal
        super().__init__(reason) # never includes a URL/query credential/HTTP body


class Transport:
    """Pinned public IP; at most one credential-free same-origin HTTPS redirect."""
    def __init__(self,allowed_hosts,timeout=12,max_bytes=1048576,user_agent='AI-Trader News Event Sandbox',read_timeout=None,prefer_ipv4=False):
        self.allowed_hosts=set(allowed_hosts); self.timeout=timeout; self.max_bytes=max_bytes
        self.user_agent=user_agent
        self.read_timeout=read_timeout
        self.prefer_ipv4=prefer_ipv4

    def request(self,url,params=None,headers=None,method='GET',body=None,_redirects=0):
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname not in self.allowed_hosts or p.username or p.password or p.port not in (None,443):
            raise ProviderFailure('unsafe_endpoint',terminal=True)
        started=time.monotonic()
        try:addresses=resolve_public(p.hostname)
        except Exception:raise ProviderFailure('dns_failed') from None
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise ProviderFailure('unsafe_address',terminal=True)
        if self.prefer_ipv4:
            addresses=sorted(addresses,key=lambda a:ipaddress.ip_address(a).version)
        connection=http.client.HTTPSConnection(p.hostname,timeout=min(3,self.timeout))
        raw=None
        def abort():
            try:
                if connection.sock:connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        timer=threading.Timer(max(.01,self.timeout-(time.monotonic()-started)),abort)
        timer.daemon=True
        stage='connect'
        try:
            raw=socket.create_connection((addresses[0],443),timeout=3)
            stage='tls'
            connection.sock=ssl.create_default_context().wrap_socket(raw,server_hostname=p.hostname)
            if self.read_timeout is not None:
                connection.sock.settimeout(min(self.timeout,self.read_timeout))
            timer.start()
            path=p.path or '/'
            query='&'.join(filter(None,[p.query,urlencode(params or {})]))
            if query:path+='?'+query
            data=json.dumps(body).encode() if body is not None else None
            stage='request'
            connection.request(method,path,data,{'User-Agent':self.user_agent,
                'Accept-Encoding':'identity',**(headers or {})})
            stage='headers'
            response=connection.getresponse()
            from retry_policy import retry_after
            if response.status in (301,302,307,308) and method=='GET' and not params and not body and not headers:
                target=urljoin(url,response.getheader('Location') or '')
                dest=urlsplit(target)
                # One HTTPS same-origin hop only. Re-resolve and pin public IP;
                # never forward credentials or accept a downgrade/redirect loop.
                if (_redirects==0 and target!=url and dest.scheme=='https' and dest.hostname==p.hostname
                        and not dest.username and not dest.password and dest.port in (None,443)):
                    timer.cancel();connection.close()
                    return self.request(target,_redirects=1)
            if response.status!=200:
                raise ProviderFailure('http_error',response.status,retry_after(response.getheader('Retry-After')),
                                      response.status in (400,401,403,404) or 300<=response.status<400)
            chunks=[]; size=0; stage='body'
            while True:
                chunk=response.read1(min(16384,self.max_bytes+1-size))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
                if size>self.max_bytes:raise ProviderFailure('body_too_large',terminal=True)
                if time.monotonic()-started>self.timeout:raise ProviderFailure('deadline')
            if response.getheader('Content-Encoding','identity')!='identity':
                raise ProviderFailure('compressed_response_not_supported',terminal=True)
            return b''.join(chunks)
        except ProviderFailure:raise
        except Exception as exc:
            reason='transport_failure'
            if self.read_timeout is not None:
                reason='transport_'+type(exc).__name__
                if self.prefer_ipv4 and isinstance(exc,OSError):
                    # Fixed stage + numeric errno only; never exception text/URL.
                    code=exc.errno if type(exc.errno) is int else 'unknown'
                    reason=f'transport_{stage}_oserror_{code}'
            raise ProviderFailure(reason) from None
        finally:
            timer.cancel();connection.close()
            if raw:raw.close()


@dataclass
class Config:
    provider_id:str
    endpoint:str
    publisher:str
    source_type:str='aggregator'
    enabled:bool=False
    rights:str='review_required'
    cadence:int=300
    credential:str=''
    removals_endpoint:str=''
    display_output:str='full'


class BaseProvider:
    def __init__(self,config,transport=None):
        self.config=config;self.provider_id=config.provider_id
        self.transport=transport or Transport([urlsplit(config.endpoint).hostname])

    def canonical_url(self,raw):return canonical_url(raw['url'])
    def source_timestamp(self,raw):return timestamp(raw['published_at'])
    def source_identity(self,raw):return str(raw.get('id') or self.canonical_url(raw))
    def raw_metadata(self,raw):
        return {k:raw[k] for k in ('id','updated','categories','exchange','accession','license_label','license_url','provider_tickers') if k in raw}

    def normalize(self,raw,collected_at):
        title,excerpt=text(raw.get('title')),text(raw.get('excerpt'))
        return Source(self.provider_id,self.source_identity(raw),self.canonical_url(raw),
            raw.get('publisher') or self.config.publisher,self.source_timestamp(raw),timestamp(collected_at),
            title,excerpt,self.config.source_type,tuple(raw.get('tickers') or ()),str(raw.get('cik') or ''),
            raw.get('event_type') or event_type(title,excerpt),tuple(raw.get('event_refs') or ()),
            raw.get('claims') or {},self.raw_metadata(raw),self.config.rights)

    def allowed(self):
        if not self.config.enabled:raise ProviderFailure('disabled',terminal=True)
        if self.config.rights not in ('internal_review','approved'):
            raise ProviderFailure('license_required',terminal=True)


class RSSProvider(BaseProvider):
    def fetch(self,state,now):
        self.allowed()
        raw=self.transport.request(self.config.endpoint)
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ProviderFailure('unsafe_xml',terminal=True)
        root=ET.fromstring(raw)
        rows=[]
        ns={'a':'http://www.w3.org/2005/Atom','c':'http://purl.org/rss/1.0/modules/content/',
            'dc':'http://purl.org/dc/elements/1.1/'}
        for node in root.findall('./channel/item')+root.findall('a:entry',ns):
            def value(tag):return node.findtext(tag,default='',namespaces=ns)
            link=value('link')
            if not link:
                links=node.findall('a:link',ns)
                link=next((n.get('href') for n in links if n.get('rel','alternate')=='alternate'),'')
            excerpt=value('description') or value('c:encoded') or value('a:summary') or value('a:content')
            refs=re.findall(r'''href=["'](https?://[^"']+)''',excerpt)
            rows.append({'id':value('guid') or value('a:id') or link,'url':link,
                'title':value('title') or value('a:title'),'excerpt':excerpt,
                'publisher':value('dc:publisher') or self.config.publisher,
                'published_at':value('pubDate') or value('a:published'),
                'event_refs':refs,'categories':[v.text for v in node.findall('category') if v.text]})
        return {'items':rows,'cursor':timestamp(now),'coverage':'broad RSS feed window; not full-universe guarantee'}


class BenzingaProvider(BaseProvider):
    def fetch(self,state,now):
        self.allowed()
        if not self.config.credential:raise ProviderFailure('credential_required',terminal=True)
        if self.config.display_output not in ('headline','abstract','full'):raise ProviderFailure('invalid_display_output',terminal=True)
        params={'token':self.config.credential,'pageSize':100,'displayOutput':self.config.display_output,'page':state.get('page',0)}
        if state.get('cursor'):params['updatedSince']=int(datetime.fromisoformat(state['cursor']).timestamp())-300
        rows=json.loads(self.transport.request(self.config.endpoint,params,{'Accept':'application/json'}))
        if not isinstance(rows,list):raise ProviderFailure('provider_schema',terminal=True)
        items=[{'id':r['id'],'title':r['title'],'url':r['url'],'published_at':r['created'],
            'updated':r.get('updated'),'excerpt':r.get('body') or r.get('teaser',''),
            'tickers':[s['name'] for s in r.get('stocks',[])],
            'event_refs':re.findall(r'''href=["'](https?://[^"']+)''',r.get('body',''))} for r in rows]
        # Full pages are paginated before advancing the persisted delta cursor.
        full=len(rows)==100
        # Advance only to the START of the pagination cycle. The next delta
        # overlaps it, covering releases added while pages were being fetched.
        cycle=state.get('cycle_started') or timestamp(now)
        withdrawn=[]
        if self.config.removals_endpoint:
            removed=json.loads(self.transport.request(self.config.removals_endpoint,
                {'token':self.config.credential},{'Accept':'application/json'}))
            if not isinstance(removed,dict) or not isinstance(removed.get('removed'),list):
                raise ProviderFailure('removal_schema',terminal=True)
            withdrawn=[str(item['id']) for item in removed['removed']]
        return {'items':items,'cursor':state.get('cursor') if full else cycle,
                'withdrawn_ids':withdrawn,
                'cycle_started':cycle if full else None,
                'page':params['page']+1 if full else 0,'coverage':'licensed broad news feed; updatedSince delta'}


class TipRanksProvider(BaseProvider):
    """Contract-configured enterprise feed; no guessed/private website endpoint.

    Public enterprise documentation does not disclose a response contract.
    Fields/path/header must be supplied from the licensed contract before use.
    """
    def __init__(self,config,transport=None,contract=None):
        super().__init__(config,transport);self.contract=contract

    def fetch(self,state,now):
        self.allowed()
        if not self.config.credential or not self.contract:raise ProviderFailure('enterprise_contract_required',terminal=True)
        spec=self.contract
        headers={spec['auth_header']:spec.get('auth_prefix','')+self.config.credential,'Accept':'application/json'}
        params={spec['cursor_param']:state.get('cursor','')}
        data=json.loads(self.transport.request(self.config.endpoint,params,headers))
        rows=data[spec['items_field']]
        items=[{field:r[path] for field,path in spec['fields'].items()} for r in rows]
        return {'items':items,'cursor':data[spec['next_cursor_field']],'coverage':'licensed enterprise contract'}


class ExistingProvider(BaseProvider):
    """Wrap existing bulk collectors (SEC/Yahoo/Telegram/FJ/official feeds).

    Caller injects collector; never starts production worker or rereads old DB.
    """
    def __init__(self,config,collector):
        super().__init__(config);self.collector=collector
    def fetch(self,state,now):
        self.allowed()
        value=self.collector(state,now)
        items=[]
        for r in value['items']:
            items.append({**r,'id':r.get('canonical_key') or r.get('id') or r['url'],
                'excerpt':r.get('source_excerpt',''),'tickers':r.get('verified_tickers',r.get('tickers',[]))})
        return {**value,'items':items,'cursor':value.get('cursor',timestamp(now))}


def registry(configs,existing=None,transport_factory=None,tipranks_contract=None):
    """Provider selection stays here, never in core routing or analysis."""
    result=[]
    from .investing import InvestingProvider
    from .press_feed import PressFeedProvider
    classes={'benzinga':BenzingaProvider,'tipranks':TipRanksProvider,'investing':InvestingProvider,
             'prnewswire':PressFeedProvider,'globenewswire':PressFeedProvider}
    for cfg in configs:
        if cfg.provider_id in (existing or {}):
            result.append(ExistingProvider(cfg,existing[cfg.provider_id]));continue
        cls=classes.get(cfg.provider_id,RSSProvider)
        kw={'contract':tipranks_contract} if cls is TipRanksProvider else {}
        result.append(cls(cfg,transport_factory(cfg) if transport_factory else None,**kw))
    return result


DEFAULT_CONFIGS=[
    Config('investing','https://www.investing.com/rss/news.rss','Investing.com','established financial media'),
    Config('globenewswire','https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies','GlobeNewswire','press_release'),
    Config('prnewswire','https://www.prnewswire.com/rss/news-releases-list.rss','PR Newswire','press_release'),
    Config('benzinga','https://api.benzinga.com/api/v2/news','Benzinga','established financial media',
           removals_endpoint='https://api.benzinga.com/api/v2/news-removed'),
    Config('tipranks','','TipRanks','established financial media'),
]
