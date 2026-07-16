from flask import Flask, render_template, request, redirect, session, jsonify
import hashlib, datetime, os, json, secrets, base64
import psycopg
from psycopg.rows import dict_row
import requests as http_requests

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hannaaccs_secret_2025")

DATABASE_URL = os.environ.get("DATABASE_URL")

# Email via Resend (https://resend.com — gratis hasta 3000 emails/mes), usado
# solo para la recuperación de contraseña del panel de administrador.
RESEND_API_KEY  = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM      = os.environ.get("EMAIL_FROM", "hanna accs <onboarding@resend.dev>")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "img", "productos")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ===== DB =====
def get_db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        id SERIAL PRIMARY KEY,
        nombre TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        creado_en TEXT NOT NULL
    )""")
    # Tokens de recuperación de contraseña (solo admin)
    c.execute("""CREATE TABLE IF NOT EXISTS password_resets (
        id SERIAL PRIMARY KEY,
        email TEXT NOT NULL,
        token TEXT NOT NULL,
        expira_en TEXT NOT NULL,
        usado BOOLEAN NOT NULL DEFAULT FALSE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS menu_categorias (
        id SERIAL PRIMARY KEY,
        clave TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        emoji TEXT NOT NULL DEFAULT '',
        orden INTEGER NOT NULL DEFAULT 0,
        activo BOOLEAN NOT NULL DEFAULT TRUE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS menu_subcategorias (
        id SERIAL PRIMARY KEY,
        categoria_clave TEXT NOT NULL,
        clave TEXT NOT NULL,
        nombre TEXT NOT NULL,
        orden INTEGER NOT NULL DEFAULT 0,
        activo BOOLEAN NOT NULL DEFAULT TRUE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS menu_items (
        id SERIAL PRIMARY KEY,
        subcategoria_id INTEGER NOT NULL,
        nombre TEXT NOT NULL,
        descripcion TEXT NOT NULL DEFAULT '',
        precio INTEGER NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        emoji TEXT NOT NULL DEFAULT '',
        imagen TEXT NOT NULL DEFAULT '',
        orden INTEGER NOT NULL DEFAULT 0,
        activo BOOLEAN NOT NULL DEFAULT TRUE
    )""")
    # Migración: por si la tabla ya existía de una versión anterior sin stock
    c.execute("""ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS stock INTEGER NOT NULL DEFAULT 0""")
    c.execute("""ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS imagen TEXT NOT NULL DEFAULT ''""")

    c.execute("SELECT COUNT(*) as cnt FROM menu_categorias")
    if c.fetchone()["cnt"] == 0:
        cats = [
            ("anillos", "Anillos", "", 1),
            ("pulseras", "Pulseras", "", 2),
            ("aros", "Aros", "", 3),
            ("collares", "Collares", "", 4),
        ]
        for cat in cats:
            c.execute("INSERT INTO menu_categorias (clave,nombre,emoji,orden) VALUES (%s,%s,%s,%s)", cat)
        subcats = [
            ("anillos","acero","Acero quirurgico",1),
            ("anillos","plata","Plata 925",2),
            ("anillos","sets","Sets y trios",3),
            ("pulseras","cadenas","Cadenas",1),
            ("pulseras","dijes","Con dijes",2),
            ("pulseras","hilo","De hilo y tejidas",3),
            ("aros","criollas","Criollas",1),
            ("aros","colgantes","Colgantes",2),
            ("aros","piercings","Piercings",3),
            ("collares","gargantillas","Gargantillas",1),
            ("collares","largos","Largos",2),
        ]
        for s in subcats:
            c.execute("INSERT INTO menu_subcategorias (categoria_clave,clave,nombre,orden) VALUES (%s,%s,%s,%s)", s)
        # (subcategoria_clave, nombre, descripcion, precio, stock, orden)
        items_data = [
            ("acero","Anillo luna acero quirurgico","Ajustable, no se pone verde",3500,8,1),
            ("acero","Anillo trio minimalista","Set de 3 anillos finos combinables",4200,5,2),
            ("acero","Anillo palito liso","Bandas finas apilables",2400,12,3),
            ("plata","Anillo plata 925 piedra luna","Piedra natural, talle unico ajustable",6800,4,1),
            ("plata","Anillo plata 925 trenzado","Diseño trenzado clasico",5900,3,2),
            ("sets","Set 5 anillos combinables","Distintos anchos y texturas",5200,6,1),
            ("cadenas","Pulsera cadena rolo","Acero dorado, resistente al agua",4600,7,1),
            ("cadenas","Pulsera cadena figaro","Brillo alto, cierre reforzado",4300,0,2),
            ("dijes","Pulsera dijes corazon","Dije corazon bañado en oro",3800,9,1),
            ("dijes","Pulsera charms varios","Combinable, dijes intercambiables",4100,5,2),
            ("hilo","Pulsera hilo encerado","Ajustable con dije mini",1800,15,1),
            ("hilo","Pulsera tejida colores","Hecha a mano, varios colores",1600,10,2),
            ("criollas","Mini criollas doradas","Livianas para uso diario",3200,11,1),
            ("criollas","Criollas grandes lisas","Acero quirurgico hipoalergenico",3600,6,2),
            ("colgantes","Aros colgantes perla","Perla sintetica, cierre a presion",3900,2,1),
            ("colgantes","Aros colgantes geometricos","Diseño triangular moderno",3400,7,2),
            ("piercings","Piercing nariz clip","Sin necesidad de perforacion",2200,14,1),
            ("piercings","Piercing oreja cartilago","Acero quirurgico",2600,8,2),
            ("gargantillas","Gargantilla perlas","Perlas de rio, cierre regulable",4500,3,1),
            ("gargantillas","Gargantilla choker lisa","Acero dorado ajustable",3700,9,2),
            ("largos","Collar largo medallon","Cadena larga con medallon sol",4800,4,1),
            ("largos","Collar largo perlas","Diseño bohemio con perlas mixtas",5100,0,2),
        ]
        for it in items_data:
            c.execute("SELECT id FROM menu_subcategorias WHERE clave=%s", (it[0],))
            sub = c.fetchone()
            if sub:
                c.execute("""INSERT INTO menu_items (subcategoria_id,nombre,descripcion,precio,stock,emoji,orden)
                             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                          (sub["id"], it[1], it[2], it[3], it[4], "", it[5]))

    c.execute("""INSERT INTO admins (nombre, email, password, creado_en)
                 VALUES (%s, %s, %s, %s)
                 ON CONFLICT (email) DO NOTHING""",
              ("Admin", "admin@hannaaccs.com",
               hashlib.sha256("admin123".encode()).hexdigest(),
               datetime.datetime.now().isoformat()))
    conn.commit()
    c.close()
    conn.close()

init_db()

def get_menu_db():
    """Catálogo público: solo categorías/secciones/productos activos."""
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM menu_categorias WHERE activo=TRUE ORDER BY orden")
    cats = c.fetchall()
    menu = {"categorias": {}}
    for cat in cats:
        c.execute("SELECT * FROM menu_subcategorias WHERE categoria_clave=%s AND activo=TRUE ORDER BY orden",
                  (cat["clave"],))
        subcats = c.fetchall()
        subcategorias = {}
        for sub in subcats:
            c.execute("SELECT * FROM menu_items WHERE subcategoria_id=%s AND activo=TRUE ORDER BY orden",
                      (sub["id"],))
            items = c.fetchall()
            subcategorias[sub["clave"]] = {
                "nombre": sub["nombre"],
                "items": [{"id": it["id"], "nombre": it["nombre"], "desc": it["descripcion"],
                           "precio": it["precio"], "stock": it["stock"],
                           "emoji": it["emoji"], "imagen": it["imagen"]} for it in items]
            }
        menu["categorias"][cat["clave"]] = {
            "nombre": cat["nombre"], "emoji": cat["emoji"],
            "subcategorias": subcategorias
        }
    c.close(); conn.close()
    return menu

def hashear(p): return hashlib.sha256(p.encode()).hexdigest()
def admin_logueado(): return session.get("admin")

def enviar_email(destinatario, asunto, cuerpo_html):
    """Envía un email usando la API de Resend (https://resend.com)."""
    if not RESEND_API_KEY:
        print(f"[EMAIL SKIP] RESEND_API_KEY no configurada. Para: {destinatario} | Asunto: {asunto}")
        return False
    try:
        resp = http_requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from":    EMAIL_FROM,
                "to":      [destinatario],
                "subject": asunto,
                "html":    cuerpo_html
            },
            timeout=10
        )
        if resp.status_code in (200, 201):
            return True
        print(f"[EMAIL ERROR] Resend respondió {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

# ===== VITRINA PÚBLICA =====
@app.route("/")
def index():
    menu = get_menu_db()
    return render_template("menu.html", menu=menu)

# ===== ADMIN: AUTENTICACIÓN =====
@app.route("/admin")
def admin_redirect():
    return redirect("/admin/login")

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if admin_logueado(): return redirect("/admin/panel")
    error = None
    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM admins WHERE email=%s", (email,))
        a = c.fetchone(); c.close(); conn.close()
        if not a or a["password"] != hashear(password):
            error = "Credenciales incorrectas"
        else:
            session["admin"] = {"email": email, "nombre": a["nombre"]}
            return redirect("/admin/panel")
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/admin/login")

@app.route("/admin/recuperar-password", methods=["POST"])
def admin_recuperar_password():
    email = request.form.get("email","").strip().lower()
    if not email or "@" not in email:
        return redirect("/admin/login?error=Email+invalido")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE email=%s", (email,))
    a = c.fetchone()
    if not a:
        c.close(); conn.close()
        return redirect("/admin/login?info=Si+el+email+está+registrado+recibirás+las+instrucciones")
    token = secrets.token_urlsafe(32)
    expira = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
    c.execute("INSERT INTO password_resets (email,token,expira_en) VALUES (%s,%s,%s)",
              (email, token, expira))
    conn.commit(); c.close(); conn.close()
    base_url = request.host_url.rstrip("/")
    link = f"{base_url}/reset-password?token={token}"
    cuerpo = f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:24px">
      <h2 style="color:#b8a4e8">hanna accs · Panel · Recuperar contraseña</h2>
      <p>Hola <strong>{a['nombre']}</strong>,</p>
      <p>Recibimos una solicitud para restablecer tu contraseña de administrador.</p>
      <a href="{link}" style="display:inline-block;background:#b8a4e8;color:#1a1820;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin:16px 0">
        Restablecer contraseña
      </a>
      <p style="color:#888;font-size:13px">Este enlace expira en 1 hora. Si no solicitaste esto, ignorá este mensaje.</p>
      <p style="color:#888;font-size:12px">O copiá este enlace: {link}</p>
    </div>"""
    ok = enviar_email(email, "hanna accs Admin · Recuperar contraseña", cuerpo)
    if not ok:
        return redirect("/admin/login?error=No+se+pudo+enviar+el+email.+Intenta+más+tarde")
    return redirect("/admin/login?info=Te+enviamos+un+email+con+las+instrucciones")

@app.route("/reset-password", methods=["GET","POST"])
def reset_password():
    token = request.args.get("token","") or request.form.get("token","")
    if request.method == "GET":
        if not token:
            return redirect("/admin/login")
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM password_resets WHERE token=%s AND usado=FALSE", (token,))
        reset = c.fetchone(); c.close(); conn.close()
        if not reset or reset["expira_en"] < datetime.datetime.now().isoformat():
            return "<h3 style='font-family:sans-serif;text-align:center;margin-top:60px;color:#b8a4e8'>Enlace inválido o expirado. Solicitá uno nuevo.</h3>"
        return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Nueva contraseña · hanna accs</title>
        <style>
          *{{box-sizing:border-box;margin:0;padding:0}}
          body{{font-family:'DM Sans',sans-serif;background:#0d0d0d;color:#f0f0f0;min-height:100vh;display:flex;align-items:center;justify-content:center}}
          .wrap{{width:100%;max-width:400px;padding:2rem}}
          .card{{background:#161616;border:1px solid #2a2a2a;border-radius:16px;padding:2rem}}
          h2{{font-size:1.1rem;margin-bottom:1.5rem;color:#f0f0f0}}
          .brand{{text-align:center;margin-bottom:2rem;font-size:1.5rem;font-weight:600}}
          .brand span{{color:#b8a4e8}}
          .field{{margin-bottom:1rem}}
          label{{display:block;font-size:.7rem;color:#777;letter-spacing:1px;text-transform:uppercase;margin-bottom:.3rem}}
          input{{width:100%;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;padding:.7rem 1rem;color:#f0f0f0;font-size:.95rem;outline:none}}
          input:focus{{border-color:#b8a4e8}}
          .btn{{width:100%;padding:.85rem;background:#b8a4e8;color:#1a1820;border:none;border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;margin-top:.5rem}}
          .btn:hover{{background:#f3b8d9}}
        </style></head><body>
        <div class="wrap"><div class="brand">hanna<span>accs</span></div>
        <div class="card"><h2>Nueva contraseña</h2>
        <form method="POST" action="/reset-password">
          <input type="hidden" name="token" value="{token}"/>
          <div class="field"><label>Nueva contraseña</label><input type="password" name="password" minlength="6" required placeholder="Mínimo 6 caracteres"/></div>
          <div class="field"><label>Confirmar contraseña</label><input type="password" name="password2" minlength="6" required placeholder="Repetí la contraseña"/></div>
          <button type="submit" class="btn">Guardar nueva contraseña</button>
        </form></div></div></body></html>"""
    # POST
    password  = request.form.get("password","")
    password2 = request.form.get("password2","")
    if not password or len(password) < 6:
        return redirect(f"/reset-password?token={token}&error=minlen")
    if password != password2:
        return redirect(f"/reset-password?token={token}&error=mismatch")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM password_resets WHERE token=%s AND usado=FALSE", (token,))
    reset = c.fetchone()
    if not reset or reset["expira_en"] < datetime.datetime.now().isoformat():
        c.close(); conn.close()
        return "<h3 style='font-family:sans-serif;text-align:center;margin-top:60px;color:#b8a4e8'>Enlace inválido o expirado.</h3>"
    c.execute("UPDATE admins SET password=%s WHERE email=%s", (hashear(password), reset["email"]))
    c.execute("UPDATE password_resets SET usado=TRUE WHERE token=%s", (token,))
    conn.commit(); c.close(); conn.close()
    return redirect("/admin/login?reset=ok")

@app.route("/admin/panel")
def admin_panel():
    if not admin_logueado(): return redirect("/admin/login")
    return render_template("admin_panel.html", admin=admin_logueado())

# ===== ADMIN: CATÁLOGO =====
@app.route("/admin/api/menu")
def admin_get_menu():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM menu_categorias ORDER BY orden")
    cats = c.fetchall()
    result = []
    for cat in cats:
        c.execute("SELECT * FROM menu_subcategorias WHERE categoria_clave=%s ORDER BY orden", (cat["clave"],))
        subcats = c.fetchall()
        subs = []
        for sub in subcats:
            c.execute("SELECT * FROM menu_items WHERE subcategoria_id=%s ORDER BY orden", (sub["id"],))
            items = [dict(it) for it in c.fetchall()]
            subs.append({**dict(sub), "items": items})
        result.append({**dict(cat), "subcategorias": subs})
    c.close(); conn.close()
    return jsonify(result)

@app.route("/admin/api/menu/categorias", methods=["POST"])
def admin_crear_categoria():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    nombre = d.get("nombre","").strip()
    emoji  = d.get("emoji","").strip()
    if not nombre: return jsonify({"error":"Nombre requerido"}), 400
    clave = nombre.lower().replace(" ","_").replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(orden),0)+1 as o FROM menu_categorias")
    orden = c.fetchone()["o"]
    c.execute("INSERT INTO menu_categorias (clave,nombre,emoji,orden) VALUES (%s,%s,%s,%s) RETURNING id",
              (clave, nombre, emoji, orden))
    new_id = c.fetchone()["id"]
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True, "id": new_id, "clave": clave})

