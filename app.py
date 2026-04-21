from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from flask import Flask, render_template, request, redirect, session
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import tensorflow as tf
import numpy as np
import cv2
from twilio.rest import Client
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from flask import send_file
import io
import pymysql
pymysql.install_as_MySQLdb()
app = Flask(__name__)
app.secret_key = "secretkey"

app.config['UPLOAD_FOLDER'] = 'static/uploads'

if not os.path.exists('static/uploads'):
    os.makedirs('static/uploads')

# ---------------- MYSQL CONFIG ----------------
# -------- MYSQL CONFIG --------
import os

app.config['MYSQL_HOST'] = os.getenv('DB_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('DB_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('DB_PASSWORD', '')
app.config['MYSQL_DB'] = os.getenv('DB_NAME', 'pmfby')

# ---------------- LOAD AI MODEL ----------------
model = tf.keras.models.load_model("crop_model.h5")

# Create upload folder if not exists
if not os.path.exists("static/uploads"):
    os.makedirs("static/uploads")


# ================= CLAIM CALCULATION FUNCTION =================
def calculate_claim(sum_insured):
    threshold_yield = 100
    actual_yield = 60
    claim = ((threshold_yield - actual_yield) / threshold_yield) * float(sum_insured)
    return claim

# ================= GPS EXTRACTION FUNCTION =================
def extract_gps(image_path):
    try:
        image = Image.open(image_path)
        exif_data = image._getexif()

        if not exif_data:
            return None, None

        gps_info = {}
        for tag, value in exif_data.items():
            tag_name = TAGS.get(tag)
            if tag_name == "GPSInfo":
                for key in value:
                    gps_tag = GPSTAGS.get(key)
                    gps_info[gps_tag] = value[key]

        def convert_to_degrees(value):
            d = value[0][0] / value[0][1]
            m = value[1][0] / value[1][1]
            s = value[2][0] / value[2][1]
            return d + (m / 60.0) + (s / 3600.0)

        lat = convert_to_degrees(gps_info["GPSLatitude"])
        lon = convert_to_degrees(gps_info["GPSLongitude"])

        return str(lat), str(lon)

    except:
        return None, None

@app.route("/")
def home():
    return render_template("home.html")

# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        farmer_id = request.form['farmer_id']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM farmers WHERE farmer_id=%s", (farmer_id,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[4], password):
            session['farmer_id'] = farmer_id
            return redirect("/dashboard")
        else:
            return render_template("login.html", error="Invalid Farmer ID or Password")

    return render_template("login.html")

    

# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form['name']
        mobile = request.form['mobile']
        farmer_id = request.form['farmer_id']
        password = request.form['password']

        hashed_password = generate_password_hash(password)

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO farmers (name, mobile, farmer_id, password) VALUES (%s,%s,%s,%s)",
            (name, mobile, farmer_id, hashed_password)
        )
        mysql.connection.commit()
        cur.close()

        return redirect("/")

    return render_template("register.html")





# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    if 'farmer_id' in session:
        return render_template("dashboard.html")
    return redirect("/")

import MySQLdb.cursors

@app.route("/patwari_dashboard")
def patwari_dashboard():

    if 'patwari' not in session:
        return redirect("/patwari_login")

    import MySQLdb.cursors
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT * FROM insurance_claims")
    claims = cur.fetchall()

    return render_template("patwari_dashboard.html",claims=claims)

# ================= AI IMAGE UPLOAD =================
@app.route("/upload", methods=["GET","POST"])
def upload():

    prediction = None

    if request.method == "POST":

        file = request.files['image']

        if file and file.filename != "":

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            import cv2
            import numpy as np

            img = cv2.imread(filepath)
            img = cv2.resize(img, (128,128))
            img = img / 255.0
            img = np.expand_dims(img, axis=0)

            result = model.predict(img)

            # ✅ IMPORTANT LINE (MISSING THA)
            value = result[0][0]

            print("Prediction Value:", value)

            # ✅ AB ERROR NAHI AAYEGA
            if value < 0.15:
                prediction = "Damaged"
            else:
                prediction = "Healthy"

    return render_template("upload.html", prediction=prediction)
