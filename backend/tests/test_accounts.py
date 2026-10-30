"""Meaningful cross-account, administrative, session, and queue isolation checks."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.security import COOKIE_NAME
from .test_system import submit, good_report

INITIAL = 'initial-password-123'
CHANGED = 'changed-password-456'


@pytest.fixture
def learner_factory(app, logged_in):
    clients=[]
    def create(username='student', *, finish=True, **kwargs):
        result=logged_in.post('/api/admin/users',json={'username':username,'password':INITIAL,**kwargs})
        assert result.status_code == 201, result.text
        client=TestClient(app)
        clients.append(client)
        login=client.post('/api/auth/login',headers={'X-FDE-Client':'web'},json={'username':username,'password':INITIAL})
        assert login.status_code == 200
        client.headers.update({'X-FDE-Client':'web','X-CSRF-Token':login.json()['csrf_token']})
        if finish:
            changed=client.post('/api/auth/change-password',json={'current_password':INITIAL,'new_password':CHANGED})
            assert changed.status_code == 200, changed.text
            client.headers['X-CSRF-Token']=changed.json()['csrf_token']
        return client,result.json()
    yield create
    for client in clients:
        client.close()


def test_first_admin_new_account_password_gate_and_permissions(logged_in, learner_factory):
    assert logged_in.get('/api/auth/status').json()['user']['role'] == 'admin'
    learner,user=learner_factory(finish=False)
    assert user['must_change_password'] is True
    assert learner.get('/api/course').status_code == 403
    assert learner.get('/api/admin/users').status_code == 403
    assert learner.post('/api/auth/change-password',json={'current_password':'incorrect-current','new_password':CHANGED}).status_code == 403
    changed=learner.post('/api/auth/change-password',json={'current_password':INITIAL,'new_password':CHANGED})
    assert changed.status_code == 200 and not changed.json()['user']['must_change_password']
    learner.headers['X-CSRF-Token']=changed.json()['csrf_token']
    assert learner.get('/api/course').status_code == 200
    assert learner.get('/api/admin/users').status_code == 403
    assert learner.post('/api/admin/users',json={'username':'attacker','password':INITIAL}).status_code == 403
    assert learner.patch('/api/admin/users/1',json={'role':'learner'}).status_code == 403
    assert learner.post('/api/admin/users/1/password',json={'new_password':INITIAL}).status_code == 403
    assert learner.put('/api/settings/ai',json={'base_url':'https://example.com/v1','model':'test'}).status_code == 403
    assert learner.post('/api/settings/ai/test').status_code == 403


def test_progress_submissions_files_and_reviews_are_private(configured, learner_factory):
    learner,user=learner_factory()
    owner_sub=configured.post('/api/tasks/w01-t01/submissions',data={'content':'管理员的私有作业'},files={'files':('secret.txt',b'private owner file')}).json()
    owner_review=configured.post(f"/api/submissions/{owner_sub['id']}/reviews",json={'consent':True}).json()['review_id']
    configured.patch('/api/tasks/w01-t01/progress',json={'status':'completed','notes':'private admin note'})
    assert learner.get('/api/course').json()['progress'] == {}
    assert learner.get('/api/dashboard').json()['submitted_tasks'] == 0
    assert learner.get('/api/submissions').json()['items'] == []
    assert learner.get(f"/api/submissions/{owner_sub['id']}").status_code == 404
    assert learner.get(owner_sub['files'][0]['download_url']).status_code == 404
    assert learner.get(f'/api/reviews/{owner_review}').status_code == 404
    assert learner.post(f"/api/submissions/{owner_sub['id']}/reviews",json={'consent':True}).status_code == 404
    own=submit(learner,'客户需求与验收标准；学习者自己的证据')
    assert own['version'] == 1
    assert learner.get('/api/submissions?task_id=w01-t01').json()['total'] == 1
    assert configured.get(f"/api/submissions/{own['id']}").status_code == 404
    assert configured.get('/api/submissions').json()['total'] == 1
    learner.patch('/api/tasks/w01-t01/progress',json={'status':'in_progress','notes':'learner note'})
    assert configured.get('/api/course').json()['progress']['w01-t01']['notes'] == 'private admin note'
    assert learner.get('/api/course').json()['progress']['w01-t01']['notes'] == 'learner note'
    settings=learner.get('/api/settings/ai').json()
    assert settings['can_manage'] is False and settings['base_url'] == '' and settings['api_key_set'] is True
    assert 'api_key_cipher' not in settings and 'api_key' not in settings


def test_reset_disable_and_role_changes_revoke_sessions(configured, learner_factory, app):
    learner,user=learner_factory()
    other=TestClient(app)
    logged=other.post('/api/auth/login',headers={'X-FDE-Client':'web'},json={'username':'student','password':CHANGED})
    assert logged.status_code == 200
    reset=configured.post(f"/api/admin/users/{user['id']}/password",json={'new_password':'reset-password-789'})
    assert reset.status_code == 200
    assert learner.get('/api/course').status_code == 401
    assert other.get('/api/course').status_code == 401
    assert other.post('/api/auth/login',headers={'X-FDE-Client':'web'},json={'username':'student','password':CHANGED}).status_code == 401
    relog=other.post('/api/auth/login',headers={'X-FDE-Client':'web'},json={'username':'student','password':'reset-password-789'})
    assert relog.status_code == 200 and relog.json()['user']['must_change_password']
    other.headers.update({'X-FDE-Client':'web','X-CSRF-Token':relog.json()['csrf_token']})
    changed=other.post('/api/auth/change-password',json={'current_password':'reset-password-789','new_password':'third-password-123'})
    assert changed.status_code == 200
    other.headers['X-CSRF-Token']=changed.json()['csrf_token']
    same=configured.patch(f"/api/admin/users/{user['id']}",json={'role':'learner','display_name':'New label'})
    assert same.status_code == 200
    assert other.get('/api/course').status_code == 200  # No-op role does not revoke.
    assert configured.patch(f"/api/admin/users/{user['id']}",json={'is_active':False}).status_code == 200
    assert other.get('/api/course').status_code == 401
    assert other.post('/api/auth/login',json={'username':'student','password':'third-password-123'}).status_code == 401
    assert configured.patch(f"/api/admin/users/{user['id']}",json={'is_active':True}).status_code == 200
    assert other.get('/api/course').status_code == 401  # Old cookies stay invalid after enabling.
    other.close()
    with app.state.db.connect() as c:
        audit=json.dumps([dict(r) for r in c.execute('SELECT * FROM admin_audit')])
        assert 'reset-password-789' not in audit and INITIAL not in audit


def test_password_change_invalidates_other_device_and_self_protection(logged_in, app):
    old_cookie=logged_in.cookies.get(COOKIE_NAME)
    old_csrf=logged_in.headers['X-CSRF-Token']
    changed=logged_in.post('/api/auth/change-password',json={'current_password':'a-strong-test-password','new_password':'owner-new-password-123'})
    assert changed.status_code == 200
    logged_in.headers['X-CSRF-Token']=changed.json()['csrf_token']
    with TestClient(app) as old:
        old.cookies.set(COOKIE_NAME,old_cookie)
        old.headers.update({'X-FDE-Client':'web','X-CSRF-Token':old_csrf})
        assert old.get('/api/course').status_code == 401
    assert logged_in.patch('/api/admin/users/1',json={'role':'learner'}).status_code == 409
    assert logged_in.patch('/api/admin/users/1',json={'is_active':False}).status_code == 409
    assert logged_in.post('/api/admin/users/1/password',json={'new_password':INITIAL}).status_code == 409


def test_user_and_global_review_quotas_remain_separate(configured, learner_factory, app, monkeypatch):
    learner,user=learner_factory(review_daily_limit=1)
    own=submit(learner)
    first=learner.post(f"/api/submissions/{own['id']}/reviews",json={'consent':True})
    assert first.status_code == 202
    monkeypatch.setattr('app.ai.chat_completion',lambda *a,**k:(json.dumps(good_report()),{}))
    assert app.state.worker.process_next()
    assert learner.post(f"/api/submissions/{own['id']}/reviews",json={'consent':True}).status_code == 429
    usage=learner.get('/api/usage').json()
    assert usage['reviews']['used'] == usage['reviews']['limit'] == 1
    assert usage['reviews']['global_remaining'] == 29
    assert usage['materials']['used'] == 0
    admin_sub=submit(configured)
    app.state.config.max_reviews_per_day=1
    assert configured.post(f"/api/submissions/{admin_sub['id']}/reviews",json={'consent':True}).status_code == 429


@pytest.mark.parametrize('change',[{'is_active':False},{'reset':True}])
def test_queued_review_does_not_call_ai_after_disabled_or_reset(configured, learner_factory, app, monkeypatch, change):
    learner,user=learner_factory()
    sub=submit(learner)
    job=learner.post(f"/api/submissions/{sub['id']}/reviews",json={'consent':True}).json()
    if 'reset' in change:
        assert configured.post(f"/api/admin/users/{user['id']}/password",json={'new_password':'reset-password-new'}).status_code == 200
    else:
        assert configured.patch(f"/api/admin/users/{user['id']}",json=change).status_code == 200
    called=[]
    monkeypatch.setattr('app.ai.chat_completion',lambda *a,**k:called.append(True))
    assert app.state.worker.process_next()
    assert called == []
    with app.state.db.connect() as c:
        row=c.execute('SELECT * FROM reviews WHERE id=?',(job['review_id'],)).fetchone()
        assert row['status'] == 'failed' and row['report'] is None


def test_concurrent_submission_versions_are_unique(logged_in):
    def post(i):
        response=logged_in.post('/api/tasks/w01-t01/submissions',data={'content':f'parallel submission {i}'})
        assert response.status_code == 201, response.text
        return response.json()['version']
    with ThreadPoolExecutor(max_workers=4) as pool:
        versions=list(pool.map(post,range(4)))
    assert sorted(versions) == [1,2,3,4]


def test_login_does_not_issue_session_for_password_changed_during_verification(logged_in, app, monkeypatch):
    import app.main as main_module
    original_check = main_module.check_password
    replacement = main_module.hash_password('replacement-password-123')
    def concurrent_password_change(password, encoded):
        valid = original_check(password, encoded)
        if valid:
            # Simulate another device changing password after verification and
            # revoking all old sessions, but before this login writes its cookie.
            with app.state.db.connect() as c:
                c.execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE id=1', (replacement,))
                c.execute('DELETE FROM sessions WHERE user_id=1')
        return valid
    monkeypatch.setattr(main_module, 'check_password', concurrent_password_change)
    client = TestClient(app)
    response = client.post('/api/auth/login', headers={'X-FDE-Client':'web'}, json={
        'username':'learner', 'password':'a-strong-test-password',
    })
    assert response.status_code == 401
    assert COOKIE_NAME not in response.cookies
    assert client.get('/api/course').status_code == 401
    with app.state.db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
    client.close()


def test_password_change_does_not_issue_session_after_concurrent_admin_reset(logged_in, app, monkeypatch):
    from contextlib import contextmanager
    import app.main as main_module
    original_connect = app.state.db.connect
    reset_hash = main_module.hash_password('concurrent-reset-password')
    injected = []
    @contextmanager
    def raced_connect():
        changed = []
        with original_connect() as conn:
            conn.set_trace_callback(lambda sql: changed.append(True) if sql.startswith('UPDATE users SET password_hash=') and 'must_change_password=0' in sql else None)
            yield conn
        # The password change committed; a reset wins before create_session.
        if changed and not injected:
            injected.append(True)
            with original_connect() as other:
                other.execute('UPDATE users SET password_hash=?,must_change_password=1 WHERE id=1', (reset_hash,))
                other.execute('DELETE FROM sessions WHERE user_id=1')
    monkeypatch.setattr(app.state.db, 'connect', raced_connect)
    response = logged_in.post('/api/auth/change-password', json={
        'current_password':'a-strong-test-password', 'new_password':'requested-new-password',
    })
    assert injected == [True]
    assert response.status_code == 401
    assert COOKIE_NAME not in response.cookies
    with original_connect() as c:
        assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
        assert c.execute('SELECT must_change_password FROM users WHERE id=1').fetchone()[0] == 1
