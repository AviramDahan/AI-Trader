"""Actual wire-result syntax vs opinion, forecasts and presentation notices."""
import pytest


@pytest.mark.parametrize('title',[
    'Example Q3 Adjusted Earnings, Revenue Rise; 2026 Adjusted EPS Outlook Affirmed',
    'Example Q3 Earnings & Revenues Surpass Estimates, Both Rise Y/Y',
    'Example misses Q3 sales expectations but beats adjusted EPS consensus estimates',
    'Example Q3 Earnings Beat on Stronger Margins, Revenues Fall Y/Y',
    'Example Reports Third Quarter 2026 Results',
    'Example Announces Third Quarter 2026 Results, Declares Quarterly Dividend',
    'Example Fiscal Q4 Adjusted Earnings Increase, Revenue Declines',
    'Example Q3 Earnings Exceed Forecasts and 2027 Outlook Improves',
])
def test_actual_published_wire_results_are_reports_and_pass_public_gate(title):
    from news_report_routing import is_company_report
    from news_public_importance import source_importance
    assert is_company_report(title)
    assert source_importance(title)==(True,None)


@pytest.mark.parametrize('title',[
    'Example Stock Falls 5% After Q1 Results: Should You Hold or Fold?',
    'Example Q3 Revenue Forecast Raised Ahead of Results',
    'Could Example Q3 Earnings Beat Estimates?',
    'Example Q3 Earnings Could Beat Estimates',
    'Example will report Q3 revenue tomorrow',
    'Example Q3 Earnings Call Highlights: Revenue Surge and Raised Outlook',
    'Example Financial Results Conference',
])
def test_actual_results_grammar_does_not_lend_identity_to_previews_or_commentary(title):
    from news_report_routing import is_company_report
    assert not is_company_report(title)
