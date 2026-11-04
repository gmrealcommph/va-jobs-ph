"""Offline failure injection and real PostgREST request contract tests."""
import ast
from copy import deepcopy
import io
from contextlib import redirect_stdout
import unittest
from unittest.mock import Mock, patch

import httpx
from postgrest import SyncPostgrestClient
from postgrest.exceptions import APIError

import db_retry
from test_retention import Store, Query, namespace, tree


class FaultStore(Store):
    def __init__(self, target, failures, commit_first=False):
        super().__init__()
        self.target, self.failures = target, list(failures)
        self.commit_first = commit_first
        self.calls = []

    def table(self, name):
        return FaultQuery(self, name)


class FaultQuery(Query):
    def upsert(self, rows, **kwargs):
        self.options = kwargs
        return super().upsert(rows, **kwargs)

    def execute(self):
        call = (self.name, self.action, deepcopy(getattr(self, 'rows', None)),
                deepcopy(self.filters), getattr(self, 'options', None))
        self.store.calls.append(call)
        if (self.name, self.action) == self.store.target and self.store.failures:
            error = self.store.failures.pop(0)
            if self.store.commit_first:
                super().execute()
            raise error
        return super().execute()


def row(identifier='1', source='ashby', **values):
    return dict(source=source, source_job_id=identifier, **values)


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch('db_retry.time.sleep').start()
        patch('db_retry.random.uniform', return_value=0.5).start()
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def flush(self, store, published=None, review=None):
        namespace['flush_job_batches'](store, published or [], review or [])

    def test_timeout_then_success_and_logs(self):
        store = FaultStore(('jobs', 'upsert'), [httpx.ReadTimeout('secret')])
        self.flush(store, [row()])
        self.assertEqual(store.calls[0], store.calls[1])
        self.sleep.assert_called_once_with(1.5)
        log = self.output.getvalue()
        for field in ('table=jobs', 'operation=upsert', 'batch=1', 'rows=1',
                      'attempt=1/4', 'attempt=2/4', 'elapsed=', 'result=success'):
            self.assertIn(field, log)
        self.assertNotIn('secret', log)

    def test_commit_before_timeout_replays_without_duplicate_or_identity_loss(self):
        store = FaultStore(('jobs', 'upsert'), [httpx.ReadTimeout('')], True)
        store.jobs[('ashby', '1')].update(id='retained-id', reports=['report'])
        self.flush(store, [row(status='active')])
        self.assertEqual(store.calls[0], store.calls[1])
        self.assertEqual(len(store.jobs), 2)
        self.assertEqual(store.jobs[('ashby', '1')]['id'], 'retained-id')
        self.assertEqual(store.jobs[('ashby', '1')]['reports'], ['report'])

    def test_exhaustion_stops_before_later_writes_cleanup_and_reconciliation(self):
        error = httpx.ReadTimeout('')
        store = FaultStore(('jobs', 'upsert'), [error] * 4)
        # Execute the actual main() write/reconcile statements, with all
        # collection work omitted, to prove propagation across the boundary.
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        start = next(i for i, n in enumerate(main.body) if isinstance(n, ast.Expr)
                     and isinstance(n.value, ast.Call)
                     and isinstance(n.value.func, ast.Name) and n.value.func.id == 'flush_job_batches')
        reconcile = Mock()
        scope = dict(namespace, supabase=store, published_jobs=[row()],
                     review_jobs=[row('2')], successful_boards=[],
                     reconcile_expired_jobs=reconcile)
        with self.assertRaises(httpx.ReadTimeout) as caught:
            exec(compile(ast.Module(body=main.body[start:start + 2], type_ignores=[]), 'main.py', 'exec'), scope)
        self.assertIs(caught.exception, error)
        self.assertEqual(len(store.calls), 4)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [1.5, 2.5, 4.5])
        reconcile.assert_not_called()

    def test_permanent_errors_fail_immediately(self):
        for error in (APIError(dict(code='23505', message='constraint', details=None, hint=None)),
                      APIError(dict(code='42501', message='denied', details=None, hint=None)),
                      ValueError('bad payload')):
            with self.subTest(error=error):
                store = FaultStore(('jobs', 'upsert'), [error])
                with self.assertRaises(type(error)):
                    self.flush(store, [row()])
                self.assertEqual(len(store.calls), 1)
        self.sleep.assert_not_called()

    def test_selected_transient_responses(self):
        for code in db_retry.TRANSIENT_CODES:
            self.assertTrue(db_retry.is_transient(APIError(dict(code=code, message='', details=None, hint=None))))
        for status in (408, 429, 500, 502, 503, 504, 400, 401, 403, 404, 409, 422):
            error = httpx.HTTPStatusError('', request=httpx.Request('POST', 'https://offline.test'),
                                          response=httpx.Response(status))
            self.assertEqual(db_retry.is_transient(error), status in db_retry.TRANSIENT_STATUSES)

    def test_cleanup_replay_preserves_source_and_referenced_records(self):
        for target, published, review in ((('job_reviews', 'delete'), [row()], []),
                                           (('jobs', 'update'), [], [row()])):
            with self.subTest(target=target):
                store = FaultStore(target, [httpx.ReadTimeout('')], True)
                store.reviews = {('ashby', '1'): {}, ('lever', '1'): {}}
                self.flush(store, published, review)
                self.assertEqual(store.calls[-1], store.calls[-2])
                self.assertEqual(store.calls[-1][3], {'source': ['ashby'], 'source_job_id': ['1']})
                self.assertEqual(store.jobs[('lever', '1')]['status'], 'active')
                self.assertIn(('lever', '1'), store.reviews)
                self.assertEqual(len(store.jobs), 2)

    def test_review_and_cleanup_exhaustion_propagate(self):
        for target in (('job_reviews', 'upsert'), ('job_reviews', 'delete'), ('jobs', 'update')):
            store = FaultStore(target, [httpx.ReadTimeout('')] * 4)
            with self.assertRaises(httpx.ReadTimeout):
                self.flush(store, [row('2')], [row()])
            self.assertEqual(sum(c[:2] == target for c in store.calls), 4)
            self.assertEqual(store.calls[-1][:2], target)

    def test_batch_size_deduplication_minimal_and_missing_cleanup_keys(self):
        store = FaultStore(None, [])
        rows = [row(str(i)) for i in range(201)] + [row('0', title='last')]
        self.flush(store, rows)
        writes = [c for c in store.calls if c[1] == 'upsert']
        self.assertEqual([len(c[2]) for c in writes], [200, 1])
        self.assertEqual(writes[0][2][0]['title'], 'last')
        for call in writes:
            self.assertEqual(call[4], {'on_conflict': 'source,source_job_id', 'returning': 'minimal'})
        # Keyless records remain eligible for upsert, but never cleanup.
        client = Mock()
        self.flush(client, [{'title': 'keyless'}])
        client.table.assert_called_once_with('jobs')

    def test_real_postgrest_minimal_request_and_timeout_replay(self):
        requests = []
        def handle(request):
            requests.append(request)
            if len(requests) == 1:
                raise httpx.ReadTimeout('committed but response lost', request=request)
            return httpx.Response(201, content=b'')
        with SyncPostgrestClient('https://offline.test') as client:
            client.session = httpx.Client(transport=httpx.MockTransport(handle))
            result = db_retry.execute_with_retry(
                lambda: client.table('jobs').upsert([row()], on_conflict='source,source_job_id', returning='minimal'),
                table='jobs', operation='upsert', batch_number=1, row_count=1)
        self.assertEqual(result.data, [])
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].content, requests[1].content)
        self.assertIn('return=minimal', requests[0].headers['prefer'])
        self.assertIn('resolution=merge-duplicates', requests[0].headers['prefer'])
        self.assertEqual(requests[0].url.params['on_conflict'], 'source,source_job_id')


if __name__ == '__main__':
    unittest.main()
