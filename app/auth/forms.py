import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from app.models import User


PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


class LoginForm(FlaskForm):
    identity = StringField("Email or phone", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    remember = BooleanField("Remember me")
    submit = SubmitField("Sign in")


class RegistrationForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone_number = StringField("Phone number", validators=[DataRequired(), Length(min=9, max=30)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    confirm_password = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords must match.")])
    terms = BooleanField("I agree to the prototype terms", validators=[DataRequired(message="You must accept the prototype terms.")])
    submit = SubmitField("Create account")

    def validate_email(self, field):
        if User.query.filter(db_func_lower(User.email) == field.data.strip().lower()).first():
            raise ValidationError("An account already exists with this email.")

    def validate_phone_number(self, field):
        normalized = re.sub(r"[\s()-]", "", field.data)
        if not re.fullmatch(r"(?:\+971|0)5\d{8}", normalized):
            raise ValidationError("Enter a valid UAE mobile number, such as +971 50 123 4567.")
        if User.query.filter_by(phone_number=normalized).first():
            raise ValidationError("An account already exists with this phone number.")
        field.data = normalized

    def validate_password(self, field):
        if not PASSWORD_PATTERN.match(field.data):
            raise ValidationError("Use 8+ characters with uppercase, lowercase, and a number.")


def db_func_lower(column):
    from sqlalchemy import func
    return func.lower(column)

