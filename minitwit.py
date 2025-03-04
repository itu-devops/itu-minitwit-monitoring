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
from flask_restx import Api, Namespace, Resource, reqparse,fields
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
from werkzeug.security import check_password_hash, generate_password_hash


# configuration
DATABASE = "./tmp/minitwit.db"
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
def format_datetime(timestamp):
    """Format a timestamp for display."""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d @ %H:%M")


def gravatar_url(email, size=80):
    """Return the gravatar image for the given email address."""
    return "http://www.gravatar.com/avatar/%s?d=identicon&s=%d" % (
        md5(email.strip().lower().encode("utf-8")).hexdigest(),
        size,
    )


# create our little application :)
app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar("MINITWIT_SETTINGS", silent=True)
# add some filters to jinja
app.jinja_env.filters["datetimeformat"] = format_datetime
app.jinja_env.filters["gravatar"] = gravatar_url
api = Api(None,1.0,"Minitwit specification",doc="/api/docs")
api_ns = Namespace("api",description="api specific endpoints")
api.add_namespace(api_ns)


def connect_db():
    """Returns a new connection to the database."""
    return sqlite3.connect(app.config["DATABASE"])


def init_db():
    """Creates the database tables."""
    with closing(connect_db()) as db:
        with app.open_resource("schema.sql") as f:
            db.cursor().executescript(f.read().decode("utf-8"))
        db.commit()


def query_db(query, args=(), one=False):
    """Queries the database and returns a list of dictionaries."""
    cur = g.db.execute(query, args)
    rv = [
        dict((cur.description[idx][0], value) for idx, value in enumerate(row))
        for row in cur.fetchall()
    ]
    return (rv[0] if rv else None) if one else rv


def get_user_id(username):
    """Convenience method to look up the id for a username."""
    rv = g.db.execute(
        "select user_id from user where username = ?", [username]
    ).fetchone()
    return rv[0] if rv else None




@app.before_request
def before_request():
    """Make sure we are connected to the database each request and look
    up the current user so that we know he's there.
    """
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
    g.db.close()
    REPONSE_COUNTER.inc()
    t_elapsed_ms = (datetime.now() - request.start_time).total_seconds() * 1000
    REQ_DURATION_SUMMARY.observe(t_elapsed_ms)
    return response

@api_ns.route("/metrics")
class Metrics(Resource):
    @api_ns.response(200, "Success")
    def get(self):
        """Retrieve Prometheus metrics"""
        response = Response(generate_latest())
        response.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8"
        return response



@app.route("/public")
def public_timeline():
    """Displays the latest messages of all users."""
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

@app.route("/")
def timeline():
    """Shows a users timeline or if no user is logged in it will
    redirect to the public timeline.  This timeline shows the user's
    messages as well as all the messages of followed users.
    """
    print(f"We got a visitor from: {str(request.remote_addr)}")

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


@app.route("/<username>")
def user_timeline(username):
    """Display's a users tweets."""
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


follow_model = api_ns.model(
    "FollowUserModel",
    {
        "message": fields.String(description="Confirmation message"),
    },
)

@api_ns.route("/<string:username>/follow")
class FollowUser(Resource):
    @api_ns.response(201, "Success", follow_model)
    @api_ns.response(401, "Unauthorized")
    @api_ns.response(404, "User not found")
    def get(self, username):
        """Follow a user (Requires authentication)"""
        if not g.get("user"):
            abort(401)

        whom_id = get_user_id(username)
        if whom_id is None:
            abort(404)

        g.db.execute(
            "INSERT INTO follower (who_id, whom_id) VALUES (?, ?)",
            [session["user_id"], whom_id],
        )
        g.db.commit()

        return {"message": f"You are now following {username}"}, 201

@app.route("/<username>/unfollow")
def unfollow_user(username):
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


unfollow_model = api_ns.model(
    "UnfollowUserModel",
    {
        "message": fields.String(description="Confirmation message"),
    },
)

@api_ns.route("/<string:username>/unfollow")
class UnfollowUser(Resource):
    @api_ns.response(200, "Success", unfollow_model)
    @api_ns.response(401, "Unauthorized")
    @api_ns.response(404, "User not found")
    def delete(self, username):
        """Unfollow a user (Requires authentication)"""
        if not g.get("user"):
            abort(401)

        whom_id = get_user_id(username)
        if whom_id is None:
            abort(404)

        g.db.execute(
            "DELETE FROM follower WHERE who_id=? AND whom_id=?",
            [session["user_id"], whom_id],
        )
        g.db.commit()

        return {"message": f"You are no longer following {username}"}, 200


@app.route("/add_message", methods=["POST"])
def add_message():
    """Registers a new message for the user."""
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

