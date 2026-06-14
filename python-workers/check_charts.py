import requests, json

session = requests.Session()
login_url = 'http://localhost:8088/api/v1/security/login'
r = session.post(login_url, json={'username': 'admin', 'password': 'admin', 'provider': 'db'})
access_token = r.json().get('access_token')
session.headers.update({'Authorization': f'Bearer {access_token}'})
csrf_url = 'http://localhost:8088/api/v1/security/csrf_token/'
csrf_token = session.get(csrf_url).json().get('result')
session.headers.update({'X-CSRFToken': csrf_token})

res = session.get('http://localhost:8088/api/v1/chart/')
charts = res.json().get('result', [])
for c in charts:
    print(f"Chart ID: {c.get('id')}, Name: {c.get('slice_name')}, Dataset ID: {c.get('datasource_id')}")
