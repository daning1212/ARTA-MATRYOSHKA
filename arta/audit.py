"""Bounded audit store; hashes detect changes, not privileged attackers."""
import hashlib
import json
import sqlite3
import threading
import time

class Store:
    def __init__(self, path, limit=10000):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.limit = limit
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, payload TEXT, previous TEXT, digest TEXT)')
        self.db.commit()

    def record(self, event):
        payload = json.dumps(event, sort_keys=True, ensure_ascii=False)
        with self.lock:
            previous = self.db.execute('SELECT digest FROM events ORDER BY id DESC LIMIT 1').fetchone()
            previous = previous[0] if previous else ''
            ts = time.time()
            digest = hashlib.sha256((previous + str(ts) + payload).encode()).hexdigest()
            self.db.execute('INSERT INTO events(ts,payload,previous,digest) VALUES(?,?,?,?)', (ts, payload, previous, digest))
            self.db.execute('DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id),0)-? FROM events)', (self.limit,))
            self.db.commit()

    def recent(self):
        with self.lock:
            return [{'id': row[0], 'time': row[1], **json.loads(row[2])} for row in self.db.execute('SELECT id,ts,payload FROM events ORDER BY id DESC LIMIT 100')]

    def verify(self):
        with self.lock:
            rows = list(self.db.execute('SELECT ts,payload,previous,digest FROM events ORDER BY id'))
        last = None
        for ts, payload, previous, digest in rows:
            if last is not None and previous != last:
                return False
            if hashlib.sha256((previous + str(ts) + payload).encode()).hexdigest() != digest:
                return False
            last = digest
        return True

