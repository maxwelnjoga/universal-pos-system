# Universal POS – Backend (Django REST API)

Runs on its own. The React frontend is a separate project (`universal-frontend`) that connects through the API.

## Setup (Python 3.12)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
```

Link your user to a business (once):

```powershell
python manage.py shell -c "from django.contrib.auth import get_user_model as g; from businesses.models import *; u=g().objects.get(username='YOUR_USERNAME'); b=Business.objects.first() or Business.objects.create(name='My Shop'); Branch.objects.get_or_create(business=b, code='MN', defaults={'name':'Main'}); Membership.objects.get_or_create(user=u, business=b, defaults={'role':'owner'}); print('Done')"
```

## Run

```powershell
python manage.py runserver        # http://127.0.0.1:8000
```

- `/` and `/api/` – API index (JSON)
- `/admin/` – Django admin
- `/api/auth/login/` – returns a token used by the frontend (`Authorization: Token <key>`)

## Connecting a frontend

CORS already allows `http://localhost:5173` and `http://127.0.0.1:5173` (the frontend dev server).
For a deployed frontend, set its URL before starting Django:

```powershell
$env:FRONTEND_ORIGINS="https://pos.example.com"     # PowerShell
# export FRONTEND_ORIGINS=https://pos.example.com   # Linux/macOS
```
(comma-separate several). Also add your backend domain to `ALLOWED_HOSTS`, set `DEBUG=False` and a real `SECRET_KEY`
for production, then run with `gunicorn universal_pos.wsgi`.