@app.route("/admin/api/menu/categorias/<int:cid>", methods=["PUT"])
def admin_editar_categoria(cid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE menu_categorias SET nombre=%s,emoji=%s,activo=%s WHERE id=%s",
              (d.get("nombre",""), d.get("emoji",""), d.get("activo",True), cid))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/menu/categorias/<int:cid>", methods=["DELETE"])
def admin_eliminar_categoria(cid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE menu_categorias SET activo=FALSE WHERE id=%s", (cid,))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/menu/subcategorias", methods=["POST"])
def admin_crear_subcategoria():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    nombre          = d.get("nombre","").strip()
    categoria_clave = d.get("categoria_clave","").strip()
    if not nombre or not categoria_clave: return jsonify({"error":"Datos requeridos"}), 400
    clave = nombre.lower().replace(" ","_").replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(orden),0)+1 as o FROM menu_subcategorias WHERE categoria_clave=%s", (categoria_clave,))
    orden = c.fetchone()["o"]
    c.execute("INSERT INTO menu_subcategorias (categoria_clave,clave,nombre,orden) VALUES (%s,%s,%s,%s) RETURNING id",
              (categoria_clave, clave, nombre, orden))
    new_id = c.fetchone()["id"]
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True, "id": new_id})

@app.route("/admin/api/menu/subcategorias/<int:sid>", methods=["PUT"])
def admin_editar_subcategoria(sid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE menu_subcategorias SET nombre=%s,activo=%s WHERE id=%s",
              (d.get("nombre",""), d.get("activo",True), sid))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/menu/subcategorias/<int:sid>", methods=["DELETE"])
