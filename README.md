# Adult Content Platform (SoplaX)

A lightweight adult content platform built with **Django** and styled using **Bootstrap**.  
The platform delivers videos hosted on **AWS S3** and integrates **ExoClick** for advertising and monetization.  

---

## 🚀 Features

- **Django Backend** for content management and routing.  
- **Bootstrap UI** for a simple, responsive front-end.  
- **Video Hosting with AWS S3** for scalable and secure storage.  
- **ExoClick Advertising Integration** for revenue generation.  
- **Lightweight Architecture** designed for easy deployment and maintenance.  

---

## 🛠️ Tech Stack

- **Backend**: Django (Python)  
- **Frontend**: HTML, CSS, Bootstrap  
- **Storage**: AWS S3  
- **Advertising**: ExoClick  
- **Database**: SQLite (development) / MySQL (production)  

---

## 📦 Installation (Basic Setup)

```bash
# Clone the repository
git clone https://github.com/Danny7w7/SoplaX.git
cd SoplaX

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Start development server
python manage.py runserver
