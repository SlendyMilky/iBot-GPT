"""Vérifications de la couche partagée (routage/budget, coût, historique, découpage).

Lancer :  python tests/test_core.py   (ou pytest tests/)
Aucun réseau, aucune clé réelle : le client Anthropic est remplacé par un faux.
"""
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ.setdefault('ANTHROPIC_API_KEY', 'test')
os.environ['USAGE_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'usage.db')
os.environ['OPUS_ROLE_IDS'] = '42'
os.environ['BUDGET_SOFT_USD'] = '5'
os.environ['BUDGET_HARD_USD'] = '8'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import _claude, _usage  # noqa: E402


class FakeBot:
    async def is_owner(self, user):
        return user.id == 1


def user(uid, roles=()):
    return SimpleNamespace(id=uid, roles=[SimpleNamespace(id=r) for r in roles])


def route(u, feature, opus=False):
    return asyncio.run(_claude.route(FakeBot(), None, u, feature, opus))


def spend(uid, usd):
    _usage.log_usage(uid, 'ask', 'm', 'low', 0, 0, usd)


def test_split_text():
    assert _claude.split_text('abc') == ['abc']
    parts = _claude.split_text('x' * 9000 + '\n' + 'y' * 10, 4000)
    assert all(p and len(p) <= 4000 for p in parts)
    assert ''.join(parts).count('x') == 9000
    assert _claude.split_text('') == ['']


def test_normalize_history():
    history = [
        {'role': 'system', 'content': 'ancien prompt'},   # ancien format Redis
        {'role': 'assistant', 'content': 'orphelin en tête'},
        {'role': 'user', 'content': 'a: salut'},
        {'role': 'user', 'content': 'b: coucou'},
        {'role': 'assistant', 'content': '   '},
        {'role': 'assistant', 'content': 'réponse'},
        {'role': 'user', 'content': 'a: merci'},
    ]
    assert _claude.normalize_history(history) == [
        {'role': 'user', 'content': 'a: salut\n\nb: coucou'},
        {'role': 'assistant', 'content': 'réponse'},
        {'role': 'user', 'content': 'a: merci'},
    ]


def test_routing_and_budget():
    u = user(100)
    c = route(u, 'forum')
    assert (c.tier, c.effort, c.note) == ('sonnet', 'medium', None)
    assert (route(u, 'ask').tier, route(u, 'ask').effort) == ('haiku', 'low')
    assert (route(u, 'helper').tier, route(u, 'helper').effort) == ('sonnet', 'low')

    # Opus : refusé sans rôle (repli sur le profil de la fonctionnalité), accordé avec le rôle
    c = route(u, 'helper', opus=True)
    assert (c.tier, c.effort) == ('sonnet', 'low') and c.note
    c = route(user(100, roles=[42]), 'forum', opus=True)
    assert (c.tier, c.effort, c.note) == ('opus', 'medium', None)

    # 5 $ : tout passe en Haiku low, y compris Opus
    spend(100, 5.0)
    c = route(user(100, roles=[42]), 'forum', opus=True)
    assert (c.tier, c.effort) == ('haiku', 'low') and c.note

    # 8 $ : bloqué
    spend(100, 3.0)
    assert route(u, 'ask') is None

    # Le créateur n'est jamais limité, et peut utiliser Opus sans rôle
    spend(1, 50.0)
    c = route(user(1), 'forum', opus=True)
    assert (c.tier, c.effort) == ('opus', 'medium')


def test_stream_reply_cost_and_logging():
    calls = {}

    class Stream:
        def __init__(self, final):
            self.final = final

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        @property
        def text_stream(self):
            async def gen():
                yield 'Bon'
                yield 'jour'
            return gen()

        async def get_final_message(self):
            return self.final

    def make(name):
        def stream(**kwargs):
            calls[name] = kwargs
            final = SimpleNamespace(
                content=[SimpleNamespace(type='thinking', text=''), SimpleNamespace(type='text', text='Bonjour')],
                usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
                model=kwargs['model'], stop_reason='end_turn', stop_details=None,
            )
            return Stream(final)
        return stream

    _claude.client = SimpleNamespace(
        messages=SimpleNamespace(stream=make('plain')),
        beta=SimpleNamespace(messages=SimpleNamespace(stream=make('beta'))),
    )

    shown = []

    async def on_text(t):
        shown.append(t)

    haiku = _claude.Choice('haiku', 'low')
    r = asyncio.run(_claude.stream_reply(haiku, 'sys', [{'role': 'user', 'content': 'hi'}], 100,
                                         user_id=7, feature='ask', on_text=on_text, interval=0))
    assert r.text == 'Bonjour'                       # le bloc thinking est ignoré
    assert abs(r.cost - (1000 * 0.10 + 500 * 0.50) / 1e6) < 1e-12
    assert calls['plain']['output_config'] == {'effort': 'low'} and 'fallbacks' not in calls['plain']
    assert shown                                      # le texte partiel a été diffusé
    assert abs(_usage.month_spend(7) - r.cost) < 1e-12

    asyncio.run(_claude.stream_reply(_claude.Choice('sonnet', 'medium'), 'sys', [], 100, user_id=7, feature='forum'))
    assert calls['beta']['fallbacks'] == 'default' and calls['beta']['output_config'] == {'effort': 'medium'}
    rows = _usage.month_breakdown(7)
    assert sum(row[1] for row in rows) == 2          # deux appels loggés


def test_finalize():
    ok = lambda text, stop: _claude.finalize(_claude.Reply(text, stop, 0, 0, 0.0))  # noqa: E731
    assert ok('salut', 'end_turn') == ('salut', True)
    assert ok('salut', 'max_tokens')[0].endswith('*(réponse tronquée)*')
    assert ok('', 'end_turn')[1] is False
    assert ok('texte', 'refusal')[1] is False


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
