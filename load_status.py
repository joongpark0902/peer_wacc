"""피어 조회의 실제 대기 단계와 시간을 스레드 안전하게 추적한다."""
import threading
import time


class LoadStatus:
    def __init__(self, total, log=print, clock=time.perf_counter):
        self.total, self.log, self.clock = total, log, clock
        self.started = clock()
        self.active = {}
        self.finished = set()
        self.lock = threading.Lock()

    def run(self, code, name, stage, function, *args, **kwargs):
        started = self.clock()
        with self.lock:
            self.active[code] = (name, stage, started)
        try:
            return function(*args, **kwargs)
        finally:
            self.log(f"[조회시간] {name} ({code}) · {stage} · {self.clock()-started:.2f}초")

    def complete(self, code):
        with self.lock:
            self.finished.add(code)
            self.active.pop(code, None)

    def text(self):
        now = self.clock()
        with self.lock:
            text = f"불러오는 중 {len(self.finished)}/{self.total}"
            if self.active:
                name, stage, started = min(self.active.values(), key=lambda item: item[2])
                text += f" · {name} {stage} {now-started:.1f}초"
            return text + f" · 전체 {now-self.started:.1f}초"

    def elapsed(self):
        return self.clock() - self.started
