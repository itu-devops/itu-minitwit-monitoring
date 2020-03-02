# -*- coding: utf-8 -*-
"""
    MiniTwit
    ~~~~~~~~

    A microblogging application written with Flask and sqlite3.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import with_statement
import time
import psutil
import sqlite3
from hashlib import md5
from datetime import datetime
from contextlib import closing
from prometheus_client import Counter, Gauge, Histogram
from prometheus_client import generate_latest
from flask import (
    Flask,
    Response,
    request,
    session,
    url_for,
    redirect,
    render_template,
    abort,
    g,
    flash,
)
from werkzeug import check_password_hash, generate_password_hash
from inspect import getmembers, isfunction, currentframe
import sys


EXECUTION_FREQS = {}


# configuration
DATABASE = "/tmp/minitwit.db"
PER_PAGE = 30
DEBUG = True
SECRET_KEY = "development key"

CPU_GAUGE = Gauge(
    "minitwit_cpu_load_percent", "Current load of the CPU in percent."
)
REPONSE_COUNTER = Counter(
    "minitwit_http_responses_total", "The count of HTTP responses sent."
)
REQ_DURATION_SUMMARY = Histogram(
    "minitwit_request_duration_milliseconds", "Request duration distribution."
)


# create our little application :)
app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar("MINITWIT_SETTINGS", silent=True)


# Add /metrics route for Prometheus to scrape
@app.route("/metrics/")
def metrics():
    return Response(
        generate_latest(), mimetype="text/plain; version=0.0.4; charset=utf-8"
    )


def connect_db():
    """Returns a new connection to the database."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    return sqlite3.connect(app.config["DATABASE"])


def init_db():
    """Creates the database tables."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    with closing(connect_db()) as db:
        with app.open_resource("schema.sql") as f:
            db.cursor().executescript(f.read().decode("utf-8"))
        db.commit()


def query_db(query, args=(), one=False):
    """Queries the database and returns a list of dictionaries."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    cur = g.db.execute(query, args)
    rv = [
        dict((cur.description[idx][0], value) for idx, value in enumerate(row))
        for row in cur.fetchall()
    ]
    return (rv[0] if rv else None) if one else rv


def get_user_id(username):
    """Convenience method to look up the id for a username."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    rv = g.db.execute(
        "select user_id from user where username = ?", [username]
    ).fetchone()
    return rv[0] if rv else None


def format_datetime(timestamp):
    """Format a timestamp for display."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    return datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d @ %H:%M")


def gravatar_url(email, size=80):
    """Return the gravatar image for the given email address."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    return "http://www.gravatar.com/avatar/%s?d=identicon&s=%d" % (
        md5(email.strip().lower().encode("utf-8")).hexdigest(),
        size,
    )


@app.before_request
def before_request():
    """Make sure we are connected to the database each request and look
    up the current user so that we know he's there.
    """
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    request.start_time = datetime.now()
    g.db = connect_db()
    g.user = None
    if "user_id" in session:
        g.user = query_db(
            "select * from user where user_id = ?",
            [session["user_id"]],
            one=True,
        )
    CPU_GAUGE.set(psutil.cpu_percent())


@app.after_request
def after_request(response):
    """Closes the database again at the end of the request."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    g.db.close()
    REPONSE_COUNTER.inc()
    t_elapsed_ms = (datetime.now() - request.start_time).total_seconds() * 1000
    REQ_DURATION_SUMMARY.observe(t_elapsed_ms)
    return response


@app.route("/")
def timeline():
    """Shows a users timeline or if no user is logged in it will
    redirect to the public timeline.  This timeline shows the user's
    messages as well as all the messages of followed users.
    """
    print(f"We got a visitor from: {str(request.remote_addr)}")
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    page = request.args.get("p", default=0, type=int)

    if not g.user:
        return redirect(url_for("public_timeline"))
    return render_template(
        "timeline.html",
        messages=query_db(
            """
        select message.*, user.* from message, user
        where message.flagged = 0 and message.author_id = user.user_id and (
            user.user_id = ? or
            user.user_id in (select whom_id from follower
                                    where who_id = ?))
        order by message.pub_date desc limit ? offset ?""",
            [session["user_id"], session["user_id"], PER_PAGE, page * PER_PAGE],
        ),
    )


