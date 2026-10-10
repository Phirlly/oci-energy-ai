"""Bounded public-office run history. Never receives uploaded bills or credentials."""

import json
import sqlite3
import time
from uuid import uuid4


class RunError(Exception):
    pass


class RunRepository:
    def __init__(self, path, *, clock=time.time):
        self.clock = clock
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS office_runs (
            id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
            created REAL NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
            events TEXT NOT NULL DEFAULT '[]', result TEXT, error TEXT)''')
        with self.db:
            self.db.execute("UPDATE office_runs SET status='interrupted', error=? WHERE status='running'",
                            ('Application restarted before the run completed.',))
        self.prune()

    def close(self):
        self.db.close()

    def prune(self, *, reserve=0):
        with self.db:
            self.db.execute("DELETE FROM office_runs WHERE status!='running' AND created < ?",
                            (self.clock() - 7 * 86400,))
            count = self.db.execute('SELECT count(*) FROM office_runs').fetchone()[0]
            self.db.execute('''DELETE FROM office_runs WHERE id IN (
                SELECT id FROM office_runs WHERE status!='running' ORDER BY created, rowid LIMIT ?)''',
                            (max(0, count - 100 + reserve),))

    @staticmethod
    def decode(row):
        return dict(id=row['id'], created=row['created'], **json.loads(row['payload']),
                    status=row['status'], events=json.loads(row['events']),
                    result=json.loads(row['result']) if row['result'] is not None else None,
                    error=row['error'])

    def existing(self, key, payload):
        self.prune()
        row = self.db.execute('SELECT * FROM office_runs WHERE request_key=?', (key,)).fetchone()
        if row is None:
            return None
        if json.loads(row['payload']) != payload:
            raise RunError('This request key belongs to different settings.')
        return self.decode(row)

    def create(self, key, payload):
        self.prune(reserve=1)
        run_id = str(uuid4())
        with self.db:
            self.db.execute('INSERT INTO office_runs(id,request_key,created,payload,status) VALUES(?,?,?,?,?)',
                            (run_id, key, self.clock(), json.dumps(payload, allow_nan=False), 'running'))
        return self.get(run_id)

    def get(self, run_id):
        self.prune()
        row = self.db.execute('SELECT * FROM office_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self.decode(row)

    def history(self):
        self.prune()
        return [self.decode(row) for row in self.db.execute('SELECT * FROM office_runs ORDER BY created DESC, rowid DESC')]

    def event(self, run_id, event):
        run = self.get(run_id)
        if run['status'] != 'running' or len(run['events']) >= 64:
            return
        run['events'].append(event)
        with self.db:
            self.db.execute("UPDATE office_runs SET events=? WHERE id=? AND status='running'",
                            (json.dumps(run['events'], allow_nan=False), run_id))

    def finish(self, run_id, status, *, result=None, error=None):
        if status not in {'complete', 'failed', 'cancelled'}:
            raise ValueError('Invalid terminal status.')
        with self.db:
            updated = self.db.execute("UPDATE office_runs SET status=?,result=?,error=? WHERE id=? AND status='running'",
                                      (status, json.dumps(result, allow_nan=False) if result is not None else None,
                                       error, run_id))
        return updated.rowcount == 1
