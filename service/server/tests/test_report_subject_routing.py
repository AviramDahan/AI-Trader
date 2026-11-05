"""The article's actual subject determines its topic, not an earnings mention."""
import pytest


@pytest.mark.parametrize('title',[
    'Example Shares Surge 9.6% as Record Q3 Earnings Lift 2027 Outlook',
    'Example Shares Rise Over 8% as Fiscal Q1 Earnings Exceed Forecasts',
    'Example Shares Little Changed as Revenue Miss and Weaker Q4 Outlook Offset Earnings Beat',
    'Example Stock Down in Pre-Market Despite Q4 Earnings & Revenue Beat',
    'Example Soars 10% on Q3 Beat, Delivering 57.4% EBITDA Margins',
    'Example Q4 Earnings: How Key Metrics Compare to Estimates',
    'Example Reports Q2 Earnings: What Key Metrics Have to Say',
])
def test_price_reaction_or_editorial_stays_outside_results(title):
    from news_report_routing import is_company_report,delivery_type
    assert not is_company_report(title)
    assert delivery_type('stock_news',title)=='stock_news'


@pytest.mark.parametrize('title',[
    'Example Q3 Revenue Surges 10%, EPS Rises to $2.10',
    'Example Q3 Earnings Beat Estimates; Shares Rise Pre-Bell',
    'Example Reports Q3 Financial Results, Shares Gain 5%',
])
def test_results_remain_results_with_secondary_share_reaction(title):
    from news_report_routing import is_company_report
    assert is_company_report(title)
