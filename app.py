import zipfile
import os
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_file, abort, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash
from sqlalchemy import func, and_, or_


from config import Config
from models import db, Employee, Client, Service, ClientService, Ticket, Review
from forms import LoginForm, ClientRegistrationForm, EmployeeCreateForm, TicketForm, AssignTicketForm, ReviewForm

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Flask-Limiter для защиты от DDoS
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Загрузка пользователей для Flask-Login
@login_manager.user_loader
def load_user(user_id):
    # Пытаемся загрузить сотрудника или клиента
    # В user_id храним префикс: 'emp_' или 'cli_'
    if user_id.startswith('emp_'):
        return Employee.query.get(int(user_id[4:]))
    elif user_id.startswith('cli_'):
        return Client.query.get(int(user_id[4:]))
    return None

# Вспомогательные функции
def get_current_employee():
    if current_user.is_authenticated and hasattr(current_user, 'role'):
        return current_user
    return None

def get_current_client():
    if current_user.is_authenticated and hasattr(current_user, 'tickets'):
        return current_user
    return None

# Маршруты
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        # Пытаемся найти среди сотрудников
        user = Employee.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data) and user.is_active:
            login_user(user, remember=True)
            session['user_type'] = 'employee'
            # Перенаправление в зависимости от роли
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'operator':
                return redirect(url_for('operator_dashboard'))
            elif user.role == 'executor':
                return redirect(url_for('executor_dashboard'))
            else:
                flash('Неизвестная роль', 'danger')
                return redirect(url_for('index'))
        # Пытаемся найти среди клиентов
        client = Client.query.filter_by(username=form.username.data).first()
        if client and client.check_password(form.password.data) and client.is_active:
            login_user(client, remember=True)
            session['user_type'] = 'client'
            return redirect(url_for('client_dashboard'))
        flash('Неверное имя пользователя или пароль', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('index'))

# Регистрация клиента
@app.route('/client/register', methods=['GET', 'POST'])
def client_register():
    form = ClientRegistrationForm()
    if form.validate_on_submit():
        client = Client(
            username=form.username.data,
            email=form.email.data,
            full_name=form.full_name.data,
            phone=form.phone.data,
            address=form.address.data
        )
        client.set_password(form.password.data)
        db.session.add(client)
        db.session.commit()
        flash('Регистрация успешна! Войдите в систему.', 'success')
        return redirect(url_for('login'))
    return render_template('client_register.html', form=form)

# Клиентский кабинет
@app.route('/client/dashboard')
@login_required
def client_dashboard():
    if not hasattr(current_user, 'tickets'):
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('index'))
    # Получаем услуги клиента
    client_services = ClientService.query.filter_by(client_id=current_user.id).all()
    services = [cs.service for cs in client_services]
    # Получаем заявки клиента
    tickets = Ticket.query.filter_by(client_id=current_user.id).order_by(Ticket.created_at.desc()).all()
    return render_template('client_dashboard.html', services=services, tickets=tickets)

# Создание заявки клиентом
@app.route('/client/create_ticket', methods=['GET', 'POST'])
@login_required
def client_create_ticket():
    if not hasattr(current_user, 'tickets'):
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('index'))
    form = TicketForm()
    if form.validate_on_submit():
        ticket = Ticket(
            title=form.title.data,
            description=form.description.data,
            priority=form.priority.data,
            client_id=current_user.id,
            status='new'
        )
        db.session.add(ticket)
        db.session.commit()
        flash('Заявка создана', 'success')
        return redirect(url_for('client_dashboard'))
    return render_template('create_ticket.html', form=form)

# Просмотр заявки клиентом
@app.route('/client/ticket/<int:ticket_id>')
@login_required
def client_ticket_detail(ticket_id):
    if not hasattr(current_user, 'tickets'):
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('index'))
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.client_id != current_user.id:
        abort(403)
    review = Review.query.filter_by(ticket_id=ticket.id).first()
    return render_template('ticket_detail.html', ticket=ticket, review=review)

# Оставить отзыв
@app.route('/client/review/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def client_review(ticket_id):
    if not hasattr(current_user, 'tickets'):
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('index'))
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.client_id != current_user.id or ticket.status != 'completed':
        flash('Можно оставить отзыв только на завершенную заявку', 'warning')
        return redirect(url_for('client_dashboard'))
    if Review.query.filter_by(ticket_id=ticket.id).first():
        flash('Отзыв уже оставлен', 'info')
        return redirect(url_for('client_dashboard'))
    form = ReviewForm()
    if form.validate_on_submit():
        review = Review(
            ticket_id=ticket.id,
            client_id=current_user.id,
            executor_id=ticket.executor_id,
            rating=form.rating.data,
            comment=form.comment.data
        )
        db.session.add(review)
        db.session.commit()
        flash('Спасибо за отзыв!', 'success')
        return redirect(url_for('client_dashboard'))
    return render_template('reviews.html', form=form, ticket=ticket)

