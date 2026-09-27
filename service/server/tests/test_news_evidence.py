"""Isolated evidence tests. No production DB, providers, models or Telegram."""
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

import database
import news_evidence as evidence
import news_pipeline
import news_quality
import scanner_engine
import test_news_pipeline as pipeline_tests

URL = 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/form4.xml'
XML = '''<ownershipDocument><documentType>4</documentType><issuer><issuerCik>0000320193</issuerCik>
<issuerName>Apple Inc.</issuerName><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>Test Reporting Owner</rptOwnerName></reportingOwnerId></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
<transactionDate><value>2026-09-14</value></transactionDate><transactionCoding><transactionCode>S</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>100</value></transactionShares><transactionPricePerShare><value>200</value></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
</nonDerivativeTransaction></nonDerivativeTable><footnotes><footnote id="F1">Planned transaction; no price forecast.</footnote></footnotes></ownershipDocument>'''


class NewsEvidenceTests(unittest.TestCase):
    # Reuse only fixture helpers, not the entire original test suite.
    tearDown = pipeline_tests.NewsPipelineIntegrationTests.tearDown
    rows = pipeline_tests.NewsPipelineIntegrationTests.rows
    item = pipeline_tests.NewsPipelineIntegrationTests.item
    open_trade = pipeline_tests.NewsPipelineIntegrationTests.open_trade
    strong_analyzer = pipeline_tests.NewsPipelineIntegrationTests.strong_analyzer

    def setUp(self):
        pipeline_tests.NewsPipelineIntegrationTests.setUp(self)
        self.env = patch.dict(os.environ, {'NEWS_EVIDENCE_ENABLED': 'true',
            'NEWS_EVIDENCE_NOT_BEFORE': (self.clock-timedelta(hours=1)).isoformat()})
        self.env.start(); self.addCleanup(self.env.stop)

    def article(self):
        self.open_trade()
        item = self.item('sec_edgar', URL, 'AAPL')
        item.update(title='Apple Inc. — SEC 4', source_excerpt='FORM 4', accession_number='0000320193-26-000123')
        news_pipeline.ingest_items([item], self.clock)
        return self.rows('SELECT * FROM scanner_news')[0]

    def test_disabled_has_no_enrichment_cache_or_behavior_change(self):
        row = self.article(); analyzer = Mock(return_value={'id': row['id']})
        with patch.dict(os.environ, {'NEWS_EVIDENCE_ENABLED': 'false'}), patch.object(evidence, 'prepare') as prepare:
            self.assertEqual(evidence.review(row, analyzer), {'id': row['id']})
        prepare.assert_not_called(); analyzer.assert_called_once_with(row)
        self.assertFalse(self.rows('SELECT * FROM news_review_cache'))

    def test_exact_issuer_and_event_validation(self):
        value = evidence.extract(XML, URL, ['AAPL'])
        self.assertEqual(value['ticker'], 'AAPL')
        for raw, url, tickers in [(XML, URL, ['INTC']), (XML, URL.replace('/320193/', '/42/'), ['AAPL']),
                                  ('<!DOCTYPE test [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + XML, URL, ['AAPL'])]:
            with self.subTest(url=url, tickers=tickers), self.assertRaises(evidence.EvidenceError):
                evidence.extract(raw, url, tickers)

    def test_no_arbitrary_urls_or_internal_dns(self):
        for url in ['http://www.sec.gov/filing', 'https://127.0.0.1/a', URL.replace('www.sec.gov', 'www.sec.gov.evil.test'),
                    URL.replace('www.sec.gov', 'user@www.sec.gov'), URL+'?x=1', URL.replace('form4', '../form4'),
                    URL.replace('form4', '%2e%2e/form4')]:
            with self.subTest(url=url), self.assertRaises(evidence.EvidenceError):
                evidence.filing_url(url)
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','224.0.0.1']:
            with patch('socket.getaddrinfo', return_value=[(2,1,6,'',(ip,443))]), self.assertRaises(evidence.EvidenceError):
                evidence.public_addresses('www.sec.gov')

    def test_redirect_private_or_different_event_is_never_requested(self):
        for target in ('https://127.0.0.1/admin', URL.replace('000032019326000123','000032019326000999')):
            connection = Mock()
            response = Mock(status=302)
            response.getheader.side_effect = lambda key, default=None: target if key=='Location' else default
            connection.getresponse.return_value = response
            with patch.object(evidence, 'PinnedHTTPS', return_value=connection), \
                 patch.object(evidence, 'public_addresses', return_value=['8.8.8.8']), \
                 patch.object(evidence.time, 'sleep'), self.assertRaises(evidence.EvidenceError):
                evidence.fetch_filing(URL, 'test@example.com')
            self.assertEqual(connection.request.call_count, 1)

    def test_response_body_limit_before_read(self):
        connection = Mock(); response = Mock(status=200)
        headers = {'Content-Length':str(evidence.MAX_BYTES+1), 'Content-Type':'text/xml','Content-Encoding':'identity'}
        response.getheader.side_effect = lambda key, default=None: headers.get(key, default)
        connection.getresponse.return_value = response
        with patch.object(evidence, 'PinnedHTTPS', return_value=connection), \
             patch.object(evidence, 'public_addresses', return_value=['8.8.8.8']), \
             patch.object(evidence.time, 'sleep'), self.assertRaisesRegex(evidence.EvidenceError, 'body_too_large'):
            evidence.fetch_filing(URL, 'test@example.com')
        response.read1.assert_not_called()

    def test_inline_xbrl_multiple_share_classes_and_wrong_issuer(self):
        raw = '''<html><ix:nonNumeric name="dei:EntityCentralIndexKey">0000320193</ix:nonNumeric>
        <ix:nonNumeric name="dei:TradingSymbol">OTHER</ix:nonNumeric>
        <ix:nonNumeric name="dei:TradingSymbol">AAPL</ix:nonNumeric>
        <div>Item 2.02 Results of Operations and Financial Condition</div>
        <p>The company announced its financial results for the quarter in the attached release.
        The complete release contains additional details and qualifications; this excerpt alone
        does not establish future performance or investment merit.</p></html>'''
        result = evidence.extract(raw, URL.replace('form4.xml','report.htm'), ['AAPL'])
        self.assertEqual(result['ticker'],'AAPL')
        self.assertIn('additional details and qualifications',result['selected_excerpt'])
        with self.assertRaisesRegex(evidence.EvidenceError, 'tabular_layout_unsupported'):
            evidence.extract(raw.replace('</html>','<table><tr><td>Ambiguous headings</td></tr></table></html>'), URL.replace('form4.xml','report.htm'), ['AAPL'])
        with self.assertRaises(evidence.EvidenceError):
            evidence.extract(raw.replace('0000320193','999'), URL.replace('form4.xml','report.htm'), ['AAPL'])

    def test_stylesheet_path_is_same_exact_raw_filing(self):
        rendered = URL.replace('/form4', '/xslF345X06/form4')
        self.assertEqual(evidence.raw_filing_url(rendered), URL)

    def test_shared_cache_and_original_fields_unchanged(self):
        row = self.article(); fetch = Mock(return_value=(XML, URL))
        before = self.rows('SELECT * FROM scanner_news')
        first = evidence.prepare(row, self.clock, fetch)
        second = evidence.prepare(row, self.clock+timedelta(hours=6), fetch)
        self.assertEqual(first['source_facts_json'], second['source_facts_json'])
        fetch.assert_called_once()
        self.assertEqual(self.rows('SELECT * FROM scanner_news'), before)
        stored = self.rows('SELECT * FROM news_evidence')[0]
        self.assertEqual(stored['raw_source_text'], XML)
        self.assertEqual(stored['source_published_at'], row['published_at'])
        self.assertEqual(first['published_at'], row['published_at'])

    def test_subscription_removed_or_nonpersonal_never_fetches(self):
        row = self.article()
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_trades SET status='closed'")
        fetch = Mock(side_effect=AssertionError('must not fetch'))
        self.assertEqual(evidence.prepare(row, self.clock, fetch), row)
        fetch.assert_not_called()

    def test_backlog_fence_and_no_fuzzy_source_enrichment(self):
        row = self.article(); fetch = Mock()
        with patch.dict(os.environ, {'NEWS_EVIDENCE_NOT_BEFORE': (self.clock+timedelta(seconds=1)).isoformat()}):
            result = evidence.prepare(row, self.clock, fetch)
        self.assertEqual(result['_evidence_reason'], 'outside_activation_window')
        for change in ({'provider':'yahoo_priority'}, {'canonical_key':'sec:0000320193-26-000999'}):
            evidence.prepare({**row, **change}, self.clock, fetch)
        fetch.assert_not_called()

    def test_retry_after_and_terminal_attempts_without_ai(self):
        row = self.article()
        fetch = Mock(side_effect=evidence.EvidenceError('http_error', 429, 900, True))
        first = evidence.prepare(row, self.clock, fetch)
        self.assertEqual(first['_evidence_retry_after'], 900)
        evidence.prepare(row, self.clock+timedelta(seconds=100), fetch)
        self.assertEqual(fetch.call_count, 1)
        evidence.prepare(row, self.clock+timedelta(seconds=901), fetch)
        third = evidence.prepare(row, self.clock+timedelta(seconds=1802), fetch)
        self.assertTrue(third['_evidence_terminal'])
        evidence.prepare(row, self.clock+timedelta(days=2), fetch)
        self.assertEqual(fetch.call_count, 3)

    def test_permanent_http_failure_not_retried(self):
        row = self.article(); fetch = Mock(side_effect=evidence.EvidenceError('http_error', 403))
        evidence.prepare(row, self.clock, fetch)
        evidence.prepare(row, self.clock+timedelta(hours=2), fetch)
        fetch.assert_called_once()
        self.assertEqual(self.rows('SELECT http_status,status FROM news_evidence_attempts')[0], {'http_status':403,'status':'terminal'})

    def test_excerpt_reaches_model_exactly_no_silent_truncation(self):
        row = self.article()
        prepared = evidence.prepare(row, self.clock, Mock(return_value=(XML, URL)))
        draft = self.strong_analyzer([row])[0]
        good = dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,duplicate_of=0,material_new_fact=False,explanation='ok')
        with patch('scanner_engine._ollama_json', side_effect=[draft, good]) as model, patch('news_quality.recent_events', return_value=[]):
            news_quality.analyze_one(prepared)
        excerpt = json.loads(prepared['source_facts_json'])['source_excerpt']
        self.assertLessEqual(len(excerpt),2000)
        self.assertEqual(model.call_args_list[0].args[1]['source']['source_excerpt'], excerpt)
        self.assertIn('Planned transaction', excerpt)
        with self.assertRaises(evidence.EvidenceError):
            evidence.extract(XML.replace('Planned transaction', 'qualifying fact ' * 300), URL, ['AAPL'])

    def test_quality_rejection_cached_and_cosmetic_changes_do_not_reanalyze(self):
        row = self.article()
        row['provider'] = 'yahoo_priority'
        analyzer = Mock(side_effect=ValueError('news_quality_rejected:unsupported'))
        for candidate in (row, {**row, 'title': '  Apple Inc.  — SEC 4 ', 'published_at':self.clock.isoformat()},
                          {**row, 'id':999, 'scope':'watchlist', 'thesis':'changed context, same rejected facts'}):
            with self.assertRaisesRegex(ValueError, 'news_quality_rejected'):
                evidence.review(candidate, analyzer)
        analyzer.assert_called_once()
        changed = {**row, 'source_facts_json': json.dumps({'source_excerpt':'Company announced a new material decision.'})}
        with self.assertRaises(ValueError):
            evidence.review(changed, analyzer)
        self.assertEqual(analyzer.call_count, 2)

    def test_missing_information_is_not_low_importance(self):
        row = self.article()
        weak = dict(self.strong_analyzer([row])[0], materiality='low')
        with database.get_db_connection() as c:
            evidence.audit(c.cursor(), row, weak)
        self.assertEqual(json.loads(self.rows('SELECT reasons_json FROM news_publication_audit')[0]['reasons_json']), ['insufficient_information'])
        with database.get_db_connection() as c:
            evidence.audit(c.cursor(), row, {**weak, '_missing_information':False})
        self.assertEqual(json.loads(self.rows('SELECT reasons_json FROM news_publication_audit')[0]['reasons_json']), ['low_importance'])

    def test_versioned_delivery_can_publish_material_correction_not_same_version(self):
        row = self.article()
        def analyzer(rows):
            return [{**r, '_news_version': 'v1'} for r in self.strong_analyzer(rows)]
        initial = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)
        self.assertEqual(initial['alerts'], 1)
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_news_jobs SET status='pending'")
        self.assertEqual(news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)['alerts'], 0)
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_news_jobs SET status='pending'")
        changed = lambda rows: [{**r, '_news_version':'v2'} for r in self.strong_analyzer(rows)]
        self.assertEqual(news_pipeline.analyze_news_jobs(analyzer=changed, at=self.clock)['alerts'], 1)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='position_news'")), 2)

    def test_transient_enrichment_defers_without_quality_ai(self):
        row = self.article(); analyzer = Mock(side_effect=AssertionError('AI not allowed'))
        with patch.object(evidence, 'prepare', return_value={**row, '_evidence_terminal':False,'_evidence_retry_after':60,'_evidence_reason':'http_error'}):
            result = evidence.review(row, analyzer)
        self.assertEqual(result['_error'], 'news_evidence_pending:http_error')
        analyzer.assert_not_called()

    def test_context_is_reset_and_stage_does_not_duplicate_cost(self):
        from news_call_context import article, call, CURRENT
        with article(7, 'v1', 'facts'):
            with self.assertRaises(RuntimeError):
                call('quality_review', lambda: (_ for _ in ()).throw(RuntimeError()))
            self.assertEqual(CURRENT.get()['stage'], 'source_analysis')
        self.assertIsNone(CURRENT.get())

    def test_evidence_error_is_separate_terminal_status_without_alerts(self):
        row = self.article()
        result = news_pipeline.analyze_news_jobs(analyzer=lambda rows: [dict(id=row['id'], _error='news_evidence_unavailable')], at=self.clock)
        self.assertEqual(result['alerts'], 0)
        self.assertEqual(self.rows('SELECT status FROM scanner_news_jobs')[0]['status'], 'insufficient_information')
        self.assertEqual(self.rows('SELECT analysis_status FROM scanner_news')[0]['analysis_status'], 'insufficient_information')

    def test_wrong_topic_duplicate_does_not_hide_personal_notice(self):
        row = self.article()
        other = self.item('yahoo_priority', 'https://example.test/duplicate', 'AAPL')
        other['title'] = 'Apple announces same event in another source'
        news_pipeline.ingest_items([other], self.clock)
        second = self.rows('SELECT * FROM scanner_news ORDER BY id DESC')[0]
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_news_jobs SET status='done' WHERE news_id=?", (row['id'],))
            c.execute("INSERT INTO scanner_news_broadcast_alerts(news_id,channel,ticker,event_version,created_at) VALUES(?,'stock','AAPL','v1',?)", (row['id'], self.clock.isoformat()))
        analyzer = lambda rows: [{**r, 'duplicate_of':row['id'], '_news_version':'v1'} for r in self.strong_analyzer(rows)]
        result = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)
        self.assertEqual(result['alerts'], 1)
        self.assertEqual(len(self.rows("SELECT id FROM scanner_telegram_outbox WHERE event_type='position_news'")), 1)
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_news_jobs SET status='pending' WHERE news_id=?", (second['id'],))
        self.assertEqual(news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)['alerts'], 0)

    def test_personal_subscription_is_rechecked_at_delivery(self):
        self.article()
        news_pipeline.analyze_news_jobs(analyzer=self.strong_analyzer, at=self.clock)
        event = self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='position_news'")[0]
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_trades SET status='closed'")
        from news_subscriptions import personal_delivery_message
        self.assertIsNone(personal_delivery_message(event))

    def test_provider_backoff_shared_across_filings(self):
        row = self.article()
        fetch = Mock(side_effect=evidence.EvidenceError('http_error', 429, 900, True))
        evidence.prepare(row, self.clock, fetch)
        another = {**row, 'url':URL.replace('000032019326000123','000032019326000124'), 'canonical_key':'sec:0000320193-26-000124'}
        result = evidence.prepare(another, self.clock+timedelta(seconds=1), fetch)
        self.assertEqual(result['_evidence_reason'], 'provider_backoff')
        fetch.assert_called_once()

    def test_no_db_lock_held_during_source_fetch_or_model(self):
        row = self.article()
        def independent_write():
            # A second connection must be able to commit while the provider is
            # running. This exercises SQLite's strict write-lock behavior too.
            with database.get_db_connection() as c:
                c.execute("UPDATE scanner_accounts SET cash=cash WHERE 1=1")
        def fetch(*args):
            independent_write()
            return XML, URL
        prepared = evidence.prepare(row, self.clock, fetch)
        def analyzer(item):
            independent_write()
            return self.strong_analyzer([item])[0]
        with patch.object(evidence, 'prepare', return_value=prepared):
            evidence.review(row, analyzer)
