export function opsFixture(mode='normal') {
  const at = new Date().toISOString()
  const ids = ['news_feed','sec_intelligence','quotes','scan','ai_local','ai_cloud','news_ai','paper','monitor','telegram','api','database','backup']
  const nodes = ids.map(id => ({id,state:['paper','ai_cloud'].includes(id)?'idle':'healthy',
    reason:id==='ai_local'?'model_ready_not_inference_proof':id==='ai_cloud'?'paid_fallback_budget_available_not_connection_proof':id==='paper'?'retained_paper_state':'recent_completed_check',
    observed_at:at,last_success_at:at,lease_holders:['scan','monitor','telegram'].includes(id)?1:undefined,metrics:{}}))
  const get = id => nodes.find(n=>n.id===id)
  get('news_feed').metrics={queue:0,provider_issues:1}
  get('news_feed').state='degraded';get('news_feed').reason='partial_provider_coverage'
  get('news_feed').providers=[{id:'yahoo_priority',status:'ok',last_success_at:at},{id:'globenewswire',status:'requires_configuration',last_success_at:null}]
  get('sec_intelligence').metrics={issuers:515,completed:515,errors:0}
  get('scan').metrics={universe_count:518,technical_candidates_count:26,ai_selected_count:6,signals_published:0,last_completed_at:at}
  get('monitor').bars=[{ticker:'ALFA',bar_started_at:at,fresh_regular_session:true}]
  get('paper').metrics={open_positions:2,pending_orders:1,holds:0}
  get('telegram').metrics={public_delivery_queued:0,admin_delivery_queued:0}
  get('database').metrics={schema:7}
  get('backup').lease_holders=null // No dedicated role lease is checked for this component.
  const data={version:1,observed_at:at,build_sha:'1'.repeat(40),read_only:true,overall:'attention',market:{is_open:true,reason:'open'},nodes}
  if(mode==='failure'){get('ai_local').state='failed';get('ai_local').reason='private_relay_unavailable';data.overall='failed'}
  if(mode==='busy'){get('ai_local').state='idle';get('ai_local').reason='gpu_busy_or_loading'}
  if(mode==='partial')get('sec_intelligence').metrics.completed=460
  if(mode==='stale')data.observed_at=new Date(Date.now()-120000).toISOString()
  if(mode==='closed'){data.market.is_open=false;get('monitor').bars[0].fresh_regular_session=null}
  if(mode==='empty')return null
  return data
}
