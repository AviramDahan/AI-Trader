SEC established-response deadline
=================================

Scope
-----

``sec_transport.fetch`` keeps its existing Requests transport, URL allowlist,
verified HTTPS, operator contact, disabled environment proxies, no-redirect
policy, byte limits, conditional-cache metadata and shared fair-access clock.
The reservation still commits before network I/O. No database transaction is
held while waiting for a response.

The existing ``timeout=(4, 12)`` is not a cumulative download limit: a peer can
keep an HTTP header or body read alive by sending small amounts frequently.
The additional fixed 12-second budget bounds HTTP response headers and body
after normal verified TLS connection establishment. Expiry shuts down the
socket owned by that fetch, so a blocked read is interrupted, not merely
rejected after the whole document eventually arrives.

This is **not** a 12-second end-to-end fetch guarantee. System DNS resolution,
multiple-address connection attempts and TLS establishment retain Requests'
existing behavior and limits. The timer starts after a verified connection;
it does not interrupt an uninterruptible resolver or promise a whole-call
connection deadline. Closing this narrower response gap must not be reported
as proof that every possible transport stall has been eliminated.

Isolation and cleanup
---------------------

The adapter is mounted only on the temporary SEC Session. Its HTTPS pool uses
an owned connection class and a copied pool mapping, never mutation of the
global urllib3 mapping or an unrelated caller's transport. It does not reach
through private ``response.raw`` socket chains, weaken certificate validation,
follow redirects or add a background worker pool.

Each established response has one abort timer. Fetch cleanup cancels and joins
the timer and closes its owned socket on success, timeout and rejection.
Deadline expiry uses the existing ``requests.exceptions.Timeout`` category;
discovery and document jobs retain their existing bounded retry/backoff and
sanitized-error policies. A legitimately slow response can therefore be
deferred. No retry count, SEC request rate, byte cap or freshness rule changes.

Evidence and regression tests
-----------------------------

The synthetic local TLS fixture generates an ephemeral certificate, verifies
the certificate and hostname against its test-only trust root, and maps its
allowed hostname exclusively to loopback. It does not contact SEC. No private
key or Production record is committed.

Before the change, both trickling-header and trickling-body deadline assertions
failed while the same fixture's normal-response positive control passed.
Fixture setup failures are not counted as a reproduction. Tests cover actual
read interruption, socket/session/timer cleanup, unrelated-pool isolation and
the deliberately unbounded-by-this-timer DNS phase, plus the unchanged cache,
status, size, rate and caller contracts.

Run the relevant suites with external providers mocked::

    python -m pytest service/server/tests/test_sec_transport.py service/server/tests/test_sec_transport_safety.py -q
    python -m pytest service/server/tests/test_sec_intelligence.py service/server/tests/test_operational_recovery.py service/server/tests/test_news_evidence.py -q

Linux CI and Cloud Readiness remain the existing release checks, including the
PostgreSQL suites and container build. Passing these synthetic fixtures does
not prove a live SEC outage occurred or establish a trading advantage.

Release boundary
----------------

There is no migration, new environment flag, provider/model/budget change,
news/trading policy change, or modification of stored orders and positions.
No Production deployment is performed as part of preparing this fix. A future
merge/deployment requires explicit approval and the existing release gates,
encrypted backup and compatible image verification. Saved recovery contracts
and backup formats are unchanged; binary rollback never rewinds the database.

Primary references
------------------

* `Requests timeouts <https://requests.readthedocs.io/en/latest/user/advanced/#timeouts>`_
* `Requests adapter extension point <https://requests.readthedocs.io/en/latest/api/#requests.adapters.HTTPAdapter.init_poolmanager>`_
* `urllib3 HTTPS connection pool <https://urllib3.readthedocs.io/en/stable/reference/urllib3.connectionpool.html>`_
* `Python socket shutdown <https://docs.python.org/3/library/socket.html#socket.socket.shutdown>`_
