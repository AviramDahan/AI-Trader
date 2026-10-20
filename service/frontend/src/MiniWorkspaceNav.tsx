export type MiniView = 'map'|'positions'|'more'
export function MiniWorkspaceNav({he,view,onSelect,secondary=false}:{he:boolean;view?:MiniView;onSelect:(view:MiniView)=>void;secondary?:boolean}) {
  const t=(a:string,b:string)=>he?a:b
  return <nav className={`mini-bottom-nav${secondary?' mini-secondary-nav':''}`} aria-label={t('ניווט ראשי','Main navigation')}>
    {(['map','positions','more'] as const).map((key,n)=><button type="button" key={key}
      aria-label={t(...([['כורים','Reactors'],['פוזיציות פעילות','Active positions'],['עוד','More']][n] as [string,string]))}
      aria-current={view===key?'page':undefined} onClick={()=>onSelect(key)}>
      <span className="mini-nav-icon" aria-hidden="true">{['◉','▥','•••'][n]}</span>
      <span className="mini-nav-label">{key==='positions'?<><span>{t('פוזיציות','Active')}</span><span>{t('פעילות','positions')}</span></>:t(key==='map'?'כורים':'עוד',key==='map'?'Reactors':'More')}</span>
    </button>)}
  </nav>
}