# ================= NEW CLAIM APPLICATION =================
@app.route("/new_application", methods=["GET","POST"])
def new_application():
    if 'farmer_id' not in session:
        return redirect("/")

    if request.method == "POST":

        file = request.files['damage_image']
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO insurance_claims (
            farmer_id, name, mobile, aadhaar,
            khasra_number, land_area, village, district,
            crop_name, sowing_date, season,
            damage_type, incident_date, damage_image,
            bank_name, account_number, ifsc_code,
            policy_number, sum_insured
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            session['farmer_id'],
            request.form['name'],
            request.form['mobile'],
            request.form['aadhaar'],
            request.form['khasra'],
            request.form['land_area'],
            request.form['village'],
            request.form['district'],
            request.form['crop_name'],
            request.form['sowing_date'],
            request.form['season'],
            request.form['damage_type'],
            request.form['incident_date'],
            filename,
            request.form['bank_name'],
            request.form['account_number'],
            request.form['ifsc_code'],
            request.form['policy_number'],
            request.form['sum_insured']
        ))

        mysql.connection.commit()
        cur.close()

        return redirect("/status")

    return render_template("new_application.html")


# ================= STATUS =================
@app.route("/status")
def status():

    if 'farmer_id' not in session:
        return redirect("/")

    import MySQLdb.cursors
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT * FROM insurance_claims WHERE farmer_id=%s",
                (session['farmer_id'],))

    data = cur.fetchall()
    cur.close()

    return render_template("status.html", data=data)

# ================= PATWARI PANEL =================


# ================= PATWARI LOGIN =================
@app.route("/patwari_login", methods=["GET", "POST"])
def patwari_login():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM patwari_users WHERE username=%s AND password=%s",
                    (username, password))
        user = cur.fetchone()
        cur.close()

        if user:
            session['patwari'] = username
            return redirect("/patwari_dashboard")
        else:
            return render_template("patwari_login.html", error="Invalid Login")

    return render_template("patwari_login.html")


# ================= INSURANCE PANEL =================
@app.route("/insurance_login", methods=["GET", "POST"])
def insurance_login():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']

        if username == "insurance" and password == "1234":
            session['insurance'] = username
            return redirect("/insurance_dashboard")

    return render_template("insurance_login.html")

@app.route("/insurance_dashboard")
def insurance_dashboard():

    if 'insurance' not in session:
        return redirect("/insurance_login")

    import MySQLdb.cursors
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Only Patwari Approved Claims
    cur.execute("""
        SELECT * FROM insurance_claims
        WHERE patwari_status='Approved'
    """)

    claims = cur.fetchall()
    cur.close()

    return render_template("insurance_dashboard.html", claims=claims)

from datetime import date

@app.route("/insurance_verify/<int:id>", methods=["GET","POST"])
def insurance_verify(id):

    import MySQLdb.cursors
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    policy_status = None   # 🔥 important

    if request.method == "POST":

        action = request.form.get("action")

        # ================= VERIFY POLICY =================
        if action == "verify_policy":

            cur.execute("SELECT * FROM insurance_claims WHERE id=%s",(id,))
            claim = cur.fetchone()

            policy_number = claim['policy_number']

            cur.execute(
                "SELECT * FROM insurance_policies WHERE policy_number=%s",
                (policy_number,)
            )

            policy = cur.fetchone()

            if policy:
                policy_status = "verified"
            else:
                policy_status = "not_verified"

            return render_template("insurance_verify.html", claim=claim, policy_status=policy_status)

        # ================= APPROVE =================
        elif action == "approve":

            cur.execute("SELECT * FROM insurance_claims WHERE id=%s",(id,))
            claim = cur.fetchone()

            threshold = 80
            actual = float(claim['actual_yield'] or 0)
            sum_insured = float(claim['sum_insured'] or 0)

            damage_percent = (threshold - actual) / threshold

            if damage_percent < 0:
                damage_percent = 0

            claim_amount = sum_insured * damage_percent

            cur.execute("""
                UPDATE insurance_claims
                SET claim_amount=%s,
                    insurance_status='Approved'
                WHERE id=%s
            """,(claim_amount, id))

            mysql.connection.commit()

            return redirect("/insurance_dashboard")

        # ================= REJECT =================
        elif action == "reject":

            cur.execute("""
                UPDATE insurance_claims
                SET insurance_status='Rejected'
                WHERE id=%s
            """,(id,))

            mysql.connection.commit()

            return redirect("/insurance_dashboard")

    # GET REQUEST
    cur.execute("SELECT * FROM insurance_claims WHERE id=%s",(id,))
    claim = cur.fetchone()

    return render_template("insurance_verify.html", claim=claim, policy_status=policy_status)
                
