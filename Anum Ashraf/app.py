# ============================================================
# IMPORTS
# ============================================================
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, session
from flask_login import LoginManager
import mysql.connector
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import random 
from flask_mail import Mail, Message
from mysql.connector import Error
from difflib import SequenceMatcher
import threading
import json
import re
from openai import OpenAI
import os
from dotenv import load_dotenv

# ============================================================
# FLASK APP SETUP (EK BAAR)
# ============================================================
load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# ============================================================
# OPENAI SETUP - API KEY YAHAN DALEN
# ============================================================
# Option 1: Directly yahan likhein (temporary)
client = OpenAI(api_key="YOUR_OPENAI_API_KEY_HERE")

# Option 2: .env file se (recommended)
# client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# ============================================================
# DATABASE CONFIGURATION (EK BAAR)
# ============================================================
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'YOUR_PASSWORD',
    'database': 'doctor_appointment_hub'
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

# ============================================================
# MAIL CONFIG
# ============================================================
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='YOUR_EMAIL_HERE',
    MAIL_PASSWORD='YOUR_APP_PASSWORD_HERE',
    MAIL_DEFAULT_SENDER=('Doctor Appointment Hub', 'YOUR_EMAIL_HERE')
)
mail = Mail(app)

def send_email(to_email, subject, body):
    msg = Message(subject, recipients=[to_email], body=body)
    mail.send(msg)

# ============================================================
# CREATE NOTIFICATION FUNCTION (INDENTATION FIXED)
# ============================================================
def create_notification(conn, appointment_id, user_email, subject, message, ntype="In-App"):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO notifications (
            appointment_id,
            user_email,
            type,
            subject,
            message,
            status
        ) VALUES (%s, %s, %s, %s, %s, %s)
    """, (appointment_id, user_email, ntype, subject, message, "Sent"))
    conn.commit()
    cursor.close()

# ============================================================
# ADMIN RATINGS PAGE
# ============================================================
@app.route('/admin/ratings')
def view_ratings():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT users.first_name AS user_name, ratings.rating, ratings.feedback
        FROM ratings
        JOIN users ON ratings.user_id = users.id
    """)
    ratings = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('ratings.html', ratings=ratings)

@app.route('/admin/notifications')
def admin_notifications():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT notification_id, appointment_id, user_email, type, subject, message, status, sent_at
        FROM notifications
        ORDER BY sent_at DESC
    """)
    notifications = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("admin_notifications.html", notifications=notifications)

# ============================================================
# ADD DOCTOR
# ============================================================
@app.route('/add_doctor', methods=['POST'])
def add_doctor():
    if request.method == 'POST':
        try:
            name = request.form['name']
            specialization = request.form['specialization']
            experience = request.form['experience']
            education = request.form['education']
            image_url = request.form.get('image_url', '')
            city = request.form['city']
            rating = request.form['rating']
            
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                INSERT INTO doctors (name, specialization, experience, education, image_url, city, rating)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (name, specialization, experience, education, image_url, city, rating))
            
            conn.commit()
            conn.close()
            return jsonify({'status': 'success', 'message': 'Doctor added successfully!'})
            
        except Exception as e:
            print(f"Error: {e}")
            return jsonify({'status': 'error', 'message': 'Something went wrong!'})

# ============================================================
# ADD USER
# ============================================================
@app.route('/add_user', methods=['POST'])
def add_user():
    if request.method == 'POST':
        try:
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            email = request.form['email']
            phone = request.form['phone']
            password = request.form['password']
            confirm_password = request.form['confirm_password']
            date_of_birth = request.form['date_of_birth']
            
            if password != confirm_password:
                return jsonify({'status': 'error', 'message': 'Passwords do not match!'})
            
            hashed_password = generate_password_hash(password)
            
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                conn.close()
                return jsonify({'status': 'error', 'message': 'Email already registered!'})
            
            cursor.execute("""
                INSERT INTO users (first_name, last_name, email, phone, password, date_of_birth)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (first_name, last_name, email, phone, hashed_password, date_of_birth))
            
            conn.commit()
            conn.close()
            return jsonify({'status': 'success', 'message': 'User added successfully!'})
            
        except Exception as e:
            print(f"Error: {e}")
            return jsonify({'status': 'error', 'message': 'Something went wrong!'})