@app.route("/public")
def public_timeline():
    """Displays the latest messages of all users."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    page = request.args.get("p", default=0, type=int)
    return render_template(
        "timeline.html",
        messages=query_db(
            """
        select message.*, user.* from message, user
        where message.flagged = 0 and message.author_id = user.user_id
        order by message.pub_date desc limit ? offset ?""",
            [PER_PAGE, page * PER_PAGE],
        ),
    )


@app.route("/<username>")
def user_timeline(username):
    """Display's a users tweets."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    profile_user = query_db(
        "select * from user where username = ?", [username], one=True
    )
    if profile_user is None:
        abort(404)
    followed = False
    if g.user:
        followed = (
            query_db(
                """select 1 from follower where
            follower.who_id = ? and follower.whom_id = ?""",
                [session["user_id"], profile_user["user_id"]],
                one=True,
            )
            is not None
        )

    page = request.args.get("p", default=0, type=int)

    return render_template(
        "timeline.html",
        messages=query_db(
            """
            select message.*, user.* from message, user where message.flagged = 0 and
            user.user_id = message.author_id and user.user_id = ?
            order by message.pub_date desc limit ? offset ?""",
            [profile_user["user_id"], PER_PAGE, page * PER_PAGE],
        ),
        followed=followed,
        profile_user=profile_user,
    )


@app.route("/<username>/follow")
def follow_user(username):
    """Adds the current user as follower of the given user."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)
    g.db.execute(
        "insert into follower (who_id, whom_id) values (?, ?)",
        [session["user_id"], whom_id],
    )
    g.db.commit()
    flash('You are now following "%s"' % username)
    return redirect(url_for("user_timeline", username=username))


@app.route("/<username>/unfollow")
def unfollow_user(username):
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    """Removes the current user as follower of the given user."""
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)
    g.db.execute(
        "delete from follower where who_id=? and whom_id=?",
        [session["user_id"], whom_id],
    )
    g.db.commit()
    flash('You are no longer following "%s"' % username)
    return redirect(url_for("user_timeline", username=username))


@app.route("/add_message", methods=["POST"])
def add_message():
    """Registers a new message for the user."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    if "user_id" not in session:
        abort(401)
    if request.form["text"]:
        g.db.execute(
            """insert into message (author_id, text, pub_date, flagged)
            values (?, ?, ?, 0)""",
            (session["user_id"], request.form["text"], int(time.time())),
        )
        g.db.commit()
        flash("Your message was recorded")
    return redirect(url_for("timeline"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Logs the user in."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    if g.user:
        return redirect(url_for("timeline"))
    error = None
    if request.method == "POST":
        user = query_db(
            """select * from user where
            username = ?""",
            [request.form["username"]],
            one=True,
        )
        if user is None:
            error = "Invalid username"
        elif not check_password_hash(user["pw_hash"], request.form["password"]):
            error = "Invalid password"
        else:
            flash("You were logged in")
            session["user_id"] = user["user_id"]
            return redirect(url_for("timeline"))
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Registers the user."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    if g.user:
        return redirect(url_for("timeline"))
    error = None
    if request.method == "POST":
        if not request.form["username"]:
            error = "You have to enter a username"
        elif not request.form["email"] or "@" not in request.form["email"]:
            error = "You have to enter a valid email address"
        elif not request.form["password"]:
            error = "You have to enter a password"
        elif request.form["password"] != request.form["password2"]:
            error = "The two passwords do not match"
        elif get_user_id(request.form["username"]) is not None:
            error = "The username is already taken"
        else:
            g.db.execute(
                """insert into user (
                username, email, pw_hash) values (?, ?, ?)""",
                [
                    request.form["username"],
                    request.form["email"],
                    generate_password_hash(request.form["password"]),
                ],
            )
            g.db.commit()
            flash("You were successfully registered and can login now")
            return redirect(url_for("login"))
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    """Logs the user out."""
    EXECUTION_FREQS[currentframe().f_code.co_name].inc()

    flash("You were logged out")
    session.pop("user_id", None)
    return redirect(url_for("public_timeline"))


# add some filters to jinja
app.jinja_env.filters["datetimeformat"] = format_datetime
app.jinja_env.filters["gravatar"] = gravatar_url


# Populate the dictionary of functions mapping to one Counter per function
this_module = sys.modules[__name__]

for name, f_kind in getmembers(this_module):
    if isfunction(f_kind):
        EXECUTION_FREQS[name] = Counter(
            f"minitwit_fct_{name}", f"No. of calls of {name}"
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0")
