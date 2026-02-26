from flask import Blueprint, render_template

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/verify")
def index():
    return render_template("index.html")


@pages_bp.route("/verify/s/<session_id>")
def session(session_id):
    return render_template("session.html", session_id=session_id)