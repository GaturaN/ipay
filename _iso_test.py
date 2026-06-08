"""Two-connection reproduction of the snapshot/locking-read interaction.

Mirrors the exact shape of the real finaliser race:
  - Connection L (the LOSER): early PLAIN read of request row A (pins the
    REPEATABLE-READ snapshot), then SELECT ... FOR UPDATE on row A, then a
    PLAIN read of Payment-Entry-like table B (unique key on ref) -> this is
    make_payment_entry.py:30 / :207.
  - Connection W (the WINNER): inserts the row into B and COMMITs while L is
    blocked on FOR UPDATE.

We assert:
  pre_insert_sees_PE  (plain read on B after the FOR UPDATE unblocks, before any rollback)
  except_block_sees_PE (same plain read, modelling line 207, still pre-rollback)
  after_rollback_sees_PE (plain read on B AFTER rollback)
"""
import time
import threading
import frappe
from frappe.database import get_db


def fresh_conn():
    db = get_db()
    db.connect()
    return db


def main():
    a = fresh_conn()  # LOSER
    b = fresh_conn()  # WINNER

    # clean slate
    a.sql("CREATE TABLE IF NOT EXISTS _iso_req (id INT PRIMARY KEY, val VARCHAR(50)) ENGINE=InnoDB")
    a.sql("CREATE TABLE IF NOT EXISTS _iso_pe (id INT PRIMARY KEY AUTO_INCREMENT, ref VARCHAR(50), UNIQUE KEY uq_ref (ref)) ENGINE=InnoDB")
    a.sql("DELETE FROM _iso_pe")
    a.sql("DELETE FROM _iso_req")
    a.sql("INSERT INTO _iso_req (id, val) VALUES (1, 'reqA')")
    a.commit()

    iso = a.sql("SELECT @@session.tx_isolation AS i")[0][0]
    print("session isolation:", iso)

    results = {}

    # ---- LOSER: open txn, EARLY PLAIN read on A (pins snapshot) ----
    a.sql("START TRANSACTION")
    a.sql("SELECT val FROM _iso_req WHERE id=1")  # plain read -> pins consistent-read snapshot

    blocked_done = threading.Event()

    def loser_path():
        # SELECT ... FOR UPDATE on A: will block until WINNER commits? No — A is
        # not locked by WINNER. The real serialisation is finalize_payment's
        # for_update on the REQUEST row. To model that, the WINNER must hold the
        # request row lock first. We model the true race below instead.
        pass

    # ---- WINNER: take request row lock, insert PE, commit, release ----
    # Model finalize_payment: WINNER locks request A FOR UPDATE first.
    b.sql("START TRANSACTION")
    b.sql("SELECT val FROM _iso_req WHERE id=1 FOR UPDATE")  # winner holds row lock on A

    # LOSER now tries to lock A FOR UPDATE in a thread -> must block on WINNER.
    def loser_lock():
        t0 = time.time()
        a.sql("SELECT val FROM _iso_req WHERE id=1 FOR UPDATE")  # blocks on winner
        results["block_secs"] = time.time() - t0
        blocked_done.set()

    th = threading.Thread(target=loser_lock)
    th.start()
    time.sleep(0.6)  # ensure loser is parked on the lock

    # WINNER inserts the PE row and commits (releases the A row lock).
    b.sql("INSERT INTO _iso_pe (ref) VALUES ('TX123')")
    b.commit()

    th.join(timeout=10)
    print("loser blocked for ~%.2fs on FOR UPDATE" % results.get("block_secs", -1))

    # LOSER has now acquired the FOR UPDATE lock on A. Model make_payment_entry:
    # pre-insert idempotency check (line 30) — plain read on B:
    pre = a.sql("SELECT id FROM _iso_pe WHERE ref='TX123'")
    results["pre_insert_sees_PE"] = bool(pre)

    # LOSER attempts INSERT -> should hit unique-key 1062
    errno_1062 = False
    try:
        a.sql("INSERT INTO _iso_pe (ref) VALUES ('TX123')")
    except Exception as e:
        errno_1062 = "1062" in str(e) or "Duplicate" in str(e)
    results["insert_failed_1062"] = errno_1062

    # except block (line 207): plain read on B, BEFORE rollback
    exb = a.sql("SELECT id FROM _iso_pe WHERE ref='TX123'")
    results["except_block_sees_PE"] = bool(exb)

    # Now rollback (line 214) and re-read
    a.rollback()
    aft = a.sql("SELECT id FROM _iso_pe WHERE ref='TX123'")
    results["after_rollback_sees_PE"] = bool(aft)

    print("RESULTS:", results)

    # cleanup
    a.sql("START TRANSACTION")
    a.sql("DROP TABLE IF EXISTS _iso_pe")
    a.sql("DROP TABLE IF EXISTS _iso_req")
    a.commit()
    a.close()
    b.close()


main()