@app.route("/patwari_verify/<int:id>", methods=["GET","POST"])
def patwari_verify(id):

    if 'patwari' not in session:
        return redirect("/patwari_login")

    import MySQLdb.cursors
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == "POST":

        action = request.form.get("action")
        print("ACTION:", action)   # 🔥 DEBUG

        # 🔵 UPLOAD
        if action == "upload":

            file = request.files.get('survey_image')

            if file and file.filename != "":
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)

                cur.execute("""
                    UPDATE insurance_claims
                    SET survey_image=%s
                    WHERE id=%s
                """, (filename, id))

                mysql.connection.commit()

            return redirect(request.url)   # ✅ SAME PAGE

        # 🟢 APPROVE
        elif action == "approve":

            notes = request.form.get("patwari_notes")
            yield_val = request.form.get("actual_yield")

            cur.execute("""
                UPDATE insurance_claims
                SET patwari_status='Approved',
                    patwari_notes=%s,
                    actual_yield=%s
                WHERE id=%s
            """,(notes, yield_val, id))

            mysql.connection.commit()
            return redirect("/patwari_dashboard")

        # 🔴 REJECT
        elif action == "reject":

            cur.execute("""
                UPDATE insurance_claims
                SET patwari_status='Rejected'
                WHERE id=%s
            """,(id,))

            mysql.connection.commit()
            return redirect("/patwari_dashboard")

    # GET
    cur.execute("SELECT * FROM insurance_claims WHERE id=%s",(id,))
    claim = cur.fetchone()

    return render_template("patwari_verify.html", claim=claim)

# ================= BANK PANEL =================
@app.route("/bank_login", methods=["GET","POST"])
def bank_login():

    if request.method == "POST":

        username = request.form['username']
        password = request.form['password']

        import MySQLdb.cursors
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        cur.execute("SELECT * FROM bank_users WHERE username=%s AND password=%s",
                    (username,password))

        user = cur.fetchone()

        if user:
            session['bank'] = username
            return redirect("/bank_dashboard")

    return render_template("bank_login.html")
@app.route("/bank_dashboard")
def bank_dashboard():

    import MySQLdb.cursors
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT COUNT(*) as total FROM insurance_claims")
    total = cur.fetchone()['total']

    cur.execute("SELECT COUNT(*) as pending FROM insurance_claims WHERE bank_status='Pending'")
    pending = cur.fetchone()['pending']

    cur.execute("SELECT COUNT(*) as paid FROM insurance_claims WHERE bank_status='Paid'")
    paid = cur.fetchone()['paid']

    cur.execute("SELECT * FROM insurance_claims WHERE insurance_status='Approved'")
    claims = cur.fetchall()

    return render_template("bank_dashboard.html",
                           total=total,
                           pending=pending,
                           paid=paid,
                           claims=claims)


@app.route("/bank_view/<int:id>", methods=["GET","POST"])
def bank_view(id):

    import MySQLdb.cursors
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # ✅ claim data lena (IMPORTANT)
    cur.execute("SELECT * FROM insurance_claims WHERE id=%s",(id,))
    claim = cur.fetchone()


    if request.method == "POST":

        action = request.form.get("action")


        # 🔹 VERIFY ACCOUNT
        if action == "verify_account":
            cur.execute("UPDATE insurance_claims SET account_verified='Verified' WHERE id=%s",(id,))


        # 🔹 VERIFY AADHAAR
        elif action == "verify_aadhaar":
            cur.execute("UPDATE insurance_claims SET aadhaar_verified='Verified' WHERE id=%s",(id,))


        # 🔹 VERIFY DBT
        elif action == "verify_dbt":
            cur.execute("UPDATE insurance_claims SET dbt_status='Eligible' WHERE id=%s",(id,))


        # 🔹 APPROVE
        elif action == "approve":
            cur.execute("UPDATE insurance_claims SET bank_status='Approved' WHERE id=%s",(id,))


        # 🔹 REJECT
        elif action == "reject":
            reason = request.form.get("reason")
            cur.execute("""
                UPDATE insurance_claims
                SET bank_status='Rejected',
                    reject_reason=%s
                WHERE id=%s
            """,(reason,id))


        # 🔥 🔥 🔥 YAHAN ADD KARNA HAI (PAYMENT) 🔥 🔥 🔥
        elif action == "pay":

            import datetime

            from_acc = request.form.get("from_account")
            to_acc = request.form.get("to_account")
            amount = request.form.get("amount")

            txn_id = "TXN" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")

            cur.execute("""
                UPDATE insurance_claims
                SET bank_status='Paid',
                    transaction_id=%s,
                    payment_date=NOW()
                WHERE id=%s
            """,(txn_id, id))

            mysql.connection.commit()

            # ✅ SMS simulation
            print(f"""
            SMS SENT to {claim['mobile']}
            ₹{amount} transferred successfully
            From: {from_acc}
            To: {to_acc}
            TXN: {txn_id}
            """)

            return redirect(f"/bank_view/{id}")


        mysql.connection.commit()
        return redirect(f"/bank_view/{id}")


    return render_template("bank_view.html", claim=claim)
