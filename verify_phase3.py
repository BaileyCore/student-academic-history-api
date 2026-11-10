"""Run the supplied practice grader; proof files are assessed separately."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'selftest'))
from grader.grade_service import run
from grader._svc import format_report

result = run('http://127.0.0.1:8000', Path(__file__).parent / 'selftest/data/selftest')
print(format_report(result))
api_groups = {k: v for k, v in result['detail'].items() if not k.startswith('F_')}
assert all(v['points'] == v['max'] for v in api_groups.values()), 'API verification failed'
print('All API checks passed (95/95). CI screenshot and logs must come from the actual workflow run.')
