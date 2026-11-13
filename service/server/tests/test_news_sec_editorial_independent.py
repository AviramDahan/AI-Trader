"""Independent editorial regression cases; synthetic retained facts only.

No provider, AI, Telegram, trading operation or real database is required.
"""
import copy

import pytest

import sec_intelligence as sec
from test_news_events import env


@pytest.fixture(autouse=True)
def no_live_effects(monkeypatch):
    monkeypatch.setattr(sec, 'fetch', lambda *a, **k: pytest.fail('provider IO forbidden'))
    for name in ('SEC_INTELLIGENCE_MATERIAL_CHANGE_PCT','SEC_INTELLIGENCE_MATERIAL_MARGIN_PP'):
        monkeypatch.delenv(name, raising=False)


def comparison(metric='revenue', *, current=120_000_000, previous=100_000_000,
               end='2026-09-30', start='2026-07-01', prior_end='2025-09-30',
               prior_start='2025-07-01', pct=20.0, unit='USD'):
    return dict(metric=metric, namespace='us-gaap',tag={
        'revenue':'Revenues','cash':'CashAndCashEquivalentsAtCarryingValue',
        'long_term_debt':'LongTermDebtNoncurrent','operating_income':'OperatingIncomeLoss'}[metric],
        unit=unit,start=start,end=end,value=current,accession='0000000001-26-000001',
        reason='comparable_prior',change_pct=pct,source_url='https://data.sec.gov/synthetic',
        previous=dict(value=previous,accession='0000000001-25-000001',
                      start=prior_start,end=prior_end,filed='2025-10-20'))


def render(*rows):
    return sec._material_public_fact(
        {'accession':'0000000001-26-000001','form':'10-Q','accepted_at':'2026-10-20T12:00:00Z'},
        {'kind':'financial','comparisons':list(rows)},None)


@pytest.mark.parametrize('reverse',[False,True])
def test_newest_period_not_older_high_percentage_comparative(reverse):
    newest=comparison()
    old=comparison(current=100_000_000,previous=25_000_000,end='2025-09-30',start='2025-07-01',
                   prior_end='2024-09-30',prior_start='2024-07-01',pct=300.0)
    rows=[newest,old]
    if reverse:rows.reverse()
    result=render(*rows)
    assert result is not None and '2026' in result
    assert '300.0%' not in result and '300%' not in result


def test_tiny_cash_percentage_cannot_replace_operating_context():
    cash=comparison('cash',current=300,previous=100,start=None,prior_start=None,pct=200.0)
    result=render(comparison(),cash)
    assert result is not None and 'הכנסות' in result
    assert '2026' in result


def test_selected_fact_exposes_period_comparator_and_value_unit_not_only_percent():
    result=render(comparison())
    assert result is not None
    assert '2026' in result and '2025' in result
    assert any(unit in result for unit in ('USD','דולר','$'))
    assert any(value in result for value in ('120','120,000,000'))
    assert any(value in result for value in ('100','100,000,000'))


def test_no_new_materiality_floor_or_fake_zero_baseline_growth():
    assert render(comparison(current=101_000_000,pct=1.0)) is None
    zero=comparison(current=120_000_000,previous=0,pct=None)
    zero['reason']='zero_denominator'
    result=render(zero)
    assert result is None or ('inf' not in result.lower() and 'nan' not in result.lower()
                              and '100%' not in result)


def test_formatter_does_not_mutate_retained_comparisons():
    original=[comparison(),comparison('cash',current=300,previous=100,start=None,prior_start=None,pct=200)]
    before=copy.deepcopy(original)
    render(*original)
    assert original==before


@pytest.mark.parametrize('latest_kind',['immaterial','uncomparable'])
def test_old_large_delta_cannot_resurrect_when_newest_period_has_no_material_comparison(latest_kind):
    newest=comparison(current=105_000_000,pct=5.0)
    if latest_kind=='uncomparable':
        newest.update(reason='no_comparable_prior',previous=None,change_pct=None)
    old=comparison(current=100_000_000,previous=25_000_000,end='2025-09-30',start='2025-07-01',
                   prior_end='2024-09-30',prior_start='2024-07-01',pct=300.0)
    assert render(newest,old) is None


