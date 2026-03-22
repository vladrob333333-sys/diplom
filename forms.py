from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, SelectField, IntegerField, BooleanField, DateField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, Optional
from models import Employee, Client

class LoginForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

class ClientRegistrationForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=4, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=6)])
    password2 = PasswordField('Повторите пароль', validators=[DataRequired(), EqualTo('password')])
    full_name = StringField('Полное имя', validators=[DataRequired()])
    phone = StringField('Телефон')
    address = StringField('Адрес')
    submit = SubmitField('Зарегистрироваться')

    def validate_username(self, username):
        user = Client.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Имя пользователя уже занято.')

    def validate_email(self, email):
        user = Client.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email уже зарегистрирован.')

class EmployeeCreateForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=4, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=6)])
    role = SelectField('Роль', choices=[('admin', 'Администратор'), ('operator', 'Оператор'), ('executor', 'Исполнитель')], validators=[DataRequired()])
    full_name = StringField('Полное имя')
    submit = SubmitField('Создать')

    def validate_username(self, username):
        user = Employee.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Имя пользователя уже занято.')

    def validate_email(self, email):
        user = Employee.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email уже зарегистрирован.')

class TicketForm(FlaskForm):
    title = StringField('Заголовок', validators=[DataRequired()])
    description = TextAreaField('Описание', validators=[DataRequired()])
    priority = SelectField('Приоритет', choices=[('low', 'Низкий'), ('medium', 'Средний'), ('high', 'Высокий')], validators=[DataRequired()])
    # executor_id будет динамическим
    submit = SubmitField('Создать заявку')

class AssignTicketForm(FlaskForm):
    executor_id = SelectField('Назначить исполнителю', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Назначить')

class ReviewForm(FlaskForm):
    rating = SelectField('Оценка', choices=[(1, '1'), (2, '2'), (3, '3'), (4, '4'), (5, '5')], validators=[DataRequired()], coerce=int)
    comment = TextAreaField('Комментарий', validators=[Optional()])
    submit = SubmitField('Отправить отзыв')