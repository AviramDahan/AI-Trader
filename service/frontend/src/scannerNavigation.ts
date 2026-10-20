import { preserveMiniApp } from './telegramMiniApp'

/** Router-relative path. Link supplies the deployment basename; no auth data is copied. */
export function scannerRecordPath(kind: 'signal'|'trade', id: unknown, history: boolean, search: string) {
  if (!/^[1-9]\d*$/.test(String(id))) return null
  return preserveMiniApp(`/market?tab=${history?'results':'signals'}`,search,`#${kind}-${id}`) +
    (new URLSearchParams(search).get('miniapp')==='1'?'':`#${kind}-${id}`)
}

export function revealScannerRecord(hash: string, doc: Document = document): boolean {
  if (!/^#(?:signal|trade)-[1-9]\d*$/.test(hash)) return false
  const node=doc.getElementById(hash.slice(1))
  if(!node)return false
  for(let parent:HTMLElement|null=node;parent;parent=parent.parentElement) {
    if(parent.tagName==='DETAILS')(parent as HTMLDetailsElement).open=true
  }
  node.setAttribute('tabindex','-1')
  node.scrollIntoView({behavior:'auto',block:'start'})
  node.focus({preventScroll:true})
  return true
}
