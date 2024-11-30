from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this to a secure secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
db = SQLAlchemy(app)

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    creation_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)
    reminder_start_date = db.Column(db.DateTime, nullable=False)
    email_content = db.Column(db.Text, nullable=False)
    is_complete = db.Column(db.Boolean, default=False)

class TaskRecipient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Email Configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "mmea072@gmail.com"  # Replace with your email
SMTP_PASSWORD = "iszvdwevdrkbvipj"   # Replace with your app password

# Initialize scheduler
scheduler = BackgroundScheduler(timezone=pytz.timezone('Africa/Cairo'))
scheduler.start()

def send_email(recipient_email, subject, content):
    msg = MIMEMultipart()
    msg['From'] = SMTP_SERVER
    msg['To'] = recipient_email
    msg['Subject'] = subject
    msg.attach(MIMEText(content, 'plain'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def schedule_reminder_emails(task_id):
    task = Task.query.get(task_id)
    recipients = TaskRecipient.query.filter_by(task_id=task_id).all()
    
    current_date = task.reminder_start_date
    while current_date <= task.end_date:
        for hour in range(8, 21, 2):  # 8 AM to 8 PM, every 2 hours
            email_time = current_date.replace(hour=hour, minute=0)
            if email_time > datetime.now():
                for recipient in recipients:
                    user = User.query.get(recipient.user_id)
                    scheduler.add_job(
                        send_email,
                        'date',
                        run_date=email_time,
                        args=[user.email, f"Reminder: {task.name}", task.email_content]
                    )
        current_date += timedelta(days=1)

def send_initial_task_notification(task, recipients):
    subject = f"New Task Assigned: {task.name}"
    content = f"""
Hello,

You have been assigned a new task:

Task Name: {task.name}
End Date: {task.end_date.strftime('%Y-%m-%d')}
Reminder Start Date: {task.reminder_start_date.strftime('%Y-%m-%d')}

Task Details:
{task.email_content}

This is an initial notification. You will receive regular reminders starting from {task.reminder_start_date.strftime('%Y-%m-%d')}.

Best regards,
Task Management System
    """
    
    for recipient in recipients:
        user = User.query.get(recipient.user_id)
        try:
            send_email(user.email, subject, content)
            print(f"Initial notification sent to {user.email}")
        except Exception as e:
            print(f"Error sending initial notification to {user.email}: {e}")

def create_default_user():
    # Check if admin user exists
    admin = User.query.filter_by(email='admin@example.com').first()
    if not admin:
        admin = User(
            name='Admin',
            email='admin@example.com',
            password='admin123'  # In a production environment, use proper password hashing
        )
        db.session.add(admin)
        try:
            db.session.commit()
            print("Default admin user created successfully!")
        except Exception as e:
            print(f"Error creating default user: {e}")
            db.session.rollback()

# Routes
@app.route('/')
def login():
    if 'user_id' in session:
        return redirect(url_for('homepage'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login_post():
    email = request.form.get('email')
    password = request.form.get('password')
    
    user = User.query.filter_by(email=email, password=password).first()
    if user:
        session['user_id'] = user.id
        return redirect(url_for('homepage'))
    
    flash('Invalid credentials')
    return redirect(url_for('login'))

@app.route('/homepage')
def homepage():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    tasks = Task.query.filter_by(is_complete=False).all()
    return render_template('homepage.html', tasks=tasks)

@app.route('/task/new', methods=['GET', 'POST'])
def new_task():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        task = Task(
            name=request.form['name'],
            end_date=datetime.strptime(request.form['end_date'], '%Y-%m-%d'),
            reminder_start_date=datetime.strptime(request.form['reminder_start_date'], '%Y-%m-%d'),
            email_content=request.form['email_content']
        )
        db.session.add(task)
        db.session.commit()
        
        # Add recipients and send initial notifications
        recipients = []
        for user_id in request.form.getlist('recipients'):
            recipient = TaskRecipient(task_id=task.id, user_id=int(user_id))
            recipients.append(recipient)
            db.session.add(recipient)
        db.session.commit()
        
        # Send immediate notification
        send_initial_task_notification(task, recipients)
        
        # Schedule reminder emails
        schedule_reminder_emails(task.id)
        flash('Task created and initial notifications sent successfully!')
        return redirect(url_for('homepage'))
    
    users = User.query.all()
    return render_template('new_task.html', users=users)

@app.route('/task/<int:task_id>/edit', methods=['GET', 'POST'])
def edit_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    task = Task.query.get_or_404(task_id)
    if request.method == 'POST':
        task.name = request.form['name']
        task.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
        task.reminder_start_date = datetime.strptime(request.form['reminder_start_date'], '%Y-%m-%d')
        task.email_content = request.form['email_content']
        
        # Update recipients and send notifications about changes
        TaskRecipient.query.filter_by(task_id=task.id).delete()
        new_recipients = []
        for user_id in request.form.getlist('recipients'):
            recipient = TaskRecipient(task_id=task.id, user_id=int(user_id))
            new_recipients.append(recipient)
            db.session.add(recipient)
            
        db.session.commit()
        
        # Send notifications about task updates
        send_initial_task_notification(task, new_recipients)
        schedule_reminder_emails(task.id)
        flash('Task updated and notifications sent successfully!')
        return redirect(url_for('homepage'))
    
    users = User.query.all()
    task_recipients = [tr.user_id for tr in TaskRecipient.query.filter_by(task_id=task.id).all()]
    return render_template('edit_task.html', task=task, users=users, task_recipients=task_recipients)


@app.route('/task/<int:task_id>/complete')
def complete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    task = Task.query.get_or_404(task_id)
    task.is_complete = True
    db.session.commit()
    return redirect(url_for('homepage'))

@app.route('/task/<int:task_id>/delete')
def delete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    task = Task.query.get_or_404(task_id)
    TaskRecipient.query.filter_by(task_id=task.id).delete()
    db.session.delete(task)
    db.session.commit()
    return redirect(url_for('homepage'))

@app.route('/users')
def users():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/users/new', methods=['GET', 'POST'])
def new_user():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        user = User(
            name=request.form['name'],
            email=request.form['email'],
            password=request.form['password']
        )
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('users'))
    
    return render_template('new_user.html')

@app.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
def edit_user(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.name = request.form['name']
        user.email = request.form['email']
        if request.form['password']:
            user.password = request.form['password']
        db.session.commit()
        return redirect(url_for('users'))
    
    return render_template('edit_user.html', user=user)

@app.route('/users/<int:user_id>/delete')
def delete_user(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get_or_404(user_id)
    TaskRecipient.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('users'))

@app.route('/users/<int:user_id>/test_email')
def send_test_email(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get_or_404(user_id)
    send_email(user.email, "Test Email", "This is a test email from the task management system.")
    flash('Test email sent successfully')
    return redirect(url_for('users'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_default_user()  # Create default user when starting the app
    app.run(debug=True)