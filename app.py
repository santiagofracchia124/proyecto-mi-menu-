from flask import Flask, render_template, request, redirect, session, jsonify
import hashlib, datetime, os, json, secrets, base64
import psycopg
from psycopg.rows import dict_row
import requests as http_requests

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hannaaccs_secret_2025")

DATABASE_URL = os.environ.get("DATABASE_URL")
MPAT = os.environ.get("MPAT", "")
MPPK = os.environ.get("MPPK", "")

# Email via Resend (https://resend.com — gratis hasta 3000 emails/mes)
RESEND_API_KEY  = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM      = os.environ.get("EMAIL_FROM", "hanna accs <onboarding@resend.dev>")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "img", "productos")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

def mp_get(endpoint):
    headers = {"Authorization": f"Bearer {MPAT}"}
    r = http_requests.get(f"https://api.mercadopago.com/{endpoint}", headers=headers, timeout=10)
    return r.status_code, r.json()

def mp_api_preferencia(items_mp, payer_email, back_urls, external_reference, notification_url):
    def to_https(url):
        return url.replace("http://", "https://")
    body = {
        "items": items_mp,
        "payer": {"email": payer_email},
        "back_urls": {
            "success": to_https(back_urls.get("success","")),
            "failure": to_https(back_urls.get("failure","")),
            "pending": to_https(back_urls.get("pending",""))
        },
        "external_reference": external_reference,
        "statement_descriptor": "HannaAccs",
    }
    headers = {"Authorization": f"Bearer {MPAT}", "Content-Type": "application/json"}
    try:
        r = http_requests.post("https://api.mercadopago.com/checkout/preferences",
                               json=body, headers=headers, timeout=15)
        print("MP STATUS:", r.status_code, r.text[:300])
        return r.status_code, r.json()
    except Exception as e:
        print("MP EXCEPTION:", str(e))
        return 500, {"error": str(e)}

