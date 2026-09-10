import pathlib

auth_path = pathlib.Path('backend/tests/test_auth.py')
companies_path = pathlib.Path('backend/tests/test_companies.py')

# strip everything before the first class from test_auth.py
auth_text = auth_path.read_text(encoding='utf-8')
idx = auth_text.index('class TestRegister:')
header = '"""Phase 2 Authentication Tests - test DB provided by conftest.py"""\n\n'
auth_path.write_text(header + auth_text[idx:], encoding='utf-8')
print('cleaned test_auth.py')

# strip everything before helpers from test_companies.py
comp_text = companies_path.read_text(encoding='utf-8')
idx = comp_text.index('# -- Helper functions')
header = '"""Phase 3 Company tests - test DB provided by conftest.py"""\n\n'
companies_path.write_text(header + comp_text[idx:], encoding='utf-8')
print('cleaned test_companies.py')
