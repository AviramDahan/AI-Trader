Backup startup readiness
========================

The 11 October release reached API/monitor/scanner/Telegram readiness, then
rolled back when backup exceeded the 180-second Compose wait. Original failed
container logs were not retained: an internal backup exception is NOT proven.
The retained return-version backup completed in 156 seconds and was declared
healthy after 184 seconds; the predeploy archive took 154 seconds. Backup code
and SEC archive code did not change in PR 60. Startup plus its old 60-second
health sampling interval can exhaust a 180-second release budget.

The focused fix separates backup startup from the other workers: they retain
their 180-second gates, while backup has a bounded 600-second gate. Backup's
health poll is 15 seconds; its start period is the same bounded 600 seconds,
so more frequent polling cannot prematurely mark a valid slow first archive
unhealthy. The two failures and 7500-second freshness requirement remain
unchanged. A successful check still becomes healthy immediately during the
start period. The release independently inspects actual health for every
service after Compose exits: Linux tests found a Compose version returning
zero at its deadline while still "starting". That is a release failure, not
success. The same gates apply on return.
No CPU/RAM, archive, trading, schema, budget or provider setting changes.

The marker is still created ONLY after encryption, push and remote-commit
verification. No cached status file, file from the previous container, or
started process substitutes for successful backup. Missing/stale markers fail.
An actual failure still stops the release and invokes the existing binary
rollback without rewinding the database. Never clear a failed-release marker
and retry blindly.

Tests execute the release Bash itself with isolated command doubles and a
virtual slow backup. They reproduce the old timeout, then prove success,
bounded failure/rollback, prebackup failure, ordinary worker failure and the
unchanged lock/main/schema guards. They are not live GitHub or live backup
proof. A separate real Docker Compose probe in Linux uses the actual image and
health expression, scaled timing and no network/DB/credentials to reproduce
the timeout, pass the corrected startup and reject missing completion.
Existing PostgreSQL real-age backup tests verify remote confirmation
and failure behavior. All exact-release CI/readiness gates remain required.

Operator installation uses the existing protected SSH channel, verifies the
previous installed script, exact tested candidate bytes and root ownership,
and performs an atomic install while holding the existing deployment lock.
No alternate deployment path or gate bypass is introduced. After release,
verify all five actual service images, encrypted backup and accounting before
enabling PR 60's two creation flags; retain the actual capable server image
as the binary return target. Old 6429c42 is unsafe after format-5 contracts.