# Администратор: управление пользователями
@app.route('/admin/users')
@login_required
def admin_users():
    if not (hasattr(current_user, 'role') and current_user.role == 'admin'):
        abort(403)
    employees = Employee.query.all()
    clients = Client.query.all()
    return render_template('users_management.html', employees=employees, clients=clients)

@app.route('/admin/employee/create', methods=['GET', 'POST'])
@login_required
def admin_create_employee():
    if not (hasattr(current_user, 'role') and current_user.role == 'admin'):
        abort(403)
    form = EmployeeCreateForm()
    if form.validate_on_submit():
        emp = Employee(
            username=form.username.data,
            email=form.email.data,
            role=form.role.data,
            full_name=form.full_name.data
        )
        emp.set_password(form.password.data)
        db.session.add(emp)
        db.session.commit()
        flash('Сотрудник создан', 'success')
        return redirect(url_for('admin_users'))
    return render_template('employee_create.html', form=form)

@app.route('/admin/employee/<int:id>/toggle')
@login_required
def admin_toggle_employee(id):
    if not (hasattr(current_user, 'role') and current_user.role == 'admin'):
        abort(403)
    emp = Employee.query.get_or_404(id)
    emp.is_active = not emp.is_active
    db.session.commit()
    flash('Статус изменен', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/client/<int:id>/toggle')
@login_required
def admin_toggle_client(id):
    if not (hasattr(current_user, 'role') and current_user.role == 'admin'):
        abort(403)
    client = Client.query.get_or_404(id)
    client.is_active = not client.is_active
    db.session.commit()
    flash('Статус изменен', 'success')
    return redirect(url_for('admin_users'))

# Бэкапы
@app.route('/admin/backup', methods=['GET', 'POST'])
@login_required
def admin_backup():
    if not (hasattr(current_user, 'role') and current_user.role == 'admin'):
        abort(403)
    if request.method == 'POST':
        tables = {
            'employees': Employee,
            'clients': Client,
            'services': Service,
            'client_services': ClientService,
            'tickets': Ticket,
            'reviews': Review
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as zipf:
            for table_name, model in tables.items():
                data = model.query.all()
                if data:
                    # Получаем имена колонок
                    columns = [col.name for col in model.__table__.columns]
                    csv_buffer = io.StringIO()
                    writer = csv.writer(csv_buffer)
                    writer.writerow(columns)
                    for row in data:
                        writer.writerow([getattr(row, col) for col in columns])
                    zipf.writestr(f'{table_name}.csv', csv_buffer.getvalue().encode('utf-8'))
                else:
                    zipf.writestr(f'{table_name}.csv', b'')
        output.seek(0)
        return send_file(
            output,
            download_name='backup.zip',
            as_attachment=True,
            mimetype='application/zip'
        )
    return render_template('backup.html')

# Оператор: дашборд
@app.route('/operator/dashboard')
@login_required
def operator_dashboard():
    if not (hasattr(current_user, 'role') and current_user.role == 'operator'):
        abort(403)
    # Все заявки (можно с фильтрацией)
    tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()
    # Доступные исполнители
    executors = Employee.query.filter_by(role='executor', is_active=True).all()
    return render_template('operator_dashboard.html', tickets=tickets, executors=executors)

# Создание заявки оператором
@app.route('/operator/create_ticket', methods=['GET', 'POST'])
@login_required
def operator_create_ticket():
    if not (hasattr(current_user, 'role') and current_user.role == 'operator'):
        abort(403)
    form = TicketForm()
    # Добавим выбор клиента
    form.client_id = SelectField('Клиент', coerce=int, validators=[DataRequired()])
    form.client_id.choices = [(c.id, c.full_name) for c in Client.query.filter_by(is_active=True).all()]
    if form.validate_on_submit():
        ticket = Ticket(
            title=form.title.data,
            description=form.description.data,
            priority=form.priority.data,
            client_id=form.client_id.data,
            operator_id=current_user.id,
            status='new'
        )
        db.session.add(ticket)
        db.session.commit()
        flash('Заявка создана', 'success')
        return redirect(url_for('operator_dashboard'))
    return render_template('create_ticket.html', form=form)

# Назначение заявки оператором
@app.route('/operator/assign/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def operator_assign(ticket_id):
    if not (hasattr(current_user, 'role') and current_user.role == 'operator'):
        abort(403)
    ticket = Ticket.query.get_or_404(ticket_id)
    form = AssignTicketForm()
    form.executor_id.choices = [(e.id, e.full_name) for e in Employee.query.filter_by(role='executor', is_active=True).all()]
    if form.validate_on_submit():
        ticket.executor_id = form.executor_id.data
        ticket.status = 'assigned'
        db.session.commit()
        flash('Заявка назначена', 'success')
        return redirect(url_for('operator_dashboard'))
    return render_template('assign_ticket.html', form=form, ticket=ticket)

# Исполнитель: дашборд
@app.route('/executor/dashboard')
@login_required
def executor_dashboard():
    if not (hasattr(current_user, 'role') and current_user.role == 'executor'):
        abort(403)
    # Мои назначенные и принятые заявки
    my_tickets = Ticket.query.filter_by(executor_id=current_user.id).order_by(Ticket.created_at.desc()).all()
    # Доступные для принятия заявки (new или assigned другим, но без исполнителя)
    available_tickets = Ticket.query.filter(and_(Ticket.status.in_(['new', 'assigned']), Ticket.executor_id == None)).all()
    return render_template('executor_dashboard.html', my_tickets=my_tickets, available_tickets=available_tickets)

# Принять заявку (исполнитель)
@app.route('/executor/accept/<int:ticket_id>')
@login_required
def executor_accept(ticket_id):
    if not (hasattr(current_user, 'role') and current_user.role == 'executor'):
        abort(403)
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.status in ['new', 'assigned'] and ticket.executor_id is None:
        ticket.executor_id = current_user.id
        ticket.status = 'in_progress'
        db.session.commit()
        flash('Заявка принята в работу', 'success')
    else:
        flash('Нельзя принять эту заявку', 'warning')
    return redirect(url_for('executor_dashboard'))

# Отказаться от заявки (исполнитель)
@app.route('/executor/reject/<int:ticket_id>')
@login_required
def executor_reject(ticket_id):
    if not (hasattr(current_user, 'role') and current_user.role == 'executor'):
        abort(403)
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.executor_id == current_user.id and ticket.status in ['assigned', 'in_progress']:
        ticket.executor_id = None
        ticket.status = 'new'
        db.session.commit()
        flash('Отказ от заявки зарегистрирован. Оператор уведомлен.', 'info')
        # Уведомление оператора (можно записать в лог или отправить email)
        # Здесь просто flash сообщение
    else:
        flash('Невозможно отказаться', 'warning')
    return redirect(url_for('executor_dashboard'))

# Завершить заявку (исполнитель)
@app.route('/executor/complete/<int:ticket_id>')
@login_required
def executor_complete(ticket_id):
    if not (hasattr(current_user, 'role') and current_user.role == 'executor'):
        abort(403)
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.executor_id == current_user.id and ticket.status == 'in_progress':
        ticket.status = 'completed'
        ticket.completed_at = datetime.utcnow()
        db.session.commit()
        flash('Заявка завершена', 'success')
    else:
        flash('Невозможно завершить', 'warning')
    return redirect(url_for('executor_dashboard'))

# Диаграммы для админа и оператора
@app.route('/charts')
@login_required
def charts():
    if hasattr(current_user, 'role'):
        role = current_user.role
        if role in ['admin', 'operator']:
            # Получаем параметры: executor_id (опционально), start_date, end_date
            executor_id = request.args.get('executor_id', type=int)
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            query = Ticket.query
            if executor_id:
                query = query.filter_by(executor_id=executor_id)
            if start_date:
                query = query.filter(Ticket.created_at >= datetime.strptime(start_date, '%Y-%m-%d'))
            if end_date:
                query = query.filter(Ticket.created_at <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
            tickets = query.all()
            # Подсчет статусов
            status_counts = {
                'completed': sum(1 for t in tickets if t.status == 'completed'),
                'cancelled': sum(1 for t in tickets if t.status == 'cancelled'),
                'active': sum(1 for t in tickets if t.status in ['new', 'assigned', 'in_progress'])
            }
            # Список исполнителей для фильтра
            executors = Employee.query.filter_by(role='executor', is_active=True).all()
            return render_template('charts.html', status_counts=status_counts, executors=executors, selected_executor=executor_id, start_date=start_date, end_date=end_date)
        elif role == 'executor':
            # Исполнитель видит только свои заявки
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            query = Ticket.query.filter_by(executor_id=current_user.id)
            if start_date:
                query = query.filter(Ticket.created_at >= datetime.strptime(start_date, '%Y-%m-%d'))
            if end_date:
                query = query.filter(Ticket.created_at <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
            tickets = query.all()
            status_counts = {
                'completed': sum(1 for t in tickets if t.status == 'completed'),
                'cancelled': sum(1 for t in tickets if t.status == 'cancelled'),
                'active': sum(1 for t in tickets if t.status in ['new', 'assigned', 'in_progress'])
            }
            return render_template('charts_executor.html', status_counts=status_counts, start_date=start_date, end_date=end_date)
    abort(403)

# Админ дашборд
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not (hasattr(current_user, 'role') and current_user.role == 'admin'):
        abort(403)
    return render_template('admin_dashboard.html')

# Обработка ошибок
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Создаем администратора, если нет
        if not Employee.query.filter_by(role='admin').first():
            admin = Employee(username='admin', email='admin@example.com', role='admin', full_name='Administrator')
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()
    app.run(debug=True)
