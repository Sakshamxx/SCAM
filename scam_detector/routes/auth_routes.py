from flask import render_template, request, session, redirect, url_for
from scam_detector.database.supabase_client import supabase, log_activity
from werkzeug.security import generate_password_hash, check_password_hash

def register_auth_routes(app):
    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if "user" in session:
            return redirect("/dashboard")
            
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            confirm_password = request.form.get("confirm_password")
            
            if not username or not password:
                return render_template("signup.html", error="All fields are required.")
                
            if password != confirm_password:
                return render_template("signup.html", error="Passwords do not match.")
                
            try:
                existing_user = supabase.table("users").select("*").eq("username", username).execute()
                if existing_user.data:
                    return render_template("signup.html", error="Username already exists.")
                    
                hashed_password = generate_password_hash(password)
                supabase.table("users").insert({
                    "username": username,
                    "password": hashed_password
                }).execute()
                try:
                    log_activity(username, "Created Account")
                except Exception as e:
                    print("Error logging Created Account activity:", e)
                return redirect("/login")
            except Exception as e:
                return render_template("signup.html", error="An error occurred during signup. Please try again.")
        return render_template("signup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if "user" in session:
            return redirect("/dashboard")

        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            remember = request.form.get("remember") == "on"
            
            if not username or not password:
                return render_template("login.html", error="All fields are required.")
                
            try:
                user = supabase.table("users").select("*").eq("username", username).execute()
                if len(user.data) > 0:
                    db_user = user.data[0]
                    if check_password_hash(db_user["password"], password):
                        session["user"] = username
                        session["is_admin"] = db_user.get("is_admin", False)
                        session.permanent = remember
                        try:
                            log_activity(username, "Logged In")
                        except Exception as e:
                            print("Error logging Logged In activity:", e)
                        return redirect("/dashboard")
                return render_template("login.html", error="Invalid Username or Password")
            except Exception as e:
                return render_template("login.html", error="An error occurred during login. Please try again.")
                
        error_msg = request.args.get("error")
        return render_template("login.html", error=error_msg)

    @app.route("/logout")
    def logout():
        if "user" not in session:
            return redirect(url_for("login", error="Unauthorized access. Please log in."))

        username = session.get("user")
        if username:
            try:
                log_activity(username, "Logged Out")
            except Exception as e:
                print("Error logging Logged Out activity:", e)
        session.clear()
        return redirect("/")