@api_ns.route("/add_message")
class AddMessage(Resource):
    def post(self):
        """Registers a new message for the user."""
        if "user_id" not in session:
            abort(401)
        
        g.db.execute(
            """INSERT INTO message (author_id, text, pub_date, flagged)
               VALUES (?, ?, ?, 0)""",
            (session["user_id"], request.form["text"], int(time.time())),
        )
        g.db.commit()

        return {"message": "Your message was recorded"}, 201  # 201 Created

# Define a Model for Request Body (Better than reqparse)
message_model = api_ns.model(
    "MessageModel",
    {
        "text": fields.String(required=True, description="The message text"),
    },
)

@api_ns.route("/add_message")
class AddMessage(Resource):
    @api_ns.expect(message_model) 
    @api_ns.doc(
        description="Registers a new message for the logged-in user.",
        consumes=["application/json"],
        responses={
            201: "Message created",
            400: "Missing or invalid input",
            401: "Unauthorized",
        },
    )
    def post(self):
        """Registers a new message for the user."""
        if "user_id" not in session:
            abort(401)

        # Get JSON data
        data = request.get_json()
        if not data or "text" not in data:
            abort(400, "Missing 'text' field")

        g.db.execute(
            """INSERT INTO message (author_id, text, pub_date, flagged)
               VALUES (?, ?, ?, 0)""",
            (session["user_id"], data["text"], int(time.time())),
        )
        g.db.commit()

        return {"message": "Your message was recorded"}, 201 

@app.route("/login", methods=["GET", "POST"])
def login():
    """Logs the user in."""
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

login_model = api_ns.model(
    "LoginModel",
    {
        "username": fields.String(required=True, description="Username"),
        "password": fields.String(required=True, description="Password"),
    },
)
@api_ns.route("/login")
class Login(Resource):
    @api_ns.expect(login_model)
    @api_ns.doc(
        description="Logs the user in using session-based authentication.",
        responses={
            200: "Login successful",
            400: "Invalid input",
            401: "Unauthorized",
        },
    )
    def post(self):
        """Logs the user in."""
        if g.get("user"):
            return {"message": "Already logged in"}, 200

        username = request.form.get("username")
        password = request.form.get("password")

        user = query_db("SELECT * FROM user WHERE username = ?", [username], one=True)

        if user is None:
            return {"error": "Invalid username"}, 401
        if not check_password_hash(user["pw_hash"], password):
            return {"error": "Invalid password"}, 401

        session["user_id"] = user["user_id"]
        return {"message": "You were logged in", "user_id": user["user_id"]}, 200


@app.route("/register", methods=["GET", "POST"])
def register():
    """Registers the user."""
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



register_model = api_ns.model(
    "RegisterForm",
    {
        "username": fields.String(required=True, description="Username"),
        "email": fields.String(required=True, description="Valid Email Address"),
        "password": fields.String(required=True, description="Password"),
        "password2": fields.String(required=False, description="Repeat Password"),
    },
)

@api_ns.route("/register")
class Register(Resource):
    @api_ns.expect(register_model)
    @api_ns.doc(
        consumes=["application/x-www-form-urlencoded"],
        responses={
            201: "User registered successfully",
            400: "Bad Request - Possible errors: \n"
                 "- Missing required fields\n"
                 "- You have to enter a valid email address\n"
                 "- The two passwords do not match",
            401: "Unauthorized - User already logged in",
            409: "Conflict - Username already taken",
        }
    )
    def post(self):
        """Registers a new user."""
        if g.get("user"):
            return redirect(url_for("timeline"))

        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        password2 = request.form.get("password2")

        if not username:
            return {"error": "You have to enter a username"}, 400
        if not email:
            return {"error": "You have to enter a email"}, 400
        if not password:
            return {"error": "You have to enter a password"}, 400
        if "@" not in email:
            return {"error": "You have to enter a valid email address"}, 400
        if password != password2:
            return {"error": "The two passwords do not match"}, 400
        if get_user_id(username) is not None:
            return {"error": "The username is already taken"}, 400

        g.db.execute(
            "INSERT INTO user (username, email, pw_hash) VALUES (?, ?, ?)",
            [username, email, generate_password_hash(password)],
        )
        g.db.commit()

        return {"message": "You were successfully registered and can login now"}, 201


@app.route("/logout")
def logout():
    """Logs the user out."""
    flash("You were logged out")
    session.pop("user_id", None)
    return redirect(url_for("public_timeline"))

@api_ns.route("/logout")
class Logout(Resource):
    @api_ns.doc(
        responses={
            200: "You were logged out",
        }
    )
    def get(self):
        """Logs the user out and clears the session."""
        session.pop("user_id", None)
        return {"message": "You were logged out"}, 200


api.init_app(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0")