@pytest.mark.parametrize('importance,expected',[('low',False),('medium',True),('high',True)])
def test_market_publication_importance_is_distinct_from_topical_relevance(importance,expected):
    from news_events.engine import Policy,route
    result=dict(related=True,relevance=.3,materiality=importance,sentiment='neutral')
    before=copy.deepcopy(result)
    routes,reason=route({'tickers':[],'event_type':'market'},result,set(),set(),{},Policy())
    assert bool(routes)is expected
    assert (reason is None)is expected
    assert result==before  # Do not inflate related/relevance/materiality to publish.


@pytest.mark.parametrize('changes',[
    {'related':False},{'relevance':.29},{'materiality':'low'},
])
def test_market_review_and_existing_relevance_floor_still_authoritative(changes):
    from news_events.engine import Policy,route
    result=dict(related=True,relevance=.3,materiality='high',sentiment='neutral',**{})
    result.update(changes)
    assert route({'tickers':[],'event_type':'market'},result,set(),set(),{},Policy())[0]==[]


def test_company_routes_retain_existing_importance_and_relevance_policy():
    from news_events.engine import Policy,route
    event={'tickers':['EXAMPLE'],'event_type':'earnings'}
    result=dict(related=True,relevance=.95,materiality='high',sentiment='positive')
    assert route(event,result,{'EXAMPLE'},set(),{'EXAMPLE':{}},Policy())[0]==[('portfolio_watchlist',['EXAMPLE'])]
    for delta in ({'materiality':'low'},{'related':False},{'relevance':.54}):
        assert route(event,{**result,**delta},{'EXAMPLE'},set(),{'EXAMPLE':{}},Policy())[0]==[]


def test_conflicting_latest_alias_value_is_not_hidden_by_missing_prior():
    valid=comparison()
    conflicting=comparison(current=250_000_000)
    conflicting.update(tag='RevenueFromContractWithCustomerExcludingAssessedTax',
                       reason='no_comparable_prior',previous=None,change_pct=None)
    assert render(valid,conflicting) is None


def macro(**changes):
    value=dict(event_type='market',tickers=(),cik='',rights='approved',
        title='New Zealand CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)',
        source_excerpt='',published_at='2026-10-21T12:00:00Z')
    value.update(changes)
    return value


def test_conflicting_same_source_macro_excerpt_cannot_overwrite_headline_claim():
    from news_events.editorial import macro_release
    source=macro(source_excerpt='New Zealand CPI (Q/Q) Q3: 0.9% (est 0.8%; prev 1.5%)')
    assert macro_release(source) is None


@pytest.mark.parametrize('changes',[
    {'title':'Australia CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)'},
    {'title':'New Zealand Core CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)'},
    {'title':'New Zealand CPI (Q/Q) Q2: 0.7% (est 0.8%; prev 1.5%)'},
    {'title':'New Zealand CPI (M/M) Sep: 0.7% (est 0.8%; prev 1.5%)'},
    {'title':'New Zealand CPI (Q/Q) Q3 2026: 0.7% (est 0.8%; prev 1.5%)'},
    {'published_at':'2026-10-22T12:00:00Z'},
])
def test_release_identity_does_not_guess_cross_country_series_period_year_day(changes):
    from news_events.editorial import macro_release
    first=macro_release(macro());other=macro_release(macro(**changes))
    assert first and other and first[0]!=other[0]


@pytest.mark.parametrize('changes',[
    {'tickers':('EXAMPLE',)},{'cik':'0000000001'},{'rights':'review_required'},
    {'title':'New Zealand CPI (Q/Q): 0.7% (est 0.8%; prev 1.5%)'},
    {'title':'New Zealand CPI (M/M) Q3: 0.7% (est 0.8%; prev 1.5%)'},
    {'title':'New Zealand CPI (Q/Q) Sep: 0.7% (est 0.8%; prev 1.5%)'},
    {'title':'New Zealand CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%) BUY NOW'},
])
def test_unknown_or_company_macro_bulletin_never_gets_release_anchor(changes):
    from news_events.editorial import macro_release
    assert macro_release(macro(**changes)) is None


