import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from test_sec_intelligence import isolated, ownership_xml
import scanner_engine
import sec_activity_topics as activity
import sec_intelligence as si
import stock_scanner


CIK = '0000320193'
ACCESSION = '0000320193-26-000001'


def schedule_xml(form):
    family = form.split()[-1].split('/')[0].lower()
    if family == '13d':
        event = '<dateOfEvent>09/30/2026</dateOfEvent>'
        cik = f'<issuerCIK>{CIK}</issuerCIK>'
        persons = ('<reportingPersons><reportingPersonInfo><reportingPersonName>Example Fund</reportingPersonName>'
                   '<percentOfClass>6.25</percentOfClass></reportingPersonInfo></reportingPersons>')
    else:
        event = '<eventDateRequiresFilingThisStatement>09/30/2026</eventDateRequiresFilingThisStatement>'
        cik = f'<issuerCik>{CIK}</issuerCik>'
        persons = ('<coverPageHeaderReportingPersonDetails><reportingPersonName>Example Fund</reportingPersonName>'
                   '<classPercent>6.25</classPercent></coverPageHeaderReportingPersonDetails>')
    namespace_suffix = '13D' if family == '13d' else '13g'
    return (f'<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule{namespace_suffix}">'
            f'<headerData><submissionType>{form}</submissionType></headerData>'
            f'<formData><coverPageHeader>{event}<issuerInfo>{cik}</issuerInfo>'
            f'<securitiesClassTitle>Class A Common Stock</securitiesClassTitle></coverPageHeader>'
            f'{persons}</formData></edgarSubmission>').encode()


@pytest.mark.parametrize('form', sorted(activity.BENEFICIAL_FORMS))
def test_beneficial_forms_identify_subject_and_never_infer_trade(form):
    data = schedule_xml(form)
    parsed = activity.parse_beneficial_ownership(data, form, CIK)
    assert parsed['reported_date'] == '2026-09-30'
    assert parsed['persons'] == [{'name': 'Example Fund', 'percent': '6.25'}]
    with pytest.raises(ValueError, match='issuer_cik_mismatch'):
        activity.parse_beneficial_ownership(data, form, '0000000001')


def test_schedule_13g_percentage_accepts_reported_value_with_explanation():
    form = 'SCHEDULE 13G'
    raw = schedule_xml(form)
    explained = raw.replace(b'6.25</classPercent>', b'6.3% (approximately 6.28%) - Based on the cover page.</classPercent>')
    assert activity.parse_beneficial_ownership(explained, form, CIK)['persons'][0]['percent'] == '6.3'
    ambiguous = raw.replace(b'6.25</classPercent>', b'6.3% of class A and 8.9% of class B</classPercent>')
    with pytest.raises(ValueError, match='ownership_percent_not_available'):
        activity.parse_beneficial_ownership(ambiguous, form, CIK)


def _parsed_purchase(relation, post_shares='100', *, owners=('0000000042',), price='12.50'):
    raw = ownership_xml(owners=owners, price=price)
    raw = raw.replace(b'</reportingOwnerId>', (
        '</reportingOwnerId><reportingOwnerRelationship>' + relation +
        '</reportingOwnerRelationship>').encode(), 1)
    raw = raw.replace(b'</nonDerivativeTransaction>', (
        '<postTransactionAmounts><sharesOwnedFollowingTransaction><value>' + post_shares +
        '</value></sharesOwnedFollowingTransaction></postTransactionAmounts>'
        '<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>'
        '</ownershipNature></nonDerivativeTransaction>').encode())
    return si.parse_form4(raw, ACCESSION, CIK)['transactions'][0]


def test_insider_notice_shows_officer_title_and_buy_size():
    tx = _parsed_purchase('<isOfficer>true</isOfficer><officerTitle>Chief Financial Officer</officerTitle>'
                          '<isDirector>1</isDirector>')
    notice = activity._insider_text([tx], date(2026, 10, 9))
    assert 'Owner · סמנכ״ל כספים (CFO), חבר דירקטוריון' in notice
    assert 'שווי לפי המחיר המדווח 125' in notice
    assert 'גודל רכישה 3/5 · בינונית' in notice
    assert '10% מההחזקה הישירה המדווחת לאחר העסקה' in notice


@pytest.mark.parametrize('post_shares,score', [('1001', 1), ('1000', 2), ('200', 3),
                                             ('100', 3), ('66', 4), ('30', 5), ('10', 5)])
