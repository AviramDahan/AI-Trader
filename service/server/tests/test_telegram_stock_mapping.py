import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from telegram_stock_mapping import match_stocks


def test_exact_identities_and_symbols():
    companies={'INTC':'Intel Corporation','NVDA':'NVIDIA','AAPL':'Apple Inc.','IT':'Gartner Inc.'}
    assert set(match_stocks('Intel and NVIDIA announce a deal with $AAPL.',companies))=={'INTC','NVDA','AAPL'}
    assert set(match_stocks('NYSE:IT raises guidance',companies))=={'IT'}


def test_no_people_sector_common_words_substrings_or_links():
    companies={'MSFT':'Microsoft','AAPL':'Apple','META':'Meta','MSTR':'Strategy','IT':'Gartner','INTC':'Intel Corporation'}
    for text in ['Bill Gates discusses AI','Apple harvest improves','Meta analysis of strategy in IT',
                 'Intellectual property dispute','https://example.com/$INTC @Microsoft']:
        assert match_stocks(text,companies)=={}


def test_unknown_symbol_is_not_accepted():
    assert match_stocks('$FAKE and $BTC rally',{'INTC':'Intel Corporation'})=={}