@app.route("/download_receipt/<int:id>")
def download_receipt(id):

    import MySQLdb.cursors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from flask import send_file
    import io, os

    # ✅ DB Cursor
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # ✅ JOIN (IMPORTANT)
    cur.execute("""
        SELECT insurance_claims.*, farmers.name, farmers.mobile
        FROM insurance_claims
        LEFT JOIN farmers ON insurance_claims.farmer_id = farmers.id
        WHERE insurance_claims.id=%s
    """, (id,))

    claim = cur.fetchone()

    if not claim:
        return "No data found ❌"

    # ✅ PDF START
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()

    elements = []

    # ================== LOGO ==================
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(base_dir, "static", "logo.png")

    if os.path.exists(logo_path):
        logo = Image(logo_path, width=520, height=90)
        elements.append(logo)

    elements.append(Spacer(1, 10))

    

    # ================== LINE ==================
    elements.append(Paragraph(
        "<para align=center>---------------------------------------------</para>",
        styles['Normal']
    ))

    elements.append(Spacer(1, 15))

    # ================== TABLE ==================
    data = [
        ["Farmer Name", claim.get('name', 'N/A')],
        ["Mobile", claim.get('mobile', 'N/A')],
        ["Claim Amount", f"₹ {claim.get('claim_amount', 0)}"],
        ["Transaction ID", claim.get('transaction_id', 'N/A')],
        ["Payment Date", str(claim.get('payment_date', 'N/A'))],
        ["Status", "PAID ✅"]
    ]

    table = Table(data, colWidths=[150, 250])

    table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TEXTCOLOR', (1,-1), (1,-1), colors.green),
    ]))

    elements.append(table)

    elements.append(Spacer(1, 25))

    # ================== QR ==================
    qr_path = os.path.join(base_dir, "static", "qr.png")

    if os.path.exists(qr_path):
        elements.append(Paragraph(
            "<para align=center>Scan for Verification</para>",
            styles['Normal']
        ))

        elements.append(Spacer(1, 10))

        qr = Image(qr_path, width=120, height=120)
        elements.append(qr)

    elements.append(Spacer(1, 30))

    # ================== SIGNATURE ==================
    elements.append(Paragraph("Authorized Bank Officer", styles['Normal']))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Signature & Stamp", styles['Normal']))

    elements.append(Spacer(1, 30))

    # ================== FOOTER ==================
    elements.append(Paragraph(
        "<para align=center><i>This is a system generated receipt. No signature required.</i></para>",
        styles['Italic']
    ))

    # ================== BUILD PDF ==================
    doc.build(elements)

    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="receipt.pdf", mimetype='application/pdf')
@app.route("/bank_pay/<int:id>")
def bank_pay(id):

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT account_number, ifsc_code FROM insurance_claims WHERE id=%s",(id,))
    claim = cur.fetchone()

    # ❌ Block if details missing
    if not claim['account_number'] or not claim['ifsc_code']:
        return "Bank details missing!"

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE insurance_claims
        SET bank_status='Paid'
        WHERE id=%s
    """,(id,))

    mysql.connection.commit()

    return redirect("/bank_dashboard")

@app.route("/transactions")
def transactions():

    import MySQLdb.cursors
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("""
        SELECT * FROM insurance_claims 
        WHERE bank_status='Paid'
        ORDER BY payment_date DESC
    """)

    data = cur.fetchall()

    return render_template("transactions.html", data=data)

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.pop('farmer_id', None)
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)