def test_buy_size_boundaries(post_shares, score):
    tx = _parsed_purchase('<isTenPercentOwner>true</isTenPercentOwner>', post_shares)
    notice = activity._insider_text([tx], date(2026, 10, 9))
    assert 'בעל החזקה מעל 10%' in notice
    assert f'גודל רכישה {score}/5' in notice


@pytest.mark.parametrize('change', ['joint', 'indirect', 'missing_post', 'inconsistent_post'])
def test_purchase_without_verifiable_individual_direct_holdings_is_not_scored(change):
    owners = ('0000000042', '0000000043') if change == 'joint' else ('0000000042',)
    post = {'missing_post': '', 'inconsistent_post': '9'}.get(change, '100')
    tx = _parsed_purchase('<isOther>1</isOther><otherText>Trustee</otherText>', post, owners=owners)
    if change == 'indirect':
        tx['ownership'] = 'I'
    notice = activity._insider_text([tx], date(2026, 10, 9))
    assert 'Trustee' in notice
    assert 'גודל רכישה לא זמין' in notice
    if change == 'joint':
        assert 'מדווחים במשותף' in notice


def test_bounded_notice_keeps_complete_transactions_and_counts_omissions():
    from telegram_presentation import telegram_text, utf16_length
    relation = '<isOfficer>1</isOfficer><officerTitle>' + 'א' * 60 + '</officerTitle>'
    tx = _parsed_purchase(relation, owners=('0000000042', '0000000043', '0000000044'))
    tx['owners'] = [{**owner, 'name': '🔹' * 90, 'officer': True, 'officer_title': 'א' * 60}
                    for owner in tx['owners']]
    notice = activity._insider_text([{**tx, 'shares': i} for i in range(1, 7)], date(2026, 10, 9))
    visible = notice.count('גודל רכישה לא זמין')
    assert 0 < visible < 5
    assert f'ועוד {6 - visible} עסקאות מדווחות' in notice
    assert utf16_length(telegram_text(notice, limit=100_000)) < 3600


def buyback_payload(rows):
    return {'cik': 320193, 'facts': {'us-gaap': {
        'PaymentsForRepurchaseOfCommonStock': {'units': {'USD': rows}}}}}


def buyback_row(**overrides):
    return {'accn': ACCESSION, 'form': '10-Q', 'start': '2026-01-01',
            'end': '2026-09-30', 'val': 2_000_000, **overrides}


def test_buyback_uses_current_exact_filing_and_ytd_period():
    job = {'accession': ACCESSION, 'form': '10-Q', 'accepted_at': '2026-10-30T14:00:00Z'}
    rows = [buyback_row(start='2026-07-01', val=500_000),
            buyback_row(accn='0000320193-26-000002', val=9_000_000), buyback_row()]
    assert activity.reported_buyback(buyback_payload(rows), job) == {
        'start': '2026-01-01', 'end': '2026-09-30', 'usd_paid': '2000000'}
    assert activity.reported_buyback(buyback_payload(rows + [buyback_row(val=0)]), job) is None
    assert activity.reported_buyback(buyback_payload([buyback_row(val=0)]), job) is None
    assert activity.reported_buyback({'facts': None}, job) is None


def enable(monkeypatch, now):
    for key, value in {
        'SEC_INTELLIGENCE_MODE': 'paper', 'SEC_INTELLIGENCE_KILL_SWITCH': 'false',
        'STOCK_SCANNER_TELEGRAM_ENABLED': 'true',
        'TELEGRAM_OWNERSHIP_ACTIVITY_THREAD_ID': '41', 'TELEGRAM_BUYBACK_ACTIVITY_THREAD_ID': '42',
        'SEC_ACTIVITY_TOPICS_NOT_BEFORE': si._z(now - timedelta(minutes=10)),
        'NEWS_SEC_USER_AGENT': 'Synthetic testing agent contact@example.invalid',
        'TELEGRAM_BOT_TOKEN': 'synthetic-token', 'TELEGRAM_CHAT_ID': '-100123',
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})


def _purchase_xml(traded):
    raw = ownership_xml(date=traded, period=traded)
    return raw.replace(b'</reportingOwnerId>',
        b'</reportingOwnerId><reportingOwnerRelationship><isOfficer>true</isOfficer>'
        b'<officerTitle>CEO</officerTitle></reportingOwnerRelationship>').replace(
        b'</nonDerivativeTransaction>',
        b'<postTransactionAmounts><sharesOwnedFollowingTransaction><value>100</value>'
        b'</sharesOwnedFollowingTransaction></postTransactionAmounts>'
        b'<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>'
        b'</ownershipNature></nonDerivativeTransaction>')


