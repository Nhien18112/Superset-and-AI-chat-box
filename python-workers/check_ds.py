import requests, json

session = requests.Session()
login_url = 'http://localhost:8088/api/v1/security/login'
r = session.post(login_url, json={'username': 'admin', 'password': 'admin', 'provider': 'db'})
access_token = r.json().get('access_token')
session.headers.update({'Authorization': f'Bearer {access_token}'})

dataset_url = 'http://localhost:8088/api/v1/dataset/'
res = session.get(dataset_url)
datasets = res.json().get('result', [])

if datasets:
    for ds in datasets:
        print('ID:', ds['id'], '| Table Name:', ds['table_name'])
else:
    print('NO DATASETS FOUND. You need to add the PostgreSQL table as a Dataset first!')
