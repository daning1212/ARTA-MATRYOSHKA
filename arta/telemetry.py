"""Bounded JSON datagrams; no pickle/object deserialization at audit boundary."""
import json
import queue
import socket


class DatagramSink:
    def __init__(self, port, token):
        self.port, self.token = port, token
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def put_nowait(self, event):
        payload = json.dumps({'token': self.token, 'event': event}, separators=(',', ':')).encode()
        if len(payload) > 2048:
            raise ValueError('event exceeds datagram limit')
        try:
            self.sock.sendto(payload, ('127.0.0.1', self.port))
        except BlockingIOError as exc:
            raise queue.Full() from exc