def admin_eliminar_subcategoria(sid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE menu_subcategorias SET activo=FALSE WHERE id=%s", (sid,))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/menu/items", methods=["POST"])
def admin_crear_item():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    nombre          = d.get("nombre","").strip()
    descripcion     = d.get("desc","").strip()
    precio          = int(d.get("precio", 0))
    stock           = int(d.get("stock", 0) or 0)
    emoji           = d.get("emoji","").strip()
    subcategoria_id = int(d.get("subcategoria_id", 0))
    if not nombre or precio <= 0 or not subcategoria_id:
        return jsonify({"error":"Datos invalidos"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(orden),0)+1 as o FROM menu_items WHERE subcategoria_id=%s", (subcategoria_id,))
    orden = c.fetchone()["o"]
    c.execute("""INSERT INTO menu_items (subcategoria_id,nombre,descripcion,precio,stock,emoji,orden)
                 VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
              (subcategoria_id, nombre, descripcion, precio, stock, emoji, orden))
    new_id = c.fetchone()["id"]
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True, "id": new_id})

@app.route("/admin/api/menu/items/<int:iid>", methods=["PUT"])
def admin_editar_item(iid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    conn = get_db(); c = conn.cursor()
    c.execute("""UPDATE menu_items SET nombre=%s,descripcion=%s,precio=%s,stock=%s,emoji=%s,activo=%s WHERE id=%s""",
              (d.get("nombre",""), d.get("desc",""), int(d.get("precio",0)),
               int(d.get("stock", 0) or 0), d.get("emoji",""), d.get("activo",True), iid))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/menu/items/<int:iid>", methods=["DELETE"])
def admin_eliminar_item(iid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE menu_items SET activo=FALSE WHERE id=%s", (iid,))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/menu/items/<int:iid>/imagen", methods=["POST"])
def admin_subir_imagen_item(iid):
    """Recibe imagen como base64 y la guarda en disco."""
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    data_url = d.get("imagen","")
    if not data_url:
        return jsonify({"error":"No se recibió imagen"}), 400
    # Soporta data:image/jpeg;base64,... o data:image/png;base64,...
    try:
        if "," in data_url:
            header, encoded = data_url.split(",", 1)
            ext = "jpg"
            if "png" in header:  ext = "png"
            elif "webp" in header: ext = "webp"
            elif "gif" in header: ext = "gif"
        else:
            encoded = data_url
            ext = "jpg"
        img_bytes = base64.b64decode(encoded)
    except Exception as e:
        return jsonify({"error": f"Imagen inválida: {e}"}), 400
    filename = f"item_{iid}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    with open(filepath, "wb") as f:
        f.write(img_bytes)
    url_imagen = f"/static/img/productos/{filename}"
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE menu_items SET imagen=%s WHERE id=%s", (url_imagen, iid))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True, "url": url_imagen})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
