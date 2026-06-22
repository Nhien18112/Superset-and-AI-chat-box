import requests

session = requests.Session()
login_url = 'http://localhost:8088/api/v1/security/login'
res = session.post(login_url, json={'username': 'admin', 'password': 'admin', 'provider': 'db'})
access_token = res.json().get('access_token')
session.headers.update({'Authorization': f'Bearer {access_token}'})
csrf_res = session.get('http://localhost:8088/api/v1/security/csrf_token/')
session.headers.update({'X-CSRFToken': csrf_res.json().get('result')})

roles_res = session.get('http://localhost:8088/api/v1/security/roles/?q={"filters":[{"col":"name","opr":"eq","value":"Gamma"}]}')
gamma_role = roles_res.json()['result'][0]

print("Gamma Permissions:")
for p in gamma_role['permissions']:
    if 'datasource' in p['permission']['name'].lower() or 'database' in p['permission']['name'].lower() or 'fact_orders' in p['view_menu']['name'].lower() or 'vdt_db' in p['view_menu']['name'].lower():
        print(f"{p['permission']['name']} on {p['view_menu']['name']}")
