from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func, or_

from app.extensions import db
from app.models import User
from .forms import LoginForm, RegistrationForm


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.app_shell"))
    form = LoginForm()
    if form.validate_on_submit():
        identity = form.identity.data.strip()
        user = User.query.filter(or_(func.lower(User.email) == identity.lower(), User.phone_number == identity.replace(" ", ""))).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash("Welcome back — your prototype workspace is ready.", "success")
            next_url = request.args.get("next")
            return redirect(next_url if next_url and next_url.startswith("/") else url_for("main.app_shell"))
        form.password.errors.append("The email, phone, or password is incorrect.")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.app_shell"))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            full_name=form.full_name.data.strip(),
            email=form.email.data.strip().lower(),
            phone_number=form.phone_number.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("Account created securely. Sign in to continue.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@auth_bp.post("/forgot")
def forgot_password():
    contact = (request.form.get("contact") or "").strip()
    if len(contact) < 4:
        return jsonify({"ok": False, "message": "Enter your registered email or phone number."}), 400
    return jsonify({"ok": True, "message": "A verification link would be sent to your registered contact. Prototype simulation only."})


@auth_bp.post("/logout")
def logout():
    logout_user()
    flash("You have signed out securely.", "success")
    return redirect(url_for("auth.login"))