def seed_filing(monkeypatch, form):
    now = datetime.now(timezone.utc)
    enable(monkeypatch, now)
    snapshot, _ = si.save_universe({'SYN': {'company': 'Synthetic Inc.', 'indexes': ['sp500']}},
                                   {CIK: ['SYN']}, now)
    accepted = si._z(now - timedelta(minutes=1))
    document = 'xslSCHEDULE_13G_X01/primary_doc.xml' if form == 'SCHEDULE 13G' else 'primary.xml'
    row = {'accessionNumber': ACCESSION, 'form': form, 'acceptanceDateTime': accepted,
           'primaryDocument': document}
    assert si._queue_filing(row, CIK, ['SYN'], snapshot, now, [10])
    observed = []
    def fetch(url, *args, **kwargs):
        observed.append(url)
        if form == 'SCHEDULE 13G':
            return schedule_xml(form), {}
        if form == '4':
            traded = (now - timedelta(days=1)).date().isoformat()
            return _purchase_xml(traded), {}
        if 'companyfacts' in url:
            end = (now - timedelta(days=20)).date()
            rows = [buyback_row(start=(end - timedelta(days=90)).isoformat(), end=end.isoformat())]
            return json.dumps(buyback_payload(rows)).encode(), {}
        return b'<html></html>', {}
    monkeypatch.setattr(si, 'fetch', fetch)
    assert si.process_jobs(now)['processed'] == 1
    return observed


@pytest.mark.parametrize(('form','thread'), [('SCHEDULE 13G',41), ('4',41), ('10-Q',42)])
def test_filing_to_topic_ack_and_no_repeat(isolated, monkeypatch, form, thread):
    calls = seed_filing(monkeypatch, form)
    if form == 'SCHEDULE 13G':
        assert calls[0].endswith('/primary_doc.xml') and '/xsl' not in calls[0]
        with isolated() as conn:
            assert conn.execute('SELECT COUNT(*) n FROM si_company_snapshots').fetchone()['n'] == 0
    response = Mock()
    response.json.return_value = {'ok': True, 'result': {
        'message_id': 100, 'chat': {'id': -100123}, 'message_thread_id': thread}}
    session = Mock()
    session.post.return_value = response
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    wire = session.post.call_args.kwargs['data']
    assert wire['message_thread_id'] == thread
    if form == '4':
        text = wire['text'].translate(dict.fromkeys(map(ord, '\u200f\u2066\u2069')))
        assert 'Owner · מנכ״ל (CEO)' in text
        assert 'גודל רכישה 3/5' in text
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    session.post.assert_called_once()


@pytest.mark.parametrize('fault', ['missing_topic', 'shared_topic', 'wrong_ack', 'expired_lease'])
def test_queued_activity_cannot_spill_or_retry_unknown(isolated, monkeypatch, fault):
    seed_filing(monkeypatch, 'SCHEDULE 13G')
    session = Mock()
    response = Mock()
    response.json.return_value = {'ok': True, 'result': {
        'message_id': 100, 'chat': {'id': -100123}, 'message_thread_id': 42}}
    session.post.return_value = response
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    if fault == 'missing_topic':
        monkeypatch.setenv('TELEGRAM_OWNERSHIP_ACTIVITY_THREAD_ID', '1')
    elif fault == 'shared_topic':
        monkeypatch.setenv('TELEGRAM_BUYBACK_ACTIVITY_THREAD_ID', '41')
    elif fault == 'expired_lease':
        with isolated() as conn:
            conn.execute("""UPDATE scanner_telegram_outbox SET status='sec_topic_sending',next_attempt_at=?
                            WHERE event_type='ownership_activity'""", ('2000-01-01T00:00:00Z',))
            conn.commit()
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert session.post.call_count == int(fault == 'wrong_ack')
    with isolated() as conn:
        assert conn.execute("""SELECT status FROM scanner_telegram_outbox
                            WHERE event_type='ownership_activity'""").fetchone()['status'] == 'failed'


def test_buyback_repeated_period_and_payment_is_not_enqueued_twice(isolated, monkeypatch):
    seed_filing(monkeypatch, '10-Q')
    with isolated() as conn:
        job = dict(conn.execute('SELECT * FROM si_filing_jobs WHERE accession=?', (ACCESSION,)).fetchone())
        evidence = json.loads(job['evidence_json'])
        job['accession'] = '0000320193-26-000002'
        assert not activity.enqueue(job, evidence, [], datetime.now(timezone.utc), conn)
        assert conn.execute("SELECT COUNT(*) n FROM scanner_telegram_outbox WHERE event_type='buyback_activity'").fetchone()['n'] == 1