# ============================================================
# SMART KEYWORD MAPPING (URDU + ENGLISH)
# ============================================================

SPECIFIC_DOCTORS = ['ophthalmologist', 'cardiologist', 'gynaecologist', 'neurologist',
                    'gastroenterologist', 'orthopedic', 'dentist', 'ent specialist', 
                    'psychiatrist', 'endocrinologist', 'urologist', 'pulmonologist', 
                    'oncologist', 'dermatologist', 'physiotherapist', 'radiologist', 'pediatrics']

GENERIC_DOCTORS = ['general physician']

KEYWORD_DOCTOR_MAP = {
    'ophthalmologist': ['eye', 'aankh', 'vision', 'blur', 'motia', 'nazar', 'cataract', 'eyesight'],
    'cardiologist': ['heart', 'dil', 'chest', 'bp', 'blood pressure', 'palpitations', 'cardio'],
    'gynaecologist': ['period', 'mahwari', 'pregnancy', 'hamal', 'pcos', 'pcod', 'breast', 'chati', 'women'],
    'neurologist': ['brain', 'dimag', 'headache', 'migraine', 'dizziness', 'chakkar', 'nerve', 'memory', 'seizure'],
    'gastroenterologist': ['stomach', 'pet', 'acidity', 'gas', 'liver', 'jigar', 'constipation', 'qabz', 'diarrhea', 'dast'],
    'orthopedic': ['bone', 'haddi', 'joint', 'jor', 'knee', 'ghutna', 'back', 'kamar', 'neck', 'gardan', 'arthritis'],
    'dermatologist': ['skin', 'jild', 'chamdi', 'acne', 'pimples', 'rash', 'dana', 'khujli', 'hair', 'bal'],
    'ent specialist': ['ear', 'kan', 'nose', 'naak', 'throat', 'gala', 'sinus', 'cold', 'nazla', 'hearing'],
    'dentist': ['tooth', 'daant', 'dant', 'teeth', 'gum', 'masura', 'toothache'],
    'psychiatrist': ['mental', 'depression', 'anxiety', 'stress', 'tension', 'insomnia', 'neend', 'pareshani', 'udasi'],
    'pulmonologist': ['lung', 'phephra', 'asthma', 'dam', 'breathing', 'saans', 'cough', 'khansi', 'pneumonia'],
    'urologist': ['urine', 'peshab', 'kidney', 'gurda', 'bladder', 'uti', 'prostate'],
    'oncologist': ['cancer', 'tumor', 'gilty', 'rasoli', 'kansa', 'chemotherapy'],
    'endocrinologist': ['diabetes', 'shakkar', 'sugar', 'thyroid', 'hormone', 'weight gain', 'weight loss'],
    'physiotherapist': ['physio', 'therapy', 'rehab', 'exercise', 'movement', 'physiotherapy'],
    'radiologist': ['xray', 'x-ray', 'ct scan', 'mri', 'ultrasound', 'sonography', 'scan'],
    'pediatrics': ['child', 'bacha', 'baby', 'kid', 'children', 'bachay', 'infant', 'toddler'],
    'general physician': ['fever', 'bukhar', 'weakness', 'kamzori', 'fatigue', 'thakan', 'general', 'body ache']
}

# ============================================================
# SMART KEYWORD MATCH FUNCTION
# ============================================================
def smart_keyword_match(symptoms_text):
    text_lower = symptoms_text.lower()
    matches = {}
    
    for doctor in SPECIFIC_DOCTORS:
        keywords = KEYWORD_DOCTOR_MAP.get(doctor, [])
        for keyword in keywords:
            if keyword in text_lower:
                matches[doctor] = matches.get(doctor, 0) + 1
        # Urdu special handling
        if doctor == 'orthopedic':
            for k in ['gutna', 'ghutna', 'knee', 'kamar dard', 'haddi']:
                if k in text_lower:
                    matches[doctor] = matches.get(doctor, 0) + 1
        if doctor == 'gynaecologist':
            for k in ['period', 'mahwari', 'pregnancy', 'hamal', 'pcos']:
                if k in text_lower:
                    matches[doctor] = matches.get(doctor, 0) + 1
    
    # General keywords
    for k in ['bukhar', 'fever', 'weakness', 'kamzori', 'body ache', 'jism dard', 'cold', 'nazla']:
        if k in text_lower:
            matches['general physician'] = matches.get('general physician', 0) + 1
    
    if not matches:
        return 'General Physician'
    
    # Priority order
    priority = ['oncologist', 'cardiologist', 'neurologist', 'psychiatrist', 'dermatologist', 
                'orthopedic', 'gynaecologist', 'gastroenterologist', 'pulmonologist', 'urologist',
                'ophthalmologist', 'ent specialist', 'dentist', 'endocrinologist', 'pediatrics',
                'physiotherapist', 'radiologist', 'general physician']
    
    best_doctor = max(matches, key=matches.get)
    best_score = matches[best_doctor]
    tied = [d for d, s in matches.items() if s == best_score]
    
    if len(tied) > 1:
        for p in priority:
            if p in tied:
                return p.title()
    return best_doctor.title()