def test_same_release_annual_component_is_addition_not_same_fact_duplicate():
    from news_events.editorial import macro_release
    first=macro_release(macro())
    annual=macro_release(macro(title='New Zealand CPI (Y/Y) Q3: 3.7% (est 3.8%; prev 4.1%)'))
    assert first[0]==annual[0]
    assert len(first[1])==len(annual[1])==3
    assert not set(first[1]) & set(annual[1])


def test_provider_claim_cannot_overwrite_deterministic_macro_packet_namespace():
    from news_events.editorial import macro_release
    from news_events.store import combine
    value=macro(source_excerpt='The publisher additionally cited a separate estimate of 0.9 in the discussion.')
    release=macro_release(value)
    key=next(key for key,claim in release[1].items() if claim['value']=='0.7')
    value.update(provider_id='synthetic',publisher='Synthetic publication',
                 url='https://synthetic.example/article/123456',source_type='aggregator',
                 claims={key:{'value':'0.9','quote':value['source_excerpt']}})
    evidence,conflicts=combine([value],allow_macro=True)
    assert conflicts or evidence[0]['claims'][key]['value']=='0.7'


def test_verified_company_event_cannot_receive_macro_materiality_shortcut(env):
    from datetime import datetime,timezone
    from news_events.model import Source
    from news_events.engine import Analysis
    p,s,_=env
    now=datetime(2026,10,21,12,tzinfo=timezone.utc)
    first=Source('first','one','https://synthetic.example/articles/123456','Synthetic',
        now.isoformat(),now.isoformat(),macro()['title'],
        'Apple Inc. described its products, expected performance, and operating activities in the published discussion.',
        event_type='market',rights='approved')
    eid=p.ingest(first,now)
    assert s.event(eid)['body']['tickers']==['AAPL']
    result=dict(related=True,title_he='החברה פרסמה עדכון',summary_he='החברה פרסמה מידע על פעילותה.',
        interpretation_he='אין בכך המלצת מסחר.',sentiment='neutral',materiality='high',relevance=.95)
    assert p.analyze(eid,lambda _e:Analysis(result),now)=='done'
    from dataclasses import replace
    second=replace(first,provider_id='second',source_id='two',
        title='New Zealand CPI (Y/Y) Q3: 3.7% (est 3.8%; prev 4.1%)')
    assert p.ingest(second,now)==eid
    event=s.event(eid)
    assert event['status']=='needs_material_review'
    assert not any(key.startswith('macro_release:') for row in event['body']['normalized_evidence'] for key in row['claims'])


@pytest.mark.parametrize('change',[
    lambda row:row.update(unit='EUR'),
    lambda row:row.update(value=True),
    lambda row:row.update(value=float('inf')),
    lambda row:row.update(value='120000000'),
    lambda row:row.update(change_pct=99.0),
    lambda row:row.update(end='2026-02-30'),
    lambda row:row.update(end='2027-09-30',start='2027-07-01'),
    lambda row:row['previous'].update(start='2025-01-01'),
    lambda row:row['previous'].update(value=-100_000_000),
])
def test_public_comparison_does_not_guess_invalid_basis_clock_value_or_duration(change):
    row=comparison();change(row)
    assert render(row) is None


def test_signed_margin_uses_points_not_percent_growth_or_currency():
    row=comparison(current=5,previous=-2,pct=None,unit='percent')
    row.update(metric='operating_margin',namespace='derived',tag='operating_income/revenue',change_pp=7)
    text=render(row)
    assert text and 'נקודות אחוז' in text and '7.0' in text
    assert '-2' in text and 'USD' not in text


def test_cash_or_debt_alone_cannot_be_percentage_only_public_headline():
    cash=comparison('cash',current=300_000_000,previous=100_000_000,start=None,prior_start=None,pct=200)
    debt=comparison('long_term_debt',current=900_000_000,previous=100_000_000,start=None,prior_start=None,pct=800)
    assert render(cash,debt) is None
