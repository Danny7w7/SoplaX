# Adult Content Platform (SoplaX)

A lightweight adult content platform built with **Django** and styled using **Bootstrap**.  
The platform delivers videos hosted on **AWS S3**. Third-party advertising is paused.

---

## 🚀 Features

- **Django Backend** for content management and routing.  
- **Bootstrap UI** for a simple, responsive front-end.  
- **Video Hosting with AWS S3** for scalable and secure storage.  
- **Email verification and password recovery** with expiring links.
- **Lightweight Architecture** designed for easy deployment and maintenance.  

---

## 🛠️ Tech Stack

- **Backend**: Django (Python)  
- **Frontend**: HTML, CSS, Bootstrap  
- **Storage**: AWS S3  
- **Database**: SQLite (development) / MySQL (production)  

---

## 📦 Installation (Basic Setup)

Use Python 3.14.

```bash
# Clone the repository
git clone https://github.com/Danny7w7/SoplaX.git
cd SoplaX

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
```

On Windows, activate it with `.\venv\Scripts\Activate.ps1` in PowerShell.

```bash
pip install -r requirements.txt
```

Set `DJANGO_ENV=development` in your untracked `.env` and generate a value for `DJANGO_SECRET_KEY`.

```bash
python -c "from secrets import token_urlsafe; print(token_urlsafe(64))"
```

```bash
python manage.py migrate
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

The development profile uses SQLite, local media files and console email. Check the terminal running Django for registration and recovery links. `DJANGO_SQLITE_PATH` can point to a separate SQLite database when validating changes.

See [Deploying SoplaX with Docker](DEPLOYMENT.md) for production configuration and how to prepare a copy of an existing MySQL database.
