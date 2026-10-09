"""Smoke tests: python test_local.py (requires httpx)."""
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from main import app, parse_transcript

html = b'''<html><table><tr><th>Status</th><th>Course</th><th>Title</th><th>Grade</th><th>Term</th><th>Credits</th></tr>
<tr><td>Completed</td><td>COSC-1046</td><td>Programming</td><td>P</td><td>23F</td><td>3</td></tr>
<tr><td>Completed</td><td>COSC-1046</td><td>Programming</td><td>86</td><td>23F</td><td>3</td></tr>
<tr><td>Attempted</td><td>COSC-1046L</td><td>Lab</td><td>F</td><td>23F</td><td></td></tr>
<tr><td>Planned</td><td>COSC-2006</td><td>Later</td><td></td><td>25F</td><td>3</td></tr>
<tr><td>Completed</td><td>OTHER</td><td>Empty term</td><td>A</td><td></td><td>3</td></tr></table></html>'''

with TestClient(app) as c:
    base = '/api/v1/students'
    assert c.get(f'{base}/none/profile').status_code == 404
    assert c.put(f'{base}/none/history', json={'history': []}).status_code == 404
    assert c.post(f'{base}/none/plan', json={'planned_courses': []}).status_code == 404
    def do_import(student_id):
        return c.post(f'{base}/{student_id}/history/import', files={'file': ('transcript.html', html, 'text/html')})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(do_import, ('a', 'b')))
    assert [r.status_code for r in results] == [201, 201]
    assert [r.json()['past_courses_imported'] for r in results] == [2, 2]
    assert c.post(f'{base}/a/plan', json={'planned_courses': [{'course_code': 'COSC-3506', 'term': '26F'}]}).status_code == 200
    a = c.get(f'{base}/a/profile').json()
    b = c.get(f'{base}/b/profile').json()
    assert set(a) == {'student_id', 'history', 'plan'}
    assert len(a['history']) == 2 and len(a['plan']) == 1
    assert len(b['history']) == 2 and b['plan'] == []
    assert next(x for x in a['history'] if x['course_code'] == 'COSC-1046L')['credits_earned'] == 0
    assert c.put(f'{base}/a/history', json={'history': []}).status_code == 200
    assert c.get(f'{base}/a/profile').json()['history'] == []
    assert len(c.get(f'{base}/b/profile').json()['history']) == 2
    assert c.put(f'{base}/a/plan', json={'planned_courses': []}).status_code == 200
    assert c.delete(f'{base}/a/plan').status_code == 200
    assert c.delete(f'{base}/a/history').status_code == 200
    assert c.get(f'{base}/a/plan').status_code in (404, 405)
    print('All local smoke tests passed.')
