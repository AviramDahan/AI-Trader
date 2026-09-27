"""Read-only public feed diagnostics; no application config, AI or Telegram."""
import json
import socket
import ssl
import time
import http.client
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

URLS={
 'globenewswire':'https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies',
 'investing':'https://www.investing.com/rss/news.rss',
}

for provider,url in URLS.items():
    result={'provider':provider};start=time.monotonic();sock=None
    try:
        host=urlsplit(url).hostname
        addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        result['dns']='PASS';result['address_count']=len(addresses)
        sock=socket.create_connection((addresses[0][4][0],443),timeout=8)
        sock=ssl.create_default_context().wrap_socket(sock,server_hostname=host)
        result['tls']='PASS';result['tls_version']=sock.version()
        conn=http.client.HTTPSConnection(host,timeout=10);conn.sock=sock
        conn.request('GET',urlsplit(url).path,headers={'User-Agent':'AI-Trader feed availability check','Accept-Encoding':'identity'})
        response=conn.getresponse();result['http']=response.status
        if response.status==200:
            data=response.read(1048577)
            if len(data)>1048576:raise ValueError('body_limit')
            root=ET.fromstring(data);nodes=root.findall('./channel/item')
            result.update(parse='PASS',items=len(nodes),publication_dates=[n.findtext('pubDate') for n in nodes[:3]])
        else:result['retry_after']=response.getheader('Retry-After')
    except Exception as exc:
        result['failure']=type(exc).__name__
    finally:
        if sock:sock.close()
    result['seconds']=round(time.monotonic()-start,3)
    print(json.dumps(result),flush=True)
