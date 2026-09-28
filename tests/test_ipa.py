import ast
import asyncio
from pathlib import Path
import queue
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
import uuid

from 音标查询 import 提取英文单词, 构建翻译结果, 解析美式音标, 剑桥音标客户端


# 人工构造的结构测试样例，不是抓取/分发的完整剑桥网页。
def 页面(word, us, uk="wrong-uk", extra=""):
    return (f'<div class="entry-body__el"><div class="pos-header dpos-h">'
            f'<span class="headword"><span class="hw dhw">{word}</span></span>'
            f'<span class="uk dpron-i"><span class="pron"><span class="ipa">{uk}</span></span></span>'
            + "".join(f'<span class="us dpron-i"><span class="pron"><span class="ipa">{ipa}</span></span></span>' for ipa in us)
            + '</div>' + extra + '</div>')


class IPATests(unittest.TestCase):
    def test_single_word_recognition(self):
        for text, expected in [("Hello!", "hello"), ("“apple”", "apple"),
                               ("don't", "don't"), ("don’t", "don't"), ("well-known", "well-known")]:
            self.assertEqual(提取英文单词(text), expected)
        for text in ("hello world", "hello\nworld", "你好", "hello_world", "123", "", "C++"):
            self.assertIsNone(提取英文单词(text))

    def test_initial_card_never_queries_or_loads_old_dictionary(self):
        result = 构建翻译结果("configuration", "configuration", "配置")
        self.assertNotIn("音标", result)
        self.assertIn("正在查询", result["音标提示"])
        self.assertTrue(result["词典链接"].endswith('/configuration'))
        self.assertFalse((Path(__file__).resolve().parents[1] / 'data' / 'en_US.txt').exists())

    def test_phrases_and_split_identifiers_keep_plain_layout(self):
        for original, processed in (("hello world", "hello world"),
                                    ("helloWorld", "hello World"), ("hello_world", "hello world")):
            self.assertEqual(构建翻译结果(original, processed, "你好世界"), {"译文": "你好世界"})

    def test_all_words_use_source_not_conversion_rules(self):
        # 覆盖重音、音节点、嵌套的弱读元音、长元音、闪音符号和可选音。
        cases = {"configuration": ("kənˌfɪɡ.jəˈreɪ.ʃ<span>ə</span>n", "/kənˌfɪɡjəˈreɪʃən/"),
                 "apple": ("ˈæp.əl", "/ˈæpəl/"), "bird": ("bɝːd", "/bɝːd/"),
                 "water": ("ˈwɑː.t̬ɚ", "/ˈwɑːt̬ɚ/"), "teacher": ("ˈtiː.tʃɚ", "/ˈtiːtʃɚ/"),
                 "testword": ("tə(s)t", "/tə(s)t/")}
        for word, (raw, expected) in cases.items():
            with self.subTest(word=word):
                request = Mock(return_value=页面(word, [raw]))
                result = 剑桥音标客户端(请求=request).查询(word)
                self.assertEqual(result["音标"], [expected])
                self.assertEqual(result["音标来源"], "Cambridge Dictionary · US")
                request.assert_called_once()

    def test_multiple_us_pronunciations_preserved_without_duplicates(self):
        html = 页面("read", ["riːd", "red", "riːd"])
        self.assertEqual(解析美式音标(html, "read"), ["/riːd/", "/red/"])

    def test_uk_unknown_region_and_other_headwords_are_not_used(self):
        self.assertEqual(解析美式音标(页面("bird", ["bɝːd"]), "birds"), [])
        self.assertEqual(解析美式音标(页面("bird", []), "bird"), [])
        html = '<div class="pos-header"><span class="hw">bird</span><span class="ipa">bɜːd</span></div>'
        self.assertEqual(解析美式音标(html, "bird"), [])
        self.assertEqual(解析美式音标('<span class="us"><span class="ipa">bad</span></span>', "bird"), [])

    def test_derivatives_idioms_and_sidebar_are_excluded(self):
        nested = '<div class="runon">' + 页面("configuration", ["wrong-derived"]) + '</div>'
        html = 页面("configuration", ["kənˌfɪɡ.jəˈreɪ.ʃən"], extra=nested)
        html += 页面("configure", ["wrong-other-word"])
        self.assertEqual(解析美式音标(html, "configuration"), ["/kənˌfɪɡjəˈreɪʃən/"])

    def test_service_errors_do_not_supply_fallback_ipa(self):
        for error in (HTTPError('https://dictionary.cambridge.org',403,'Forbidden',{},None),
                      HTTPError('https://dictionary.cambridge.org',429,'Limited',{},None),
                      HTTPError('https://dictionary.cambridge.org',404,'Not found',{},None),
                      TimeoutError(), URLError('offline'), ValueError()):
            with self.subTest(error=type(error)):
                result = 剑桥音标客户端(请求=Mock(side_effect=error)).查询('configuration')
                self.assertIn('音标提示',result)
                self.assertNotIn('音标',result)

    def test_blocked_response_has_cooldown_without_retries(self):
        request = Mock(side_effect=HTTPError('https://dictionary.cambridge.org',403,'Forbidden',{},None))
        client = 剑桥音标客户端(请求=request)
        client.查询('configuration')
        result=client.查询('apple')
        request.assert_called_once()
        self.assertIn('拒绝',result['音标提示'])

    def test_challenge_page_is_not_a_dictionary_result(self):
        request=Mock(return_value='<html><title>Just a moment...</title><script src="/challenge-platform/"></script></html>')
        client=剑桥音标客户端(请求=request)
        self.assertIn('验证',client.查询('configuration')['音标提示'])
        client.查询('apple')
        request.assert_called_once()

    def test_malformed_or_missing_entry_does_not_claim_correct_ipa(self):
        for data in ('<html>not found</html>', None, 页面('otherword',['wrong'])):
            self.assertNotIn('音标', 剑桥音标客户端(请求=Mock(return_value=data)).查询('configuration'))


class TranslationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setup_app(self, cached, client):
        source=Path(__file__).resolve().parents[1]/'01 ⭐️ 主程序.py'
        tree=ast.parse(source.read_text(encoding='utf-8-sig'))
        nodes=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in {'翻译并显示','补充单词音标'}]
        env={'asyncio':asyncio,'uuid':uuid,'预处理翻译文本':lambda x:x,'缓存键':lambda x:x.lower(),
             '翻译缓存':{'configuration':'配置'} if cached else {}, 'KEY':'fake-test-key',
             '调用翻译接口':Mock(return_value='配置'),'保存翻译缓存':Mock(),'更新翻译记录':Mock(),
             '翻译队列':queue.Queue(),'构建翻译结果':构建翻译结果,'音标客户端':client,'print':Mock()}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),env)
        return env

    async def test_translation_shown_before_ipa_for_cached_and_new_results(self):
        for cached in (True,False):
            with self.subTest(cached=cached):
                entered, release=threading.Event(),threading.Event()
                def query(word):
                    entered.set(); release.wait(2)
                    return {'音标':['/kənˌfɪɡjəˈreɪʃən/']}
                env=self.setup_app(cached,Mock(查询=query,超时秒=3))
                task=asyncio.create_task(env['翻译并显示']('configuration'))
                try:
                    for _ in range(100):
                        if entered.is_set(): break
                        await asyncio.sleep(.01)
                    initial=env['翻译队列'].get_nowait()
                    self.assertEqual(initial['译文'],'配置')
                    self.assertNotIn('音标',initial)
                    self.assertFalse(task.done())
                finally:
                    release.set()
                await task
                update=env['翻译队列'].get_nowait()
                self.assertEqual(update['请求ID'],initial['请求ID'])
                self.assertTrue(update['更新音标'])
                self.assertEqual(update['音标'],['/kənˌfɪɡjəˈreɪʃən/'])
                self.assertEqual(env['调用翻译接口'].call_count,0 if cached else 1)

    async def test_cancelled_word_does_not_publish_late_update(self):
        entered,release=threading.Event(),threading.Event()
        def query(word):
            entered.set(); release.wait(2)
            return {'音标':['/old/']}
        env=self.setup_app(True,Mock(查询=query,超时秒=3))
        task=asyncio.create_task(env['翻译并显示']('configuration'))
        for _ in range(100):
            if entered.is_set(): break
            await asyncio.sleep(.01)
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(env['翻译队列'].qsize(),1)

    async def test_lookup_failure_preserves_translation(self):
        env=self.setup_app(True,Mock(查询=Mock(side_effect=RuntimeError()),超时秒=3))
        await env['翻译并显示']('configuration')
        self.assertEqual(env['翻译队列'].get_nowait()['译文'],'配置')
        self.assertIn('音标提示',env['翻译队列'].get_nowait())

    def test_stale_updates_cannot_reopen_or_replace_cards(self):
        source=Path(__file__).resolve().parents[1]/'01 ⭐️ 主程序.py'
        tree=ast.parse(source.read_text(encoding='utf-8-sig'))
        window=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='翻译窗口线程')
        display=next(n for n in window.body if isinstance(n,ast.FunctionDef) and n.name=='显示译文')
        card=Mock()
        state={'win':object(),'请求ID':'new','卡片':card}
        env={'状态':state}
        exec(compile(ast.Module(body=[display],type_ignores=[]),str(source),'exec'),env)
        env['显示译文']({'更新音标':True,'请求ID':'old','音标':['/old/']})
        card.更新音标.assert_not_called()
        env['显示译文']({'更新音标':True,'请求ID':'new','音标':['/new/']})
        card.更新音标.assert_called_once()
        state['win']=None
        env['显示译文']({'更新音标':True,'请求ID':'new','音标':['/new/']})
        card.更新音标.assert_called_once()


if __name__=='__main__': unittest.main()
