import requests, json
session = requests.Session()
login_url = 'http://localhost:8088/api/v1/security/login'
r = session.post(login_url, json={'username': 'admin', 'password': 'admin', 'provider': 'db'})
access_token = r.json().get('access_token')
session.headers.update({'Authorization': f'Bearer {access_token}'})
csrf_url = 'http://localhost:8088/api/v1/security/csrf_token/'
csrf_token = session.get(csrf_url).json().get('result')
session.headers.update({'X-CSRFToken': csrf_token})

# Delete all dashboards
dashes = session.get('http://localhost:8088/api/v1/dashboard/').json().get('result', [])
for d in dashes:
    session.delete(f"http://localhost:8088/api/v1/dashboard/{d['id']}")

# Delete all charts
charts = session.get('http://localhost:8088/api/v1/chart/').json().get('result', [])
for c in charts:
    session.delete(f"http://localhost:8088/api/v1/chart/{c['id']}")