def get_recommended_doctors(specializations):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if isinstance(specializations, str):
            specializations = [specializations]
        placeholders = ', '.join(['%s'] * len(specializations))
        query = f"""
            SELECT DISTINCT id, name, specialization, experience, education, image_url, city, rating
            FROM doctors 
            WHERE specialization IN ({placeholders})
            LIMIT 5
        """
        cursor.execute(query, specializations)
        doctors = cursor.fetchall()
        cursor.close()
        conn.close()
        return doctors
    except Exception as e:
        print(f"Doctor error: {e}")
        return []
    

def emergency_check(symptoms_text):
    text_lower = symptoms_text.lower()
    emergency_map = {
        'cancer': 'Oncologist',
        'tumor': 'Oncologist',
        'chest pain': 'Cardiologist',
        'heart attack': 'Cardiologist',
        'difficulty breathing': 'Emergency Care',
        'severe bleeding': 'Emergency Care',
        'unconscious': 'Emergency Care'
    }
    for keyword, doctor in emergency_map.items():
        if keyword in text_lower:
            return doctor
    return None
# ============================================================
# DATABASE INITIALIZATION
# ============================================================
def init_database():
    try:
        conn = mysql.connector.connect(host='localhost', user='root', password='YOUR_PASSWORD_HERE')
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS doctor_appointment_hub")
        cursor.close()
        conn.close()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY, first_name VARCHAR(100), last_name VARCHAR(100),
            email VARCHAR(255) UNIQUE, phone VARCHAR(20), password VARCHAR(255),
            role ENUM('admin','user') DEFAULT 'user', date_of_birth DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS doctors (
            id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255), specialization VARCHAR(255),
            experience VARCHAR(100), education TEXT, image_url VARCHAR(500), email VARCHAR(255),
            password VARCHAR(255), phone VARCHAR(20), city VARCHAR(100), rating DECIMAL(2,1)
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS appointments (
            id INT AUTO_INCREMENT PRIMARY KEY, doctor_id INT, doctor_name VARCHAR(255),
            specialization VARCHAR(255), patient_name VARCHAR(255), email VARCHAR(255),
            message TEXT, appointment_date DATE, appointment_time TIME, status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS ratings (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT, rating INT, feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS contact_messages (
            id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255), email VARCHAR(255),
            phone VARCHAR(20), subject VARCHAR(255), department VARCHAR(255), message TEXT,
            user_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS payments (
            payment_id INT AUTO_INCREMENT PRIMARY KEY, appointment_id INT, amount DECIMAL(10,2),
            payment_status VARCHAR(50), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS notifications (
            notification_id INT AUTO_INCREMENT PRIMARY KEY, appointment_id INT,
            user_email VARCHAR(255), type VARCHAR(50), subject VARCHAR(255), message TEXT,
            status VARCHAR(50), sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
            id INT AUTO_INCREMENT PRIMARY KEY, email VARCHAR(255) UNIQUE,
            password VARCHAR(255), full_name VARCHAR(255)
        )''')
        
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database initialized successfully!")
    except Exception as e:
        print(f"❌ DB init error: {e}")

# ============================================================
# DECORATORS
# ============================================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session and 'admin_id' not in session and 'doctor_id' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('actor'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================================
# ROUTES
# ============================================================

@app.route('/')
def welcome():
    return render_template('welcome.html')

@app.route('/home')
@login_required
def home():
    return render_template('index.html')

@app.route('/actor')
def actor():
    return render_template('actor.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        password = request.form.get('password','')
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cursor.fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session['role'] = 'user'
                session['first_name'] = user.get('first_name', '')
                session['last_name'] = user.get('last_name', '')
                flash("Login successful!", "success")
                return redirect(url_for('home'))
            else:
                flash("Invalid credentials!", "danger")
        except Exception as e:
            print("Login error:", e)
            flash("Something went wrong.", "danger")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()
    return render_template("login.html")

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        first_name = request.form.get('first_name','').strip()
        last_name = request.form.get('last_name','').strip()
        email = request.form.get('email','').strip()
        phone = request.form.get('phone','').strip()
        password = request.form.get('password','')
        confirm = request.form.get('confirm_password','')
        dob = request.form.get('dob','')
        
        if not all([first_name, last_name, email, phone, password, confirm, dob]):
            flash("All fields required!", "error")
            return render_template("signup.html")
        if password != confirm:
            flash("Passwords do not match!", "error")
            return render_template("signup.html")
        if len(password) < 6:
            flash("Password too short!", "error")
            return render_template("signup.html")
        
        hashed = generate_password_hash(password)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (first_name, last_name, email, phone, password_hash, date_of_birth) VALUES (%s,%s,%s,%s,%s,%s)",
                           (first_name, last_name, email, phone, hashed, dob))
            conn.commit()
            flash("Account created! Please login.", "success")
            return redirect(url_for('login'))
        except mysql.connector.IntegrityError:
            flash("Email already exists!", "error")
        except Exception as e:
            print(e)
            flash("Error creating account.", "error")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()
    return render_template("signup.html")

@app.route('/admin_login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM admins WHERE email=%s", (email,))
        admin = cursor.fetchone()
        cursor.close()
        conn.close()
        if admin and check_password_hash(admin['password_hash'], password):
            session.clear()
            session['admin_id'] = admin['id']
            session['role'] = 'admin'
            flash("Admin login successful", "success")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid admin credentials", "danger")
    return render_template("admin_login.html")

@app.route('/doctor-login', methods=['GET','POST'])
def doctor_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM doctors WHERE email = %s", (email,))
        doctor = cursor.fetchone()
        cursor.close()
        conn.close()
        
        # ✅ Direct compare (no hash checking)
        if doctor and doctor['password_hash'] == password:
            session.clear()
            session['doctor_id'] = doctor['id']
            session['doctor_name'] = doctor['name']
            session['role'] = 'doctor'
            flash(f'Welcome Dr. {doctor["name"]}!', 'success')
            return redirect(url_for('doctor_dashboard'))
        else:
            flash('Invalid credentials.', 'error')
    
    return render_template('doctor_login.html')
@app.route('/doctor/register', methods=['GET', 'POST'])
def doctor_register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        specialization = request.form.get('specialization')
        phone = request.form.get('phone')
        password = request.form.get('password')
        hashed = generate_password_hash(password)
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM doctors WHERE email = %s", (email,))
            if cursor.fetchone():
                flash("Email already exists!", "error")
                return redirect(url_for('doctor_register'))
            cursor.execute("SELECT id FROM doctors WHERE name = %s AND specialization = %s", (name, specialization))
            if cursor.fetchone():
                flash(f"Doctor '{name}' with specialization '{specialization}' already exists!", "error")
                return redirect(url_for('doctor_register'))
            cursor.execute("INSERT INTO doctors (name, email, specialization, phone, password, rating) VALUES (%s, %s, %s, %s, %s, 4.0)",
                           (name, email, specialization, phone, hashed))
            conn.commit()
            flash("Registration successful! Please login.", "success")
            return redirect(url_for('doctor_login'))
        except Exception as e:
            print(f"Registration error: {e}")
            flash("Something went wrong. Please try again.", "error")
        finally:
            cursor.close()
            conn.close()
    return render_template('doctor_register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('welcome'))

@app.route('/rate', methods=['GET','POST'])
@login_required
def rate():
    if request.method == 'POST':
        rating = request.form.get('rating')
        feedback = request.form.get('feedback', '').strip()
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO ratings (user_id, rating, feedback) VALUES (%s,%s,%s)",
                           (session.get('user_id'), rating, feedback))
            conn.commit()
            flash('Thank you for your feedback!', 'success')
        except Exception as e:
            print(e)
            flash('Error saving rating.', 'error')
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()
        flash('Thank you for rating!', 'success')
        return redirect(url_for('home'))
    return render_template('rating.html')

# ============================================================
# ADMIN DASHBOARD
# ============================================================
@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("Admin access required.", "warning")
        return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    cursor.execute("SELECT * FROM appointments")
    appointments = cursor.fetchall()
    cursor.execute("SELECT * FROM doctors")
    doctors = cursor.fetchall()
    cursor.execute("SELECT * FROM contact_messages ORDER BY id DESC")
    messages = cursor.fetchall()
    cursor.execute("SELECT * FROM ratings ORDER BY id DESC")
    ratings = cursor.fetchall()
    cursor.execute("SELECT * FROM payments ORDER BY payment_id DESC")
    payments = cursor.fetchall()
    cursor.execute("SELECT * FROM notifications ORDER BY notification_id DESC")
    notifications = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("admin_dashboard.html", users=users, appointments=appointments,
                          doctors=doctors, ratings=ratings, payments=payments,
                          messages=messages, notifications=notifications)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if session.get('role') != 'admin':
        flash("Admin access required.", "warning")
        return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash("User deleted successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_doctor/<int:doctor_id>', methods=['POST'])
def delete_doctor(doctor_id):
    if session.get('role') != 'admin':
        flash("Admin access required.", "warning")
        return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM doctors WHERE id = %s", (doctor_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash("Doctor deleted successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_appointment/<int:appointment_id>', methods=['POST'])
def delete_appointment(appointment_id):
    if session.get('role') != 'admin':
        flash("Admin access required.", "warning")
        return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM payments WHERE appointment_id = %s", (appointment_id,))
    cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash("Appointment deleted successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/edit_appointment/<int:appointment_id>', methods=['GET', 'POST'])
@login_required
def edit_appointment(appointment_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if request.method == 'POST':
        new_date = request.form.get('appointment_date')
        new_time = request.form.get('appointment_time')
        new_message = request.form.get('message')
        cursor.execute("UPDATE appointments SET appointment_date=%s, appointment_time=%s, message=%s WHERE id=%s",
                       (new_date, new_time, new_message, appointment_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Appointment updated successfully!", "success")
        return redirect(url_for('admin_dashboard'))
    cursor.execute("SELECT * FROM appointments WHERE id=%s", (appointment_id,))
    appointment = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('edit_appointment.html', appointment=appointment)
@app.route('/admin/edit_user/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    if session.get('role') != 'admin':
        flash("Admin access required.", "warning")
        return redirect(url_for('admin_login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        
        cursor.execute("""
            UPDATE users SET first_name=%s, last_name=%s, email=%s, phone=%s 
            WHERE id=%s
        """, (first_name, last_name, email, phone, user_id))
        conn.commit()
        flash("User updated successfully!", "success")
        cursor.close()
        conn.close()
        return redirect(url_for('admin_dashboard'))
    
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return render_template('edit_user.html', user=user)

# ============================================================
# SYMPTOM CHECKER
# ============================================================
@app.route('/symptom-checker')
def symptom_checker_page():
    return render_template('symptom_checker.html')

@app.route('/api/check-symptoms', methods=['POST'])
def symptom_checker_api():
    data = request.get_json()
    user_symptoms = data.get("symptoms_text", "").strip()
    
    if not user_symptoms:
        return jsonify({"success": False, "error": "Please enter your symptoms"})
    
    # ============================================================
    # TRY 1: OPENAI AI (Primary)
    # ============================================================
    try:
        system_prompt = """
        You are a medical symptom analyzer. Analyze the user's symptoms and return ONLY JSON format.
        
        Rules:
        1. Identify the most likely doctor specialization from this list:
           Cardiologist, Dermatologist, Neurologist, Orthopedic, Gynaecologist, 
           Gastroenterologist, Pulmonologist, Ophthalmologist, ENT Specialist, 
           Dentist, Urologist, Psychiatrist, Endocrinologist, Oncologist, 
           Pediatrics, Physiotherapist, Radiologist, General Physician
        
        2. Give a confidence score (0-100)
        3. Explain the reasoning briefly in simple language (Urdu or English)
        4. Add emergency advice if needed (chest pain, severe bleeding, unconsciousness, difficulty breathing)
        
        Return ONLY this JSON format:
        {
            "specialization": "Doctor name here",
            "confidence": 85,
            "reasoning": "Brief explanation",
            "emergency": false,
            "emergency_advice": null
        }
        """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Symptoms: {user_symptoms}"}
            ],
            temperature=0.3,
            max_tokens=300,
            timeout=10  # 10 seconds timeout
        )
        
        ai_response = response.choices[0].message.content
        print("🤖 AI Response:", ai_response)
        
        # Clean JSON
        ai_response = ai_response.strip()
        if ai_response.startswith('```json'):
            ai_response = ai_response[7:]
        if ai_response.startswith('```'):
            ai_response = ai_response[3:]
        if ai_response.endswith('```'):
            ai_response = ai_response[:-3]
        ai_response = ai_response.strip()
        
        result = json.loads(ai_response)
        
        specialization = result.get('specialization', 'General Physician')
        confidence = result.get('confidence', 70)
        reasoning = result.get('reasoning', 'AI analysis complete')
        is_emergency = result.get('emergency', False)
        emergency_advice = result.get('emergency_advice', None)
        
        # Check confidence score
        if confidence >= 60:
            # AI confident enough - use AI result
            print("✅ AI Result with high confidence")
            use_ai = True
        else:
            print("⚠️ AI confidence too low, switching to keyword matching")
            use_ai = False
            
    except Exception as e:
        print("⚠️ OpenAI Error:", e)
        use_ai = False
    
    # ============================================================
    # FALLBACK 2: KEYWORD MATCHING (if AI fails or low confidence)
    # ============================================================
    if not use_ai:
        print("🔄 Using Keyword Matching as Fallback")
        specialization = smart_keyword_match(user_symptoms)
        confidence = 65
        reasoning = "Based on keyword analysis (AI service temporarily unavailable)."
        is_emergency = emergency_check(user_symptoms) is not None
        emergency_advice = "Please consult doctor immediately" if is_emergency else None
    
    # ============================================================
    # GET DOCTORS FROM DATABASE
    # ============================================================
    doctors = get_recommended_doctors(specialization)
    
    # Final fallback if no doctors found
    if not doctors:
        doctors = get_recommended_doctors('General Physician')
        if not doctors:
            doctors = []
            specialization = "General Physician"
    
    return jsonify({
        "success": True,
        "analysis": {
            "specialization": specialization,
            "confidence": confidence,
            "reasoning": reasoning,
            "emergency": is_emergency,
            "emergency_advice": emergency_advice,
            "source": "AI" if use_ai else "Keyword Matching"  # tells user which system was used
        },
        "recommended_doctors": doctors
    })
@app.route('/book-ai-appointment', methods=['POST'])
@login_required
def book_ai_appointment():
    try:
        data = request.get_json()
        doctor_id = data.get('doctor_id')
        doctor_name = data.get('doctor_name')
        specialization = data.get('specialization')
        appointment_date = data.get('appointment_date')
        appointment_time = data.get('appointment_time')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO appointments (doctor_id, doctor_name, specialization, patient_name, email, appointment_date, appointment_time, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        """, (doctor_id, doctor_name, specialization, 
              session.get('first_name') + ' ' + session.get('last_name'),
              session.get('email'), appointment_date, appointment_time))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({"success": True, "message": "Appointment booked!"})
        
    except Exception as e:
        print("Error:", e)
        return jsonify({"success": False, "message": str(e)})
    
# ============================================================
# APPOINTMENT
# ============================================================
@app.route('/appointment', methods=['GET', 'POST'])
@login_required
def appointment():
    confirmation_data = session.pop('confirmation_data', None)
    if request.method == 'POST':
        try:
            doctor_id = request.form.get('doctor_id')
            doctor_name = request.form.get('doctor_name')
            specialization = request.form.get('specialization')
            patient_name = request.form.get('patient_name')
            email = request.form.get('email')
            message = request.form.get('message')
            date = request.form.get('appointment_date')
            time = request.form.get('appointment_time')
            amount = 2500
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO appointments (doctor_id, doctor_name, specialization, patient_name, email, message, appointment_date, appointment_time, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (doctor_id, doctor_name, specialization, patient_name, email, message, date, time, "pending"))
            appt_id = cursor.lastrowid
            cursor.execute("INSERT INTO payments (appointment_id, amount, payment_status) VALUES (%s,%s,%s)",
                           (appt_id, amount, "Completed"))
            conn.commit()
            
            # ✅ ✅ ✅ EMAIL SEND CODE - YEH ADD KARO ✅ ✅ ✅
            try:
                msg = Message(
                    subject="Appointment Confirmation - Doctor Appointment Hub",
                    recipients=[email]
                )
                msg.body = f"""
Dear {patient_name},

Your appointment has been successfully booked!

Appointment Details:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Doctor: Dr. {doctor_name}
• Specialization: {specialization}
• Date: {date}
• Time: {time}
• Patient: {patient_name}
• Email: {email}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Payment ID: {appt_id}
Amount: Rs. {amount}
Payment Status: Cash

Thank you for choosing Doctor Appointment Hub!
"""
                mail.send(msg)
                print(f"✅ Email sent successfully to {email}")
            except Exception as e:
                print(f"❌ Email error: {e}")
            
            cursor.close()
            conn.close()
            
            session['confirmation_data'] = {
                "appointment_id": appt_id, "patient_name": patient_name, "doctor_name": doctor_name,
                "specialization": specialization, "email": email, "appointment_date": date,
                "appointment_time": time, "message": message, "payment_status": "Completed"
            }
            flash("Appointment booked successfully!", "success")
            return redirect(url_for('appointment'))
        except Exception as e:
            print("ERROR:", e)
            flash("Something went wrong!", "danger")
    return render_template("appointment.html", confirmation_data=confirmation_data)
@app.route('/appointments')
@login_required
def view_appointments():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM appointments ORDER BY created_at DESC")
    appointments = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('view_appointments.html', appointments=appointments)

@app.route('/cancel-appointment/<int:appointment_id>', methods=['POST'])
@login_required
def cancel_appointment(appointment_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM payments WHERE appointment_id = %s", (appointment_id,))
        cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True, "message": "Appointment deleted successfully!"})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "message": str(e)})

# ============================================================
# DOCTOR DASHBOARD
# ============================================================
@app.route("/doctor-dashboard")
def doctor_dashboard():
    if 'doctor_id' not in session:
        return redirect(url_for('doctor_login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    doctor_id = session['doctor_id']
    doctor_name = session.get('doctor_name', '')
    
    cursor.execute("SELECT * FROM doctors WHERE id=%s", (doctor_id,))
    doctor = cursor.fetchone()
    
    cursor.execute("""
        SELECT * FROM appointments 
        WHERE doctor_id = %s OR doctor_name = %s 
        ORDER BY appointment_date DESC
    """, (doctor_id, doctor_name))
    appointments = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) AS total FROM appointments WHERE doctor_id=%s", (doctor_id,))
    total = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) AS accepted FROM appointments WHERE doctor_id=%s AND status='accepted'", (doctor_id,))
    accepted = cursor.fetchone()['accepted']
    
    cursor.execute("SELECT COUNT(*) AS rejected FROM appointments WHERE doctor_id=%s AND status='rejected'", (doctor_id,))
    rejected = cursor.fetchone()['rejected']
    
    cursor.close()
    conn.close()
    
    return render_template("doctor_dashboard.html", doctor=doctor, appointments=appointments,
                          total=total, accepted=accepted, rejected=rejected)

@app.route("/accept/<int:id>")
def accept_appointment(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM appointments WHERE id=%s", (id,))
    appt = cursor.fetchone()
    cursor.execute("UPDATE appointments SET status='accepted' WHERE id=%s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    send_email(appt['email'], "Appointment Accepted", f"Your appointment with {appt['doctor_name']} is ACCEPTED.")
    flash("Appointment ACCEPTED & Email sent 📩", "success")
    return redirect(url_for("doctor_dashboard"))

@app.route("/reject/<int:id>")
def reject_appointment(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM appointments WHERE id=%s", (id,))
    appt = cursor.fetchone()
    cursor.execute("UPDATE appointments SET status='rejected' WHERE id=%s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    send_email(appt['email'], "Appointment Rejected", f"Your appointment with {appt['doctor_name']} is REJECTED.")
    flash("Appointment REJECTED & Email sent 📩", "danger")
    return redirect(url_for("doctor_dashboard"))

@app.route('/doctor-profile')
def doctor_profile():
    if 'doctor_id' not in session:
        return redirect('/doctor-login')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM doctors WHERE id=%s", (session['doctor_id'],))
    doctor = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('doctor_profile.html', doctor=doctor)

@app.route('/doctor-profile-edit', methods=['GET', 'POST'])
def doctor_profile_edit():
    if 'doctor_id' not in session:
        return redirect('/doctor-login')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    doctor_id = session['doctor_id']
    cursor.execute("SELECT * FROM doctors WHERE id=%s", (doctor_id,))
    doctor = cursor.fetchone()
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        specialization = request.form.get('specialization')
        experience = request.form.get('experience')
        education = request.form.get('education')
        city = request.form.get('city')
        rating = request.form.get('rating')
        cursor.execute("UPDATE doctors SET name=%s, email=%s, password=%s, specialization=%s, experience=%s, education=%s, city=%s, rating=%s WHERE id=%s",
                       (name, email, password, specialization, experience, education, city, rating, doctor_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Profile updated successfully!", "success")
        return redirect('/doctor-dashboard')
    cursor.close()
    conn.close()
    return render_template('doctor_profile_edit.html', doctor=doctor)

@app.route("/doctor-view-users")
def doctor_view_users():
    if 'doctor_id' not in session:
        return redirect('/doctor-login')
    doctor_id = session['doctor_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT DISTINCT u.id, u.first_name, u.last_name, u.email, u.phone, u.date_of_birth, u.created_at, u.role
        FROM users u INNER JOIN appointments a ON u.email = a.email WHERE a.doctor_id = %s
    """, (doctor_id,))
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("view_users.html", users=users)

# ============================================================
# OTHER ROUTES
# ============================================================
@app.route('/doctors')
@login_required
def doctors():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, specialization, experience, education, city, rating FROM doctors")
    doctors_list = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('find_doctor.html', doctors=doctors_list)

@app.route('/contact', methods=['GET', 'POST'])
@login_required
def contact():
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            subject = request.form.get('subject')
            department = request.form.get('department')
            message = request.form.get('message')
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO contact_messages (name, email, phone, subject, department, message, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                           (name, email, phone, subject, department, message, session.get('user_id')))
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"success": True})
        except Exception as e:
            print("ERROR:", e)
            return jsonify({"success": False})
    return render_template('contact.html')

@app.route('/about')
@login_required
def about():
    return render_template('about.html')

@app.route('/services')
@login_required
def services():
    return render_template('services.html')

@app.route('/profile')
@login_required
def profile():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT first_name, last_name, email, phone, date_of_birth FROM users WHERE id=%s", (session.get('user_id'),))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('profile.html', user=user)

@app.route('/edit-profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
    user = cursor.fetchone()
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        cursor.execute("UPDATE users SET first_name=%s, last_name=%s, email=%s WHERE id=%s",
                       (first_name, last_name, email, session['user_id']))
        conn.commit()
        session['first_name'] = first_name
        session['last_name'] = last_name
        flash("Profile updated successfully!", "success")
        return render_template("edit_profile.html", user=user, update_success=True)
    cursor.close()
    conn.close()
    return render_template("edit_profile.html", user=user)

@app.route('/edit-doctor/<int:doctor_id>', methods=['GET', 'POST'])
def edit_doctor(doctor_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM doctors WHERE id=%s", (doctor_id,))
    doctor = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('edit_doctor.html', doctor=doctor)

@app.route('/user/<int:user_id>')
def view_user_profile(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return render_template('user_profile.html', user=user)
@app.route('/doctor/view/<int:doctor_id>')
def view_doctor_profile(doctor_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM doctors WHERE id = %s", (doctor_id,))
    doctor = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not doctor:
        return "Doctor not found", 404
    
    return render_template('view_doctor_profile.html', doctor=doctor)
# ============================================================
# RUN APP
# ============================================================
if __name__ == '__main__':
    init_database()
    app.run(debug=True)