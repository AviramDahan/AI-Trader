"""Independent actual-value context regressions; synthetic text, no I/O or AI."""
import pytest


@pytest.fixture(autouse=True)
def results_only(monkeypatch):
    monkeypatch.setenv('TELEGRAM_COMPANY_REPORTS_RESULTS_ONLY_ENABLED', 'true')


@pytest.mark.parametrize('body', [
    'Prior-year revenue $100 million.',
    'Prior year revenue $100 million.',
    'Revenue $100 million forecast.',
    'Revenue of $100 million was expected.',
    'Revenue $100 million in the prior year.',
    'Revenue $100 million last quarter.',
    'Revenue $100 million a year ago.',
    'Revenue increased 18% last quarter.',
    'Revenue increased 18% in the prior year.',
    'Analysts expect revenue of $100 million.',
    'Analysts expect EPS $2.10.',
    'הכנסות בשנה שעברה: 100 מיליון דולר.',
    'רווח למניה צפוי של 2.10 דולר.',
])
def test_expected_or_prior_only_amount_is_not_a_current_result(body):
    from news_report_routing import is_company_report
    assert not is_company_report('Example Q3 financial results', body)


@pytest.mark.parametrize('body', [
    'Revenue was $100 million; expected revenue was $110 million.',
    'EPS $2.10 versus expected EPS $2.00.',
    'Revenue $100 million, prior-year $90 million.',
    'Revenue $100 million versus $90 million in the prior year.',
    'Revenue $100 million versus $90 million last quarter.',
    'EPS $1.20 versus prior EPS $0.80.',
    'EPS $2.10 beats analyst expectations.',
    'הרווח למניה היה 3.55 אירו, לעומת צפי של 2.80 אירו.',
    'Revenue increased 18% from the prior year.',
])
def test_current_amount_survives_separate_prior_or_consensus_comparison(body):
    from news_report_routing import is_company_report
    assert is_company_report('Example Q3 financial results', body)


@pytest.mark.parametrize('source,shown,expected', [
    ('Revenue $100 million forecast.', 'Revenue was $100 million.', False),
    ('Revenue was $100 million.', 'Revenue $100 million forecast.', False),
    ('Prior-year revenue $100 million.', 'Revenue was $100 million.', False),
    ('Revenue was $100 million.', 'Prior-year revenue $100 million.', False),
    ('Revenue was $100 million.', 'Revenue was $100 million.', True),
])
def test_source_and_visible_current_result_are_independent_requirements(source, shown, expected):
    from news_report_routing import report_for_presentation
    event = {'title': 'Example Q3 financial results', 'source_excerpt': source, 'sources': []}
    result = {'title_he': 'Example Q3 financial results', 'summary_he': shown}
    assert report_for_presentation(event, result) is expected