# ===== DB =====
def get_db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        nombre TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        creado_en TEXT NOT NULL,
        puntos INTEGER NOT NULL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        id SERIAL PRIMARY KEY,
        nombre TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        creado_en TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS pedidos (
        id SERIAL PRIMARY KEY,
        usuario_email TEXT NOT NULL,
        usuario_nombre TEXT NOT NULL,
        items TEXT NOT NULL,
        total INTEGER NOT NULL,
        puntos_ganados INTEGER NOT NULL DEFAULT 0,
        tipo TEXT NOT NULL DEFAULT 'local',
        pago TEXT NOT NULL DEFAULT 'efectivo',
        estado TEXT NOT NULL DEFAULT 'pendiente',
        hora TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS canjes (
        id SERIAL PRIMARY KEY,
        usuario_email TEXT NOT NULL,
        beneficio_id INTEGER NOT NULL,
        beneficio_nombre TEXT NOT NULL,
        puntos_usados INTEGER NOT NULL,
        hora TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS beneficios (
        id SERIAL PRIMARY KEY,
        nombre TEXT NOT NULL,
        descripcion TEXT NOT NULL,
        puntos INTEGER NOT NULL,
        emoji TEXT NOT NULL DEFAULT '',
        activo BOOLEAN NOT NULL DEFAULT TRUE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS pagos_mp (
        id SERIAL PRIMARY KEY,
        pedido_id INTEGER,
        preference_id TEXT,
        payment_id TEXT,
        estado TEXT NOT NULL DEFAULT 'pendiente',
        tipo TEXT NOT NULL DEFAULT 'checkout',
        total INTEGER NOT NULL,
        usuario_email TEXT NOT NULL,
        hora TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS config (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    )""")
    # Tabla para tokens de recuperación de contraseña
    c.execute("""CREATE TABLE IF NOT EXISTS password_resets (
        id SERIAL PRIMARY KEY,
        email TEXT NOT NULL,
        token TEXT NOT NULL,
        tipo TEXT NOT NULL DEFAULT 'usuario',
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
        emoji TEXT NOT NULL DEFAULT '',
        imagen TEXT NOT NULL DEFAULT '',
        orden INTEGER NOT NULL DEFAULT 0,
        activo BOOLEAN NOT NULL DEFAULT TRUE
    )""")
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
        items_data = [
            ("acero","Anillo luna acero quirurgico","Ajustable, no se pone verde",3500,"",1),
            ("acero","Anillo trio minimalista","Set de 3 anillos finos combinables",4200,"",2),
            ("acero","Anillo palito liso","Bandas finas apilables",2400,"",3),
            ("plata","Anillo plata 925 piedra luna","Piedra natural, talle unico ajustable",6800,"",1),
            ("plata","Anillo plata 925 trenzado","Diseño trenzado clasico",5900,"",2),
            ("sets","Set 5 anillos combinables","Distintos anchos y texturas",5200,"",1),
            ("cadenas","Pulsera cadena rolo","Acero dorado, resistente al agua",4600,"",1),
            ("cadenas","Pulsera cadena figaro","Brillo alto, cierre reforzado",4300,"",2),
            ("dijes","Pulsera dijes corazon","Dije corazon bañado en oro",3800,"",1),
            ("dijes","Pulsera charms varios","Combinable, dijes intercambiables",4100,"",2),
            ("hilo","Pulsera hilo encerado","Ajustable con dije mini",1800,"",1),
            ("hilo","Pulsera tejida colores","Hecha a mano, varios colores",1600,"",2),
            ("criollas","Mini criollas doradas","Livianas para uso diario",3200,"",1),
            ("criollas","Criollas grandes lisas","Acero quirurgico hipoalergenico",3600,"",2),
            ("colgantes","Aros colgantes perla","Perla sintetica, cierre a presion",3900,"",1),
            ("colgantes","Aros colgantes geometricos","Diseño triangular moderno",3400,"",2),
            ("piercings","Piercing nariz clip","Sin necesidad de perforacion",2200,"",1),
            ("piercings","Piercing oreja cartilago","Acero quirurgico",2600,"",2),
            ("gargantillas","Gargantilla perlas","Perlas de rio, cierre regulable",4500,"",1),
            ("gargantillas","Gargantilla choker lisa","Acero dorado ajustable",3700,"",2),
            ("largos","Collar largo medallon","Cadena larga con medallon sol",4800,"",1),
            ("largos","Collar largo perlas","Diseño bohemio con perlas mixtas",5100,"",2),
        ]
        for it in items_data:
            c.execute("SELECT id FROM menu_subcategorias WHERE clave=%s", (it[0],))
            sub = c.fetchone()
            if sub:
                c.execute("INSERT INTO menu_items (subcategoria_id,nombre,descripcion,precio,emoji,orden) VALUES (%s,%s,%s,%s,%s,%s)",
                          (sub["id"], it[1], it[2], it[3], it[4], it[5]))
    c.execute("""INSERT INTO config (clave, valor) VALUES ('puntos_por_peso', '50')
                 ON CONFLICT (clave) DO NOTHING""")
    beneficios_default = [
        ('15% de descuento en tu proxima compra', '15% off en cualquier producto', 800, ''),
        ('Envio gratis', 'Envio sin cargo en tu proximo pedido', 400, ''),
        ('Aros de regalo', 'Un par de aros mini de regalo en tu compra', 1200, ''),
        ('20% off en anillos', 'Descuento en cualquier anillo del catalogo', 500, ''),
        ('Estuche premium gratis', 'Estuche de regalo premium sin cargo', 300, ''),
        ('Pulsera gratis', 'Una pulsera a eleccion sin cargo', 1500, ''),
    ]
    for b in beneficios_default:
        c.execute("""INSERT INTO beneficios (nombre, descripcion, puntos, emoji)
                     SELECT %s, %s, %s, %s WHERE NOT EXISTS (SELECT 1 FROM beneficios WHERE nombre=%s)""",
                  (b[0], b[1], b[2], b[3], b[0]))
    c.execute("""INSERT INTO admins (nombre, email, password, creado_en)
                 VALUES (%s, %s, %s, %s)
                 ON CONFLICT (email) DO NOTHING""",
              ("Admin", "admin@hannaaccs.com",
               hashlib.sha256("admin123".encode()).hexdigest(),
               datetime.datetime.now().isoformat()))
    # Migración: agregar columna imagen si no existe
    c.execute("""
        ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS imagen TEXT NOT NULL DEFAULT ''
    """)
    conn.commit()
    c.close()
    conn.close()

init_db()

def get_menu_db():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM menu_categorias WHERE activo=TRUE ORDER BY orden")
    cats = c.fetchall()
    menu = {"menu_del_dia": {
        "nombre": "Anillo luna acero quirurgico",
        "descripcion": "Ajustable, hipoalergenico, no se pone verde. Ideal para regalar o combinar.",
        "precio": 3500, "emoji": ""
    }, "categorias": {}}
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
                           "precio": it["precio"], "emoji": it["emoji"], "imagen": it["imagen"]} for it in items]
            }
        menu["categorias"][cat["clave"]] = {
            "nombre": cat["nombre"], "emoji": cat["emoji"],
            "subcategorias": subcategorias
        }
    c.close(); conn.close()
    return menu

def get_beneficios():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM beneficios WHERE activo=TRUE ORDER BY puntos ASC")
    rows = c.fetchall(); c.close(); conn.close()
    return [dict(r) for r in rows]

def get_puntos_por_peso():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT valor FROM config WHERE clave='puntos_por_peso'")
    row = c.fetchone(); c.close(); conn.close()
    return int(row["valor"]) if row else 50

def hashear(p): return hashlib.sha256(p.encode()).hexdigest()
def usuario_logueado(): return session.get("usuario")
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

def get_puntos(email):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT puntos FROM usuarios WHERE email=%s", (email,))
    row = c.fetchone(); c.close(); conn.close()
    return row["puntos"] if row else 0

# ===== RUTAS CLIENTE =====
@app.route("/")
def index():
    usuario = usuario_logueado()
    if usuario:
        usuario["puntos"] = get_puntos(usuario["email"])
        session["usuario"] = usuario
    beneficios = get_beneficios()
    puntos_por_peso = get_puntos_por_peso()
    menu = get_menu_db()
    return render_template("menu.html", menu=menu, usuario=usuario,
                           beneficios=beneficios, puntos_por_peso=puntos_por_peso)

@app.route("/login", methods=["POST"])
def login():
    email    = request.form.get("email","").strip().lower()
    password = request.form.get("password","")
    next_url = request.form.get("next","/")
    if not email or not password:
        return redirect("/?auth_error=Completa+todos+los+campos&tab=login")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE email=%s", (email,))
    u = c.fetchone(); c.close(); conn.close()
    if not u: return redirect("/?auth_error=No+existe+una+cuenta+con+ese+email&tab=login")
    if u["password"] != hashear(password): return redirect("/?auth_error=Contrasena+incorrecta&tab=login")
    session["usuario"] = {"email": email, "nombre": u["nombre"], "puntos": u["puntos"]}
    return redirect(next_url)

@app.route("/registro", methods=["POST"])
def registro():
    nombre   = request.form.get("nombre","").strip()
    email    = request.form.get("email","").strip().lower()
    password = request.form.get("password","")
    next_url = request.form.get("next","/")
    if not nombre or not email or not password:
        return redirect("/?auth_error=Completa+todos+los+campos&tab=registro")
    if "@" not in email or "." not in email:
        return redirect("/?auth_error=Email+invalido&tab=registro")
    if len(password) < 6:
        return redirect("/?auth_error=La+contrasena+debe+tener+al+menos+6+caracteres&tab=registro")
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO usuarios (nombre,email,password,creado_en,puntos) VALUES (%s,%s,%s,%s,%s)",
                  (nombre, email, hashear(password), datetime.datetime.now().isoformat(), 0))
        conn.commit(); c.close(); conn.close()
    except psycopg.errors.UniqueViolation:
        return redirect("/?auth_error=Ese+email+ya+esta+registrado&tab=login")
    session["usuario"] = {"email": email, "nombre": nombre, "puntos": 0}
    return redirect(next_url)

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect("/")

# ===== RECUPERACIÓN DE CONTRASEÑA (CLIENTE) =====
@app.route("/recuperar-password", methods=["POST"])
def recuperar_password():
    email = request.form.get("email","").strip().lower()
    if not email or "@" not in email:
        return redirect("/?auth_error=Email+invalido&tab=login")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE email=%s", (email,))
    u = c.fetchone()
    if not u:
        # Por seguridad, no revelamos si el email existe o no
        c.close(); conn.close()
        return redirect("/?auth_info=Si+el+email+esta+registrado+recibirás+las+instrucciones&tab=login")
    token = secrets.token_urlsafe(32)
    expira = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
    c.execute("INSERT INTO password_resets (email,token,tipo,expira_en) VALUES (%s,%s,'usuario',%s)",
              (email, token, expira))
    conn.commit(); c.close(); conn.close()
    base_url = request.host_url.rstrip("/")
    link = f"{base_url}/reset-password?token={token}&tipo=usuario"
    cuerpo = f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:24px">
      <h2 style="color:#c0392b">TuMenú · Recuperar contraseña</h2>
      <p>Hola <strong>{u['nombre']}</strong>,</p>
      <p>Recibimos una solicitud para restablecer tu contraseña. Hacé click en el siguiente botón:</p>
      <a href="{link}" style="display:inline-block;background:#c0392b;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin:16px 0">
        Restablecer contraseña
      </a>
      <p style="color:#888;font-size:13px">Este enlace expira en 1 hora. Si no solicitaste esto, ignorá este mensaje.</p>
      <p style="color:#888;font-size:12px">O copiá este enlace: {link}</p>
    </div>"""
    ok = enviar_email(email, "TuMenú · Recuperar contraseña", cuerpo)
    if not ok:
        return redirect("/?auth_error=No+se+pudo+enviar+el+email.+Intenta+más+tarde&tab=login")
    return redirect("/?auth_info=Te+enviamos+un+email+con+las+instrucciones&tab=login")

@app.route("/reset-password", methods=["GET","POST"])
def reset_password():
    token = request.args.get("token","") or request.form.get("token","")
    tipo  = request.args.get("tipo","usuario") or request.form.get("tipo","usuario")
    if request.method == "GET":
        if not token:
            return redirect("/")
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM password_resets WHERE token=%s AND tipo=%s AND usado=FALSE", (token, tipo))
        reset = c.fetchone(); c.close(); conn.close()
        if not reset or reset["expira_en"] < datetime.datetime.now().isoformat():
            return "<h3 style='font-family:sans-serif;text-align:center;margin-top:60px;color:#c0392b'>Enlace inválido o expirado. Solicitá uno nuevo.</h3>"
        back = "/admin/login" if tipo == "admin" else "/"
        return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Nueva contraseña · TuMenú</title>
        <style>
          *{{box-sizing:border-box;margin:0;padding:0}}
          body{{font-family:'DM Sans',sans-serif;background:#0d0d0d;color:#f0f0f0;min-height:100vh;display:flex;align-items:center;justify-content:center}}
          .wrap{{width:100%;max-width:400px;padding:2rem}}
          .card{{background:#161616;border:1px solid #2a2a2a;border-radius:16px;padding:2rem}}
          h2{{font-size:1.1rem;margin-bottom:1.5rem;color:#f0f0f0}}
          .brand{{text-align:center;margin-bottom:2rem;font-size:1.5rem;font-weight:600}}
          .brand span{{color:#c0392b}}
          .field{{margin-bottom:1rem}}
          label{{display:block;font-size:.7rem;color:#777;letter-spacing:1px;text-transform:uppercase;margin-bottom:.3rem}}
          input{{width:100%;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;padding:.7rem 1rem;color:#f0f0f0;font-size:.95rem;outline:none}}
          input:focus{{border-color:#c0392b}}
          .btn{{width:100%;padding:.85rem;background:#c0392b;color:#fff;border:none;border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;margin-top:.5rem}}
          .btn:hover{{background:#e74c3c}}
          .error{{background:rgba(192,57,43,.12);border:1px solid rgba(192,57,43,.35);color:#f87171;border-radius:8px;padding:.6rem 1rem;font-size:.84rem;margin-bottom:1rem}}
        </style></head><body>
        <div class="wrap"><div class="brand">Tu<span>Menú</span></div>
        <div class="card"><h2>Nueva contraseña</h2>
        <form method="POST" action="/reset-password">
          <input type="hidden" name="token" value="{token}"/>
          <input type="hidden" name="tipo"  value="{tipo}"/>
          <div class="field"><label>Nueva contraseña</label><input type="password" name="password" minlength="6" required placeholder="Mínimo 6 caracteres"/></div>
          <div class="field"><label>Confirmar contraseña</label><input type="password" name="password2" minlength="6" required placeholder="Repetí la contraseña"/></div>
          <button type="submit" class="btn">Guardar nueva contraseña</button>
        </form></div></div></body></html>"""
    # POST
    password  = request.form.get("password","")
    password2 = request.form.get("password2","")
    if not password or len(password) < 6:
        return redirect(f"/reset-password?token={token}&tipo={tipo}&error=minlen")
    if password != password2:
        return redirect(f"/reset-password?token={token}&tipo={tipo}&error=mismatch")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM password_resets WHERE token=%s AND tipo=%s AND usado=FALSE", (token, tipo))
    reset = c.fetchone()
    if not reset or reset["expira_en"] < datetime.datetime.now().isoformat():
        c.close(); conn.close()
        return "<h3 style='font-family:sans-serif;text-align:center;margin-top:60px;color:#c0392b'>Enlace inválido o expirado.</h3>"
    tabla = "admins" if tipo == "admin" else "usuarios"
    c.execute(f"UPDATE {tabla} SET password=%s WHERE email=%s", (hashear(password), reset["email"]))
    c.execute("UPDATE password_resets SET usado=TRUE WHERE token=%s", (token,))
    conn.commit(); c.close(); conn.close()
    destino = "/admin/login?reset=ok" if tipo == "admin" else "/?auth_info=Contraseña+actualizada.+Ya+podés+iniciar+sesión&tab=login"
    return redirect(destino)

@app.route("/pedido", methods=["POST"])
def pedido():
    if not usuario_logueado(): return jsonify({"error":"no_auth"}), 401
    datos   = request.get_json()
    items   = datos.get("items", [])
    total   = datos.get("total", 0)
    tipo    = datos.get("tipo", "local")
    pago    = datos.get("pago", "efectivo")
    usuario = session["usuario"]
    if not items: return jsonify({"error":"Carrito vacio"}), 400
    puntos_ganados = total // get_puntos_por_peso()
    conn = get_db(); c = conn.cursor()
    c.execute("""INSERT INTO pedidos
                 (usuario_email,usuario_nombre,items,total,puntos_ganados,tipo,pago,estado,hora)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (usuario["email"], usuario["nombre"], json.dumps(items), total,
               puntos_ganados, tipo, pago, "pendiente",
               datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
    c.execute("UPDATE usuarios SET puntos = puntos + %s WHERE email = %s",
              (puntos_ganados, usuario["email"]))
    conn.commit()
    c.execute("SELECT puntos FROM usuarios WHERE email=%s", (usuario["email"],))
    nuevos_puntos = c.fetchone()["puntos"]
    c.close(); conn.close()
    usuario["puntos"] = nuevos_puntos
    session["usuario"] = usuario
    return jsonify({"ok": True, "puntos_ganados": puntos_ganados, "puntos_total": nuevos_puntos})

@app.route("/canjear", methods=["POST"])
def canjear():
    if not usuario_logueado(): return jsonify({"error":"no_auth"}), 401
    datos = request.get_json()
    beneficio_id = datos.get("beneficio_id")
    usuario = session["usuario"]
    conn2 = get_db(); c2 = conn2.cursor()
    c2.execute("SELECT * FROM beneficios WHERE id=%s AND activo=TRUE", (beneficio_id,))
    beneficio = c2.fetchone(); c2.close(); conn2.close()
    if not beneficio: return jsonify({"error":"Beneficio no encontrado"}), 404
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT puntos FROM usuarios WHERE email=%s", (usuario["email"],))
    puntos_actuales = c.fetchone()["puntos"]
    if puntos_actuales < beneficio["puntos"]:
        c.close(); conn.close()
        return jsonify({"error":"Puntos insuficientes"}), 400
    c.execute("UPDATE usuarios SET puntos = puntos - %s WHERE email = %s",
              (beneficio["puntos"], usuario["email"]))
    c.execute("""INSERT INTO canjes (usuario_email,beneficio_id,beneficio_nombre,puntos_usados,hora)
                 VALUES (%s,%s,%s,%s,%s)""",
              (usuario["email"], beneficio_id, beneficio["nombre"], beneficio["puntos"],
               datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
    conn.commit()
    c.execute("SELECT puntos FROM usuarios WHERE email=%s", (usuario["email"],))
    nuevos_puntos = c.fetchone()["puntos"]
    c.close(); conn.close()
    usuario["puntos"] = nuevos_puntos
    session["usuario"] = usuario
    return jsonify({"ok": True, "puntos_restantes": nuevos_puntos, "beneficio": beneficio["nombre"]})

# ===== MERCADO PAGO =====
@app.route("/mp/crear-preferencia", methods=["POST"])
def mp_crear_preferencia():
    if not usuario_logueado(): return jsonify({"error":"no_auth"}), 401
    datos   = request.get_json()
    items   = datos.get("items", [])
    total   = datos.get("total", 0)
    tipo    = datos.get("tipo", "local")
    usuario = session["usuario"]
    if not items: return jsonify({"error":"Carrito vacio"}), 400
    base_url = request.host_url.rstrip("/")
    mp_items = [{"title": i["nombre"], "quantity": i["cantidad"],
                 "unit_price": float(i["precio"]), "currency_id": "ARS"}
                for i in items]
    back_urls = {
        "success": base_url + "/mp/exito",
        "failure": base_url + "/mp/fallo",
        "pending": base_url + "/mp/pendiente"
    }
    status, pref = mp_api_preferencia(
        mp_items, usuario["email"], back_urls,
        usuario["email"]+"|"+tipo+"|"+datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
        base_url+"/mp/webhook"
    )
    if status not in (200, 201):
        print("MP ERROR:", status, pref)
        return jsonify({"error": "Error creando preferencia MP", "detalle": pref}), 500
    conn = get_db(); c = conn.cursor()
    c.execute("""INSERT INTO pagos_mp (preference_id, estado, tipo, total, usuario_email, hora)
                 VALUES (%s, %s, %s, %s, %s, %s)""",
              (pref["id"], "pendiente", "checkout", total, usuario["email"],
               datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
    conn.commit(); c.close(); conn.close()
    return jsonify({"init_point": pref["init_point"], "preference_id": pref["id"]})

@app.route("/mp/exito")
def mp_exito():
    payment_id    = request.args.get("payment_id","")
    status        = request.args.get("status","")
    preference_id = request.args.get("preference_id","")
    if status == "approved" and payment_id:
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE pagos_mp SET estado=%s, payment_id=%s WHERE preference_id=%s",
                  ("aprobado", payment_id, preference_id))
        conn.commit(); c.close(); conn.close()
    return redirect("/?pago=exito&payment_id=" + payment_id)

@app.route("/mp/fallo")
def mp_fallo():
    return redirect("/?pago=fallo")

@app.route("/mp/pendiente")
def mp_pendiente():
    return redirect("/?pago=pendiente")

@app.route("/mp/webhook", methods=["POST"])
def mp_webhook():
    data = request.get_json(silent=True) or {}
    topic = data.get("type") or request.args.get("topic","")
    resource_id = data.get("data",{}).get("id") or request.args.get("id","")
    if topic == "payment" and resource_id:
        status, payment = mp_get(f"v1/payments/{resource_id}")
        if status == 200:
            estado_mp   = payment.get("status","")
            pref_id     = payment.get("preference_id","")
            total       = int(payment.get("transaction_amount", 0))
            payer_email = payment.get("payer",{}).get("email","")
            ext_ref     = payment.get("external_reference","") or ""
            conn = get_db(); c = conn.cursor()
            c.execute("UPDATE pagos_mp SET estado=%s, payment_id=%s WHERE preference_id=%s",
                      (estado_mp, str(resource_id), pref_id))
            if estado_mp == "approved":
                c.execute("SELECT id FROM pedidos WHERE pago=%s AND usuario_email=%s AND total=%s",
                          ("mercadopago", payer_email, total))
                if not c.fetchone():
                    tipo = "local"
                    if ext_ref and "|" in ext_ref:
                        partes = ext_ref.split("|")
                        if len(partes) >= 2:
                            tipo = partes[1]
                    items_json = json.dumps([{"nombre":"Pago Mercado Pago","cantidad":1,"precio":total}])
                    puntos_ganados = total // get_puntos_por_peso()
                    hora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    c.execute(
                        "INSERT INTO pedidos (usuario_email,usuario_nombre,items,total,puntos_ganados,tipo,pago,estado,hora) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (payer_email, payer_email, items_json, total, puntos_ganados, tipo, "mercadopago", "pendiente", hora)
                    )
                    c.execute("UPDATE usuarios SET puntos = puntos + %s WHERE email = %s",
                              (puntos_ganados, payer_email))
            conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True}), 200

# ===== RUTAS ADMIN =====
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

# ===== RECUPERACIÓN DE CONTRASEÑA (ADMIN) =====
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
    c.execute("INSERT INTO password_resets (email,token,tipo,expira_en) VALUES (%s,%s,'admin',%s)",
              (email, token, expira))
    conn.commit(); c.close(); conn.close()
    base_url = request.host_url.rstrip("/")
    link = f"{base_url}/reset-password?token={token}&tipo=admin"
    cuerpo = f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:24px">
      <h2 style="color:#c0392b">TuMenú · Panel Admin · Recuperar contraseña</h2>
      <p>Hola <strong>{a['nombre']}</strong>,</p>
      <p>Recibimos una solicitud para restablecer tu contraseña de administrador.</p>
      <a href="{link}" style="display:inline-block;background:#c0392b;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin:16px 0">
        Restablecer contraseña
      </a>
      <p style="color:#888;font-size:13px">Este enlace expira en 1 hora. Si no solicitaste esto, ignorá este mensaje.</p>
      <p style="color:#888;font-size:12px">O copiá este enlace: {link}</p>
    </div>"""
    ok = enviar_email(email, "TuMenú Admin · Recuperar contraseña", cuerpo)
    if not ok:
        return redirect("/admin/login?error=No+se+pudo+enviar+el+email.+Intenta+más+tarde")
    return redirect("/admin/login?info=Te+enviamos+un+email+con+las+instrucciones")

@app.route("/admin/panel")
def admin_panel():
    if not admin_logueado(): return redirect("/admin/login")
    return render_template("admin_panel.html", admin=admin_logueado())

@app.route("/admin/api/pedidos")
def admin_api_pedidos():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    estado = request.args.get("estado","todos")
    conn = get_db(); c = conn.cursor()
    if estado == "todos":
        c.execute("SELECT * FROM pedidos ORDER BY id DESC LIMIT 100")
    else:
        c.execute("SELECT * FROM pedidos WHERE estado=%s ORDER BY id DESC LIMIT 100", (estado,))
    rows = c.fetchall(); c.close(); conn.close()
    pedidos = []
    for r in rows:
        pedidos.append({
            "id":             r["id"],
            "usuario_nombre": r["usuario_nombre"],
            "usuario_email":  r["usuario_email"],
            "items":          json.loads(r["items"]),
            "total":          r["total"],
            "puntos_ganados": r["puntos_ganados"],
            "tipo":           r["tipo"],
            "pago":           r["pago"],
            "estado":         r["estado"],
            "hora":           r["hora"],
        })
    return jsonify(pedidos)

@app.route("/admin/api/pedidos/<int:pid>/estado", methods=["POST"])
def admin_cambiar_estado(pid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    datos = request.get_json()
    nuevo_estado = datos.get("estado")
    if nuevo_estado not in ("pendiente", "en_preparacion", "listo", "entregado"):
        return jsonify({"error":"Estado invalido"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE pedidos SET estado=%s WHERE id=%s", (nuevo_estado, pid))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/stats")
def admin_stats():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    hoy = datetime.datetime.now().strftime("%d/%m/%Y")
    c.execute("SELECT COALESCE(SUM(total),0) as t FROM pedidos WHERE hora LIKE %s", (hoy+"%",))
    total_hoy = c.fetchone()["t"]
    c.execute("SELECT COUNT(*) as cnt FROM pedidos WHERE hora LIKE %s", (hoy+"%",))
    cant_hoy = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM pedidos WHERE estado='pendiente'")
    pendientes = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM pedidos WHERE estado='en_preparacion'")
    en_prep = c.fetchone()["cnt"]
    c.close(); conn.close()
    return jsonify({"total_hoy": total_hoy, "cant_hoy": cant_hoy,
                    "pendientes": pendientes, "en_preparacion": en_prep})

@app.route("/admin/api/usuarios")
def admin_api_usuarios():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT
            u.id, u.nombre, u.email, u.creado_en, u.puntos,
            COUNT(p.id) AS cantidad_pedidos,
            COALESCE(SUM(p.total), 0) AS total_gastado
        FROM usuarios u
        LEFT JOIN pedidos p ON p.usuario_email = u.email
        GROUP BY u.id, u.nombre, u.email, u.creado_en, u.puntos
        ORDER BY u.id DESC
    """)
    rows = c.fetchall(); c.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/admin/api/usuarios/<int:uid>", methods=["DELETE"])
def admin_eliminar_usuario(uid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT email FROM usuarios WHERE id=%s", (uid,))
    u = c.fetchone()
    if not u:
        c.close(); conn.close()
        return jsonify({"error":"Usuario no encontrado"}), 404
    email = u["email"]
    c.execute("DELETE FROM pedidos WHERE usuario_email=%s", (email,))
    c.execute("DELETE FROM canjes WHERE usuario_email=%s", (email,))
    c.execute("DELETE FROM pagos_mp WHERE usuario_email=%s", (email,))
    c.execute("DELETE FROM usuarios WHERE id=%s", (uid,))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/beneficios")
def admin_get_beneficios():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM beneficios ORDER BY puntos ASC")
    rows = c.fetchall(); c.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/admin/api/beneficios", methods=["POST"])
def admin_crear_beneficio():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    nombre = d.get("nombre","").strip()
    descripcion = d.get("descripcion","").strip()
    puntos = int(d.get("puntos", 0))
    emoji = d.get("emoji","").strip()
    if not nombre or not descripcion or puntos <= 0:
        return jsonify({"error":"Datos invalidos"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO beneficios (nombre,descripcion,puntos,emoji) VALUES (%s,%s,%s,%s) RETURNING id",
              (nombre, descripcion, puntos, emoji))
    new_id = c.fetchone()["id"]
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True, "id": new_id})

@app.route("/admin/api/beneficios/<int:bid>", methods=["PUT"])
def admin_editar_beneficio(bid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    nombre = d.get("nombre","").strip()
    descripcion = d.get("descripcion","").strip()
    puntos = int(d.get("puntos", 0))
    emoji = d.get("emoji","").strip()
    activo = d.get("activo", True)
    if not nombre or not descripcion or puntos <= 0:
        return jsonify({"error":"Datos invalidos"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE beneficios SET nombre=%s,descripcion=%s,puntos=%s,emoji=%s,activo=%s WHERE id=%s",
              (nombre, descripcion, puntos, emoji, activo, bid))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/beneficios/<int:bid>", methods=["DELETE"])
def admin_eliminar_beneficio(bid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE beneficios SET activo=FALSE WHERE id=%s", (bid,))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/admin/api/config", methods=["GET"])
def admin_get_config():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM config")
    rows = c.fetchall(); c.close(); conn.close()
    return jsonify({r["clave"]: r["valor"] for r in rows})

@app.route("/admin/api/config", methods=["POST"])
def admin_set_config():
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    conn = get_db(); c = conn.cursor()
    for clave, valor in d.items():
        c.execute("INSERT INTO config (clave,valor) VALUES (%s,%s) ON CONFLICT (clave) DO UPDATE SET valor=%s",
                  (clave, str(valor), str(valor)))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})

# ===== ADMIN MENU =====
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
    emoji           = d.get("emoji","").strip()
    subcategoria_id = int(d.get("subcategoria_id", 0))
    if not nombre or precio <= 0 or not subcategoria_id:
        return jsonify({"error":"Datos invalidos"}), 400
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(orden),0)+1 as o FROM menu_items WHERE subcategoria_id=%s", (subcategoria_id,))
    orden = c.fetchone()["o"]
    c.execute("INSERT INTO menu_items (subcategoria_id,nombre,descripcion,precio,emoji,orden) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
              (subcategoria_id, nombre, descripcion, precio, emoji, orden))
    new_id = c.fetchone()["id"]
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True, "id": new_id})

@app.route("/admin/api/menu/items/<int:iid>", methods=["PUT"])
def admin_editar_item(iid):
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    d = request.get_json()
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE menu_items SET nombre=%s,descripcion=%s,precio=%s,emoji=%s,activo=%s WHERE id=%s",
              (d.get("nombre",""), d.get("desc",""), int(d.get("precio",0)),
               d.get("emoji",""), d.get("activo",True), iid))
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

@app.route("/admin/api/canjes")
def admin_api_canjes():
    """Historial de canjes de puntos."""
    if not admin_logueado(): return jsonify({"error":"no_auth"}), 401
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT c.id, c.usuario_email, u.nombre as usuario_nombre,
               c.beneficio_nombre, c.puntos_usados, c.hora
        FROM canjes c
        LEFT JOIN usuarios u ON u.email = c.usuario_email
        ORDER BY c.id DESC
        LIMIT 200
    """)
    rows = c.fetchall(); c.close(); conn.close()
    return jsonify([dict(r) for r in rows])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
