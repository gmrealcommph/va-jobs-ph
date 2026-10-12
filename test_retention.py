"""Offline persistence tests. No collectors, credentials or network are loaded."""
import ast
import pathlib
import unittest

tree = ast.parse(pathlib.Path(__file__).with_name('main.py').read_text(encoding='utf-8'))
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('save_review_job', 'flush_job_batches')]
namespace = {}
exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), namespace)


class Store:
    def __init__(self):
        self.jobs = {('ashby', '1'): {'status': 'active'}, ('lever', '1'): {'status': 'active'}}
        self.reviews = {}

    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, store, name):
        self.store, self.name, self.filters = store, name, {}

    def upsert(self, rows, **kwargs):
        self.action, self.rows = 'upsert', rows if isinstance(rows, list) else [rows]
        return self

    def update(self, values):
        self.action, self.values = 'update', values
        return self

    def delete(self):
        if self.name == 'jobs':
            raise AssertionError('Published jobs must never be hard deleted')
        self.action = 'delete'
        return self

    def eq(self, key, value):
        self.filters[key] = [value]
        return self

    def in_(self, key, values):
        self.filters[key] = values
        return self

    def execute(self):
        table = self.store.jobs if self.name == 'jobs' else self.store.reviews
        if self.action == 'upsert':
            for row in self.rows:
                key = (row['source'], row['source_job_id'])
                table.setdefault(key, {}).update(row)
        else:
            for key in list(table):
                source, identifier = key
                if source in self.filters.get('source', [source]) and identifier in self.filters.get('source_job_id', [identifier]):
                    if self.action == 'delete':
                        del table[key]
                    else:
                        table[key].update(self.values)


class RetentionTests(unittest.TestCase):
    def test_legacy_review_retains_identity_and_other_source(self):
        store = Store()
        namespace['save_review_job'](store, {'source': 'ashby', 'source_job_id': '1'}, 'reject', 'Ineligible')
        self.assertEqual(store.jobs[('ashby', '1')]['status'], 'inactive')
        self.assertEqual(store.jobs[('lever', '1')]['status'], 'active')
        self.assertEqual(len(store.jobs), 2)

    def test_batches_retain_and_reopen_same_record(self):
        store = Store()
        namespace['flush_job_batches'](store, [], [{'source': 'ashby', 'source_job_id': '1'}], batch_size=1)
        self.assertEqual(store.jobs[('ashby', '1')]['status'], 'inactive')
        namespace['flush_job_batches'](store, [{'source': 'ashby', 'source_job_id': '1', 'status': 'active'}], [], batch_size=1)
        self.assertEqual(store.jobs[('ashby', '1')]['status'], 'active')
        self.assertNotIn(('ashby', '1'), store.reviews)
        self.assertEqual(len(store.jobs), 2)


if __name__ == '__main__':
    unittest.main()
