"""회사코드 재사용 및 첫 병렬 조회의 중복 읽기를 재현한다."""
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import dart_inputs as di
import settings

XML = '<result><list><corp_code>C</corp_code><stock_code>005930</stock_code></list></result>'


class CorpMapReuseTest(unittest.TestCase):
    def test_worktree_finds_original_shared_corpcode(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = os.path.join(tmp, 'original', 'peer_wacc')
            shared = os.path.join(tmp, 'original', 'dart_downloader')
            worktree = os.path.join(tmp, 'worktree', 'peer_wacc')
            git_dir = os.path.join(original, '.git', 'worktrees', 'peer')
            for path in (shared, git_dir, worktree):
                os.makedirs(path, exist_ok=True)
            with open(os.path.join(worktree, '.git'), 'w', encoding='utf-8') as f:
                f.write('gitdir: ' + git_dir.replace('\\', '/'))
            with open(os.path.join(git_dir, 'commondir'), 'w', encoding='utf-8') as f:
                f.write('../..')
            with open(os.path.join(shared, 'CORPCODE.xml'), 'w', encoding='utf-8') as f:
                f.write(XML)
            with mock.patch.object(settings, 'APP_DIR', worktree), \
                 mock.patch.object(di, 'APP_DIR', worktree), \
                 mock.patch.object(di, '_DOWNLOADER_CORPCODE', os.path.join(tmp, 'missing.xml')), \
                 mock.patch.object(di, 'CACHE_DIR', os.path.join(worktree, 'cache')), \
                 mock.patch.dict(di._CORP_MAP_CACHE, {}, clear=True), \
                 mock.patch.object(di.requests, 'get', side_effect=AssertionError('must reuse existing XML')):
                self.assertEqual(di.load_corp_map('K'), {'005930': 'C'})

    def test_four_first_callers_parse_xml_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'CORPCODE.xml')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(XML)
            parse = di.ET.parse
            barrier = threading.Barrier(4)
            def slow_parse(path):
                time.sleep(.05)
                return parse(path)
            def load(_):
                barrier.wait(timeout=3)
                return di.load_corp_map('K')
            with mock.patch.object(di, 'CACHE_DIR', tmp), \
                 mock.patch.object(di, '_DOWNLOADER_CORPCODE', p), \
                 mock.patch.dict(di._CORP_MAP_CACHE, {}, clear=True), \
                 mock.patch.object(di.ET, 'parse', side_effect=slow_parse) as reader, \
                 ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(load, range(4)))
                self.assertEqual(results, [{'005930': 'C'}] * 4)
                self.assertEqual(reader.call_count, 1)
