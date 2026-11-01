"""Pooled read-only transactions with one repeatable-read snapshot per operation."""

from contextlib import contextmanager
import logging

from psycopg2 import Error, sql


logger = logging.getLogger(__name__)


class SnapshotQueries:
    """Queries and recoverable optional groups on one snapshot cursor."""

    def __init__(self, cursor):
        self.cursor = cursor
        self.unavailable_relations = set()
        self.recovery_error = None
        self._savepoint_number = 0

    def __call__(self, statement, params=None, fetch_one=False):
        self.check_healthy()
        self.cursor.execute(statement, params)
        return self.cursor.fetchone() if fetch_one else self.cursor.fetchall()

    def check_healthy(self):
        if self.recovery_error is not None:
            raise self.recovery_error

    def lock(self, relations):
        self.check_healthy()
        names = sql.SQL(", ").join(sql.Identifier(*r) for r in relations)
        self.cursor.execute(sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(names))

    @contextmanager
    def savepoint(self):
        """Recover a failed optional group without changing the outer snapshot.

        Providers decide whether an error means unavailable data. Recovery
        errors poison the session and cannot be hidden by a provider's catch.
        """
        self.check_healthy()
        self._savepoint_number += 1
        name = f"epol_read_{self._savepoint_number}"
        try:
            self.cursor.execute(f"SAVEPOINT {name}")
        except Exception as exc:
            self.recovery_error = exc
            raise
        try:
            yield
        except BaseException:
            try:
                self.cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")
                self.cursor.execute(f"RELEASE SAVEPOINT {name}")
            except Exception as exc:
                self.recovery_error = exc
            raise
        else:
            try:
                self.cursor.execute(f"RELEASE SAVEPOINT {name}")
            except Exception as exc:
                self.recovery_error = exc
                raise


@contextmanager
def read_only_snapshot(connection_pool, *, protected_relations=(), optional_relations=()):
    """Yield a query callable bound to one cursor, connection and transaction.

    Relation names are trusted (schema, table) pairs, quoted as identifiers.
    Lock them before the first SELECT so a table-replacement sync cannot swap
    the source between snapshot acquisition and the calculation's table reads.
    Transaction-local settings leave session defaults intact. Always roll back
    the read transaction and restore autocommit before returning the connection;
    discard it if cleanup fails, preserving any original calculation error.
    Optional relations are locked in savepoints before the first SELECT too;
    missing/unreadable ones are recorded and must not be queried this operation.
    """
    conn = connection_pool.getconn()
    original_autocommit = None
    session = None
    failed = False
    try:
        original_autocommit = conn.autocommit
        conn.rollback()
        conn.autocommit = False
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            session = SnapshotQueries(cursor)
            if protected_relations:
                session.lock(protected_relations)
            for relation in optional_relations:
                try:
                    with session.savepoint():
                        session.lock((relation,))
                except Error:
                    session.check_healthy()
                    session.unavailable_relations.add(relation)
                    logger.warning("Optional snapshot source unavailable: %s.%s", *relation)
            yield session
            session.check_healthy()
    except BaseException:
        failed = True
        raise
    finally:
        cleanup_error = None
        try:
            conn.rollback()
            if original_autocommit is not None:
                conn.autocommit = original_autocommit
        except Exception as exc:
            cleanup_error = exc
        try:
            connection_pool.putconn(conn, close=(cleanup_error is not None or
                                                (session is not None and session.recovery_error is not None)))
        except Exception as exc:
            cleanup_error = cleanup_error or exc
            try:
                conn.close()
            except Exception:
                logger.exception("Could not close snapshot connection after pool return failed")
        if cleanup_error is not None:
            if failed:
                logger.error("Snapshot cleanup failed after calculation error", exc_info=(
                    type(cleanup_error), cleanup_error, cleanup_error.__traceback__))
            else:
                raise cleanup_error
