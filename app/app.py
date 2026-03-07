import os
import psycopg2
import json
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template_string
import boto3

app = Flask(__name__)

# ─────────────────────────────────────────────
#  DB helpers
# ─────────────────────────────────────────────

def get_db_connection():
    """Fetch DB credentials from Secrets Manager and connect."""
    client = boto3.client('secretsmanager', region_name=os.environ['AWS_REGION'])
    secret = json.loads(
        client.get_secret_value(SecretId=os.environ['DB_SECRET_ARN'])['SecretString']
    )
    return psycopg2.connect(
        host=secret['host'],
        port=secret['port'],
        dbname=secret['dbname'],
        user=secret['username'],
        password=secret['password']
    )


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(150) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()


# ─────────────────────────────────────────────
#  API routes
# ─────────────────────────────────────────────

@app.route('/users', methods=['GET'])
def get_users():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, name, email, created_at FROM users')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    users = [{'id': r[0], 'name': r[1], 'email': r[2], 'created_at': str(r[3])} for r in rows]
    return jsonify(users), 200


@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO users (name, email) VALUES (%s, %s) RETURNING id',
        (data['name'], data['email'])
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'id': new_id, 'name': data['name'], 'email': data['email']}), 201


# ─────────────────────────────────────────────
#  Health check — ALB uses /health?format=json
#  Browser hitting /health gets the status page
# ─────────────────────────────────────────────

HEALTH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<meta http-equiv="refresh" content="30">
<title>NexaFlow — System Status</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --ink:    #0d0d14;
    --cream:  #faf9f6;
    --fog:    #f4f3f0;
    --card:   #ffffff;
    --border: rgba(13,13,20,.08);
    --muted:  #8a8a9a;
    --accent: #2a5cff;
    --green:  #00e5b4;
    --red:    #ff4d6d;
    --yellow: #ffbd2e;
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }

  body {
    font-family: 'DM Sans', sans-serif;
    background: var(--cream);
    color: var(--ink);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* ── NAV (matches landing page) ── */
  nav {
    position: fixed; top: 0; left: 0; right: 0; z-index: 100;
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 6vw;
    background: rgba(250,249,246,.82);
    backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--border);
  }
  .logo {
    font-family: 'Syne', sans-serif;
    font-weight: 800; font-size: 1.25rem; letter-spacing: -.02em;
    color: var(--ink); text-decoration: none;
  }
  .logo span { color: var(--accent); }
  .back-link {
    font-size: .875rem; color: var(--muted); text-decoration: none;
    display: flex; align-items: center; gap: 6px;
    transition: color .2s;
  }
  .back-link:hover { color: var(--ink); }

  /* ── MAIN ── */
  main {
    flex: 1;
    padding: 120px 6vw 80px;
    max-width: 860px;
    margin: 0 auto;
    width: 100%;
  }

  /* ── PAGE HEADER ── */
  .page-header {
    margin-bottom: 48px;
    animation: fadeUp .5s ease both;
  }
  .page-label {
    font-size: .75rem; font-weight: 600; letter-spacing: .12em;
    text-transform: uppercase; color: var(--accent);
    margin-bottom: 10px;
    display: block;
  }
  .page-title {
    font-family: 'Syne', sans-serif;
    font-size: clamp(1.8rem, 3vw, 2.6rem);
    font-weight: 800; letter-spacing: -.03em;
    line-height: 1.1;
  }
  .page-subtitle {
    margin-top: 10px;
    color: var(--muted); font-size: .95rem; line-height: 1.6;
  }

  /* ── OVERALL STATUS BANNER ── */
  .status-banner {
    display: flex; align-items: center; gap: 16px;
    padding: 20px 24px;
    border-radius: 14px;
    margin-bottom: 32px;
    border: 1px solid;
    animation: fadeUp .5s .1s ease both;
  }
  .status-banner.ok {
    background: rgba(0,229,180,.06);
    border-color: rgba(0,229,180,.25);
  }
  .status-banner.degraded {
    background: rgba(255,189,46,.06);
    border-color: rgba(255,189,46,.3);
  }
  .status-banner.down {
    background: rgba(255,77,109,.06);
    border-color: rgba(255,77,109,.25);
  }
  .banner-icon {
    width: 44px; height: 44px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.3rem; flex-shrink: 0;
  }
  .ok .banner-icon    { background: rgba(0,229,180,.15); }
  .degraded .banner-icon { background: rgba(255,189,46,.15); }
  .down .banner-icon  { background: rgba(255,77,109,.15); }
  .banner-text h3 {
    font-family: 'Syne', sans-serif;
    font-size: 1rem; font-weight: 700;
  }
  .ok .banner-text h3    { color: #00a884; }
  .degraded .banner-text h3 { color: #b07d00; }
  .down .banner-text h3  { color: #cc2244; }
  .banner-text p { font-size: .82rem; color: var(--muted); margin-top: 2px; }
  .banner-time {
    margin-left: auto;
    font-family: 'DM Mono', monospace;
    font-size: .75rem; color: var(--muted);
    text-align: right; flex-shrink: 0;
  }
  .banner-time strong { display: block; color: var(--ink); font-size: .8rem; }

  /* ── COMPONENT GRID ── */
  .components-label {
    font-size: .75rem; font-weight: 600; letter-spacing: .1em;
    text-transform: uppercase; color: var(--muted);
    margin-bottom: 14px;
    animation: fadeUp .5s .15s ease both;
  }
  .components {
    display: flex; flex-direction: column; gap: 10px;
    margin-bottom: 40px;
    animation: fadeUp .5s .2s ease both;
  }
  .component-row {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
    display: flex; align-items: center; gap: 14px;
    transition: box-shadow .2s;
  }
  .component-row:hover { box-shadow: 0 4px 20px rgba(0,0,0,.05); }
  .comp-icon {
    width: 36px; height: 36px;
    background: var(--fog); border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem; flex-shrink: 0;
  }
  .comp-info { flex: 1; min-width: 0; }
  .comp-name {
    font-family: 'Syne', sans-serif;
    font-weight: 700; font-size: .9rem;
  }
  .comp-desc { font-size: .78rem; color: var(--muted); margin-top: 2px; }
  .comp-badge {
    display: flex; align-items: center; gap: 6px;
    padding: 5px 12px; border-radius: 100px;
    font-size: .75rem; font-weight: 600;
    flex-shrink: 0;
  }
  .comp-badge.ok    { background: rgba(0,229,180,.1);  color: #00a884; }
  .comp-badge.down  { background: rgba(255,77,109,.1); color: #cc2244; }
  .comp-badge.unknown { background: rgba(255,189,46,.1); color: #b07d00; }
  .badge-dot {
    width: 6px; height: 6px; border-radius: 50%;
  }
  .ok .badge-dot    { background: var(--green); box-shadow: 0 0 6px var(--green); animation: pulse 2s ease infinite; }
  .down .badge-dot  { background: var(--red); }
  .unknown .badge-dot { background: var(--yellow); }

  @keyframes pulse {
    0%,100% { opacity:1; } 50% { opacity:.3; }
  }

  /* ── METRICS ROW ── */
  .metrics {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 40px;
    animation: fadeUp .5s .25s ease both;
  }
  .metric-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
  }
  .metric-label {
    font-size: .72rem; font-weight: 600; letter-spacing: .08em;
    text-transform: uppercase; color: var(--muted);
    margin-bottom: 8px;
  }
  .metric-value {
    font-family: 'Syne', sans-serif;
    font-size: 1.5rem; font-weight: 800;
    letter-spacing: -.03em; color: var(--ink);
  }
  .metric-value span { color: var(--accent); }
  .metric-sub { font-size: .75rem; color: var(--muted); margin-top: 2px; }

  /* ── RAW JSON BLOCK ── */
  .raw-section {
    animation: fadeUp .5s .3s ease both;
  }
  .raw-label {
    font-size: .75rem; font-weight: 600; letter-spacing: .1em;
    text-transform: uppercase; color: var(--muted);
    margin-bottom: 14px;
  }
  .terminal {
    background: var(--ink);
    border-radius: 14px; overflow: hidden;
    border: 1px solid rgba(255,255,255,.06);
  }
  .terminal-bar {
    padding: 12px 16px;
    background: rgba(255,255,255,.04);
    border-bottom: 1px solid rgba(255,255,255,.07);
    display: flex; align-items: center; gap: 6px;
  }
  .t-dot { width: 11px; height: 11px; border-radius: 50%; }
  .t-dot.r { background: #ff5f57; }
  .t-dot.y { background: #ffbd2e; }
  .t-dot.g { background: #28c840; }
  .terminal-bar span {
    margin-left: 8px; color: rgba(255,255,255,.3);
    font-family: 'DM Mono', monospace; font-size: .72rem;
  }
  .terminal-body {
    padding: 20px 24px;
    font-family: 'DM Mono', monospace;
    font-size: .82rem; line-height: 1.9;
  }
  .t-key   { color: #a78bfa; }
  .t-ok    { color: var(--green); }
  .t-warn  { color: var(--yellow); }
  .t-str   { color: #f9a8d4; }
  .t-num   { color: #fdba74; }
  .t-dim   { color: rgba(255,255,255,.25); }
  .t-url   { color: var(--green); }

  /* ── REFRESH NOTE ── */
  .refresh-note {
    margin-top: 24px;
    text-align: center;
    font-size: .78rem; color: var(--muted);
    animation: fadeUp .5s .35s ease both;
  }

  /* ── FOOTER ── */
  footer {
    padding: 24px 6vw;
    border-top: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 12px;
    font-size: .8rem; color: var(--muted);
  }

  @keyframes fadeUp {
    from { opacity:0; transform: translateY(16px); }
    to   { opacity:1; transform: translateY(0); }
  }

  @media (max-width: 600px) {
    .banner-time { display: none; }
    .metrics { grid-template-columns: 1fr 1fr; }
  }
</style>
</head>
<body>

<nav>
  <a class="logo" href="/"><span>Nexa</span>Flow</a>
  <a class="back-link" href="/">← Back to home</a>
</nav>

<main>

  <!-- PAGE HEADER -->
  <div class="page-header">
    <span class="page-label">System Status</span>
    <h1 class="page-title">All systems operational</h1>
    <p class="page-subtitle">
      Live health data for NexaFlow infrastructure &mdash;
      auto-refreshes every 30 seconds.
    </p>
  </div>

  <!-- OVERALL BANNER -->
  <div class="status-banner {{ banner_class }}">
    <div class="banner-icon">{{ banner_icon }}</div>
    <div class="banner-text">
      <h3>{{ banner_title }}</h3>
      <p>{{ banner_desc }}</p>
    </div>
    <div class="banner-time">
      <strong>{{ current_time }}</strong>
      UTC &middot; eu-north-1
    </div>
  </div>

  <!-- COMPONENTS -->
  <div class="components-label">Components</div>
  <div class="components">

    <div class="component-row">
      <div class="comp-icon">🌐</div>
      <div class="comp-info">
        <div class="comp-name">Application Layer</div>
        <div class="comp-desc">Flask / Gunicorn &middot; eu-north-1 &middot; Private App Subnet</div>
      </div>
      <div class="comp-badge ok">
        <div class="badge-dot"></div>
        Operational
      </div>
    </div>

    <div class="component-row">
      <div class="comp-icon">🗄️</div>
      <div class="comp-info">
        <div class="comp-name">Database (RDS PostgreSQL)</div>
        <div class="comp-desc">db.t4g.micro &middot; Private DB Subnet &middot; Encrypted at rest</div>
      </div>
      <div class="comp-badge {{ db_badge_class }}">
        <div class="badge-dot"></div>
        {{ db_status_text }}
      </div>
    </div>

    <div class="component-row">
      <div class="comp-icon">⚖️</div>
      <div class="comp-info">
        <div class="comp-name">Load Balancer (ALB)</div>
        <div class="comp-desc">Application Load Balancer &middot; Public Subnet &middot; HTTP:80</div>
      </div>
      <div class="comp-badge ok">
        <div class="badge-dot"></div>
        Operational
      </div>
    </div>

    <div class="component-row">
      <div class="comp-icon">🌍</div>
      <div class="comp-info">
        <div class="comp-name">DR Region (eu-west-1)</div>
        <div class="comp-desc">Cross-region RDS replica &middot; Standby ASG &middot; Route53 failover</div>
      </div>
      <div class="comp-badge ok">
        <div class="badge-dot"></div>
        Standby Ready
      </div>
    </div>

  </div>

  <!-- METRICS -->
  <div class="metrics">
    <div class="metric-card">
      <div class="metric-label">Response Time</div>
      <div class="metric-value">{{ response_ms }}<span>ms</span></div>
      <div class="metric-sub">This request</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Region</div>
      <div class="metric-value" style="font-size:1.1rem">eu-north<span>-1</span></div>
      <div class="metric-sub">Stockholm, Sweden</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Database</div>
      <div class="metric-value" style="font-size:1rem; color:{{ db_color }}">{{ db_label }}</div>
      <div class="metric-sub">PostgreSQL 15</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Uptime SLA</div>
      <div class="metric-value">99<span>.99%</span></div>
      <div class="metric-sub">Rolling 30 days</div>
    </div>
  </div>

  <!-- RAW JSON -->
  <div class="raw-section">
    <div class="raw-label">Raw API Response</div>
    <div class="terminal">
      <div class="terminal-bar">
        <div class="t-dot r"></div>
        <div class="t-dot y"></div>
        <div class="t-dot g"></div>
        <span>GET /health — {{ current_time }} UTC</span>
      </div>
      <div class="terminal-body">
        <div><span class="t-dim">$ </span><span class="t-url">curl https://app.nexaflow.io/health</span></div>
        <div>&nbsp;</div>
        <div><span class="t-dim">{</span></div>
        <div>&nbsp; <span class="t-key">"status"</span><span class="t-dim">:</span> <span class="{{ status_color }}">"{{ status }}"</span><span class="t-dim">,</span></div>
        <div>&nbsp; <span class="t-key">"db"</span><span class="t-dim">:</span> <span class="{{ db_color_class }}">"{{ db }}"</span><span class="t-dim">,</span></div>
        <div>&nbsp; <span class="t-key">"region"</span><span class="t-dim">:</span> <span class="t-str">"eu-north-1"</span><span class="t-dim">,</span></div>
        <div>&nbsp; <span class="t-key">"checked_at"</span><span class="t-dim">:</span> <span class="t-str">"{{ current_time }} UTC"</span></div>
        <div><span class="t-dim">}</span></div>
        <div>&nbsp;</div>
        <div><span class="t-dim">HTTP </span><span class="{{ status_color }}">{{ http_code }}</span><span class="t-dim"> — {{ response_ms }}ms</span></div>
      </div>
    </div>
  </div>

  <p class="refresh-note">⟳ &nbsp;This page auto-refreshes every 30 seconds &nbsp;&middot;&nbsp; <a href="/health" style="color:var(--muted)">Force refresh</a></p>

</main>

<footer>
  <span><strong style="font-family:'Syne',sans-serif;">NexaFlow</strong> &copy; 2025</span>
  <span>Built on AWS &middot; Flask &middot; Terraform</span>
  <span><a href="/" style="color:var(--muted);text-decoration:none;">← Home</a></span>
</footer>

</body>
</html>"""


@app.route('/health')
def health():
    """
    ALB health check + human-readable status page.
    ALB calls /health?format=json  → returns raw JSON (200 or 500)
    Browser visits /health          → returns styled status page
    """
    t_start = time.time()

    # Check DB
    db_ok = False
    db_msg = "disconnected"
    try:
        conn = get_db_connection()
        conn.close()
        db_ok = True
        db_msg = "connected"
    except Exception as e:
        db_msg = str(e)

    response_ms = round((time.time() - t_start) * 1000)
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    overall_ok = db_ok

    # ALB / programmatic callers get plain JSON
    if request.args.get('format') == 'json' or \
       'curl' in request.headers.get('User-Agent', '').lower() or \
       request.headers.get('Accept', '') == 'application/json':
        payload = {'status': 'healthy' if overall_ok else 'unhealthy', 'db': db_msg}
        return jsonify(payload), 200 if overall_ok else 500

    # Browser gets the styled page
    return render_template_string(
        HEALTH_HTML,
        status        = 'healthy'      if overall_ok else 'unhealthy',
        db            = db_msg,
        http_code     = '200 OK'       if overall_ok else '500 Internal Server Error',
        status_color  = 't-ok'         if overall_ok else 'warn',
        db_badge_class= 'ok'           if db_ok      else 'down',
        db_status_text= 'Connected'    if db_ok      else 'Unreachable',
        db_color      = '#00a884'      if db_ok      else '#cc2244',
        db_label      = 'Connected'    if db_ok      else 'Down',
        db_color_class= 't-ok'         if db_ok      else 'warn',
        banner_class  = 'ok'           if overall_ok else 'down',
        banner_icon   = '✅'           if overall_ok else '🔴',
        banner_title  = 'All Systems Operational' if overall_ok else 'Service Degraded',
        banner_desc   = 'Application and database are healthy and serving traffic.' \
                        if overall_ok else \
                        'One or more components are experiencing issues.',
        current_time  = current_time,
        response_ms   = response_ms,
    ), 200 if overall_ok else 500


# ─────────────────────────────────────────────
#  Landing page  (unchanged)
# ─────────────────────────────────────────────

LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>NexaFlow — Resilient Infrastructure, Effortlessly</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;1,300&display=swap" rel="stylesheet">
<style>
  :root {
    --ink:   #0d0d14;
    --fog:   #f4f3f0;
    --cream: #faf9f6;
    --accent:#2a5cff;
    --accent2:#00e5b4;
    --muted: #8a8a9a;
    --card:  #ffffff;
    --border:rgba(13,13,20,.08);
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  html { scroll-behavior: smooth; }

  body {
    font-family: 'DM Sans', sans-serif;
    background: var(--cream);
    color: var(--ink);
    overflow-x: hidden;
  }

  /* ── NAV ── */
  nav {
    position: fixed; top: 0; left: 0; right: 0; z-index: 100;
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 6vw;
    background: rgba(250,249,246,.82);
    backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--border);
  }
  .logo {
    font-family: 'Syne', sans-serif;
    font-weight: 800; font-size: 1.25rem; letter-spacing: -.02em;
    color: var(--ink); text-decoration: none;
  }
  .logo span { color: var(--accent); }
  .nav-links { display: flex; gap: 32px; list-style: none; }
  .nav-links a {
    font-size: .875rem; font-weight: 500; color: var(--muted);
    text-decoration: none; transition: color .2s;
  }
  .nav-links a:hover { color: var(--ink); }
  .nav-cta {
    background: var(--ink); color: #fff;
    padding: 10px 20px; border-radius: 8px;
    font-size: .875rem; font-weight: 500; text-decoration: none;
    transition: opacity .2s;
  }
  .nav-cta:hover { opacity: .8; }

  /* ── HERO ── */
  .hero {
    min-height: 100vh;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 120px 6vw 80px;
    text-align: center;
    position: relative;
    overflow: hidden;
  }
  .hero-badge {
    display: inline-flex; align-items: center; gap: 8px;
    background: var(--fog); border: 1px solid var(--border);
    border-radius: 100px; padding: 6px 14px;
    font-size: .75rem; font-weight: 500; color: var(--muted);
    margin-bottom: 28px;
    animation: fadeUp .6s ease both;
  }
  .badge-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--accent2);
    box-shadow: 0 0 8px var(--accent2);
    animation: pulse 2s ease infinite;
  }
  @keyframes pulse {
    0%,100% { opacity: 1; } 50% { opacity: .4; }
  }
  h1 {
    font-family: 'Syne', sans-serif;
    font-size: clamp(2.6rem, 6vw, 5rem);
    font-weight: 800; line-height: 1.06; letter-spacing: -.03em;
    max-width: 820px;
    animation: fadeUp .6s .1s ease both;
  }
  h1 em { font-style: normal; color: var(--accent); }
  .hero-sub {
    margin-top: 20px;
    font-size: clamp(1rem, 1.6vw, 1.2rem);
    color: var(--muted); max-width: 560px; line-height: 1.6;
    animation: fadeUp .6s .2s ease both;
  }
  .hero-actions {
    margin-top: 36px; display: flex; gap: 14px; flex-wrap: wrap;
    justify-content: center;
    animation: fadeUp .6s .3s ease both;
  }
  .btn-primary {
    background: var(--accent); color: #fff;
    padding: 14px 28px; border-radius: 10px;
    font-size: .95rem; font-weight: 500; text-decoration: none;
    transition: transform .2s, box-shadow .2s;
    box-shadow: 0 4px 24px rgba(42,92,255,.3);
  }
  .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(42,92,255,.4); }
  .btn-ghost {
    background: transparent; color: var(--ink);
    padding: 14px 28px; border-radius: 10px;
    font-size: .95rem; font-weight: 500; text-decoration: none;
    border: 1px solid var(--border);
    transition: background .2s;
  }
  .btn-ghost:hover { background: var(--fog); }

  .hero::before {
    content: '';
    position: absolute; inset: 0;
    background-image:
      linear-gradient(var(--border) 1px, transparent 1px),
      linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 60px 60px;
    mask-image: radial-gradient(ellipse 80% 60% at 50% 40%, black 40%, transparent 100%);
    z-index: -1;
  }
  .blob {
    position: absolute; border-radius: 50%;
    filter: blur(80px); pointer-events: none; z-index: -2;
  }
  .blob-1 {
    width: 500px; height: 500px;
    background: rgba(42,92,255,.12);
    top: -100px; right: -100px;
    animation: drift 8s ease-in-out infinite alternate;
  }
  .blob-2 {
    width: 400px; height: 400px;
    background: rgba(0,229,180,.1);
    bottom: -80px; left: -80px;
    animation: drift 10s ease-in-out infinite alternate-reverse;
  }
  @keyframes drift {
    from { transform: translate(0,0); }
    to   { transform: translate(30px, 20px); }
  }

  .status-pill {
    margin-top: 48px;
    display: inline-flex; align-items: center; gap: 8px;
    background: var(--card); border: 1px solid var(--border);
    border-radius: 100px; padding: 8px 18px;
    font-size: .8rem; color: var(--muted);
    animation: fadeUp .6s .4s ease both;
    box-shadow: 0 2px 12px rgba(0,0,0,.05);
  }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--accent2);
  }

  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(20px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .logos {
    padding: 40px 6vw;
    display: flex; flex-direction: column; align-items: center; gap: 20px;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
  }
  .logos p { font-size: .8rem; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; }
  .logo-row { display: flex; gap: 48px; flex-wrap: wrap; justify-content: center; align-items: center; }
  .logo-brand {
    font-family: 'Syne', sans-serif;
    font-weight: 700; font-size: 1rem;
    color: var(--muted); letter-spacing: -.01em;
    opacity: .5;
  }

  .section { padding: 100px 6vw; }
  .section-label {
    display: inline-block;
    font-size: .75rem; font-weight: 600; letter-spacing: .12em;
    text-transform: uppercase; color: var(--accent);
    margin-bottom: 12px;
  }
  .section-title {
    font-family: 'Syne', sans-serif;
    font-size: clamp(1.8rem, 3.5vw, 2.8rem);
    font-weight: 800; letter-spacing: -.025em;
    max-width: 540px; line-height: 1.15;
  }
  .features-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 20px;
    margin-top: 56px;
  }
  .feature-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 28px;
    transition: transform .25s, box-shadow .25s;
    position: relative; overflow: hidden;
  }
  .feature-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    opacity: 0; transition: opacity .25s;
  }
  .feature-card:hover { transform: translateY(-4px); box-shadow: 0 12px 40px rgba(0,0,0,.07); }
  .feature-card:hover::before { opacity: 1; }
  .feat-icon {
    width: 44px; height: 44px;
    background: var(--fog); border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.3rem; margin-bottom: 18px;
  }
  .feat-title {
    font-family: 'Syne', sans-serif;
    font-weight: 700; font-size: 1rem; margin-bottom: 8px;
  }
  .feat-desc { font-size: .875rem; color: var(--muted); line-height: 1.6; }

  .health-section {
    background: var(--ink);
    color: #fff;
    padding: 80px 6vw;
    border-radius: 24px;
    margin: 0 4vw 80px;
    display: grid; grid-template-columns: 1fr 1fr; gap: 60px;
    align-items: center;
  }
  .health-section .section-label { color: var(--accent2); }
  .health-section .section-title { color: #fff; }
  .health-section p { color: rgba(255,255,255,.6); margin-top: 16px; line-height: 1.7; font-size: .95rem; }
  .terminal {
    background: rgba(255,255,255,.06);
    border: 1px solid rgba(255,255,255,.1);
    border-radius: 12px;
    overflow: hidden;
    font-family: 'DM Mono', 'Fira Code', monospace;
    font-size: .8rem;
  }
  .terminal-bar {
    padding: 12px 16px;
    background: rgba(255,255,255,.05);
    border-bottom: 1px solid rgba(255,255,255,.08);
    display: flex; align-items: center; gap: 6px;
  }
  .t-dot { width: 11px; height: 11px; border-radius: 50%; }
  .t-dot.r { background: #ff5f57; }
  .t-dot.y { background: #ffbd2e; }
  .t-dot.g { background: #28c840; }
  .terminal-bar span {
    margin-left: 8px; color: rgba(255,255,255,.3); font-size: .7rem;
  }
  .terminal-body { padding: 20px; line-height: 2; }
  .t-cmd { color: rgba(255,255,255,.5); }
  .t-url { color: var(--accent2); }
  .t-key { color: #a78bfa; }
  .t-val-ok { color: var(--accent2); }
  .t-val { color: #f9a8d4; }
  .t-brace { color: rgba(255,255,255,.4); }

  .stats-strip {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1px; background: var(--border);
    border: 1px solid var(--border); border-radius: 16px;
    overflow: hidden; margin: 0 4vw;
  }
  .stat-cell { background: var(--card); padding: 32px 28px; }
  .stat-num {
    font-family: 'Syne', sans-serif;
    font-size: 2.4rem; font-weight: 800;
    letter-spacing: -.04em; color: var(--ink);
  }
  .stat-num span { color: var(--accent); }
  .stat-label { font-size: .8rem; color: var(--muted); margin-top: 4px; }

  .cta-footer { text-align: center; padding: 100px 6vw; }
  .cta-footer h2 {
    font-family: 'Syne', sans-serif;
    font-size: clamp(2rem, 4vw, 3.4rem);
    font-weight: 800; letter-spacing: -.03em;
    max-width: 600px; margin: 0 auto 20px; line-height: 1.1;
  }
  .cta-footer p { color: var(--muted); max-width: 400px; margin: 0 auto 36px; line-height: 1.7; }

  footer {
    padding: 24px 6vw;
    border-top: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 12px;
    font-size: .8rem; color: var(--muted);
  }

  @media (max-width: 768px) {
    .nav-links { display: none; }
    .health-section { grid-template-columns: 1fr; }
    .hero-actions { flex-direction: column; align-items: center; }
  }
</style>
</head>
<body>

<nav>
  <a class="logo" href="#"><span>Nexa</span>Flow</a>
  <ul class="nav-links">
    <li><a href="#features">Features</a></li>
    <li><a href="#health">Status</a></li>
    <li><a href="#pricing">Pricing</a></li>
    <li><a href="/users">API</a></li>
  </ul>
  <a class="nav-cta" href="#">Get started free</a>
</nav>

<section class="hero">
  <div class="blob blob-1"></div>
  <div class="blob blob-2"></div>
  <div class="hero-badge">
    <div class="badge-dot"></div>
    Multi-region DR · Now generally available
  </div>
  <h1>Ship fast.<br>Stay <em>resilient</em>.<br>Sleep better.</h1>
  <p class="hero-sub">
    NexaFlow automates your disaster recovery pipeline — Terraform, CI/CD,
    and live health monitoring baked in from day one.
  </p>
  <div class="hero-actions">
    <a href="#" class="btn-primary">Start for free →</a>
    <a href="/health" class="btn-ghost">View system status</a>
  </div>
  <div class="status-pill">
    <div class="status-dot"></div>
    All systems operational &nbsp;·&nbsp; eu-north-1 &amp; eu-west-1
  </div>
</section>

<div class="logos">
  <p>Trusted by engineering teams at</p>
  <div class="logo-row">
    <span class="logo-brand">Meridian</span>
    <span class="logo-brand">Volantis</span>
    <span class="logo-brand">Crestline</span>
    <span class="logo-brand">Orbitas</span>
    <span class="logo-brand">Stackr</span>
    <span class="logo-brand">Lumigen</span>
  </div>
</div>

<div class="stats-strip">
  <div class="stat-cell">
    <div class="stat-num">99<span>.99%</span></div>
    <div class="stat-label">Uptime SLA</div>
  </div>
  <div class="stat-cell">
    <div class="stat-num">&lt;<span>45s</span></div>
    <div class="stat-label">Failover time</div>
  </div>
  <div class="stat-cell">
    <div class="stat-num">2<span>x</span></div>
    <div class="stat-label">Active regions</div>
  </div>
  <div class="stat-cell">
    <div class="stat-num">0<span> config</span></div>
    <div class="stat-label">Manual clicks needed</div>
  </div>
</div>

<section class="section" id="features">
  <span class="section-label">Platform</span>
  <h2 class="section-title">Everything you need, nothing you don't</h2>
  <div class="features-grid">
    <div class="feature-card">
      <div class="feat-icon">🌍</div>
      <div class="feat-title">Multi-region by default</div>
      <p class="feat-desc">Primary + DR regions deployed from a single Terraform variable. Route53 flips DNS automatically on health-check failure.</p>
    </div>
    <div class="feature-card">
      <div class="feat-icon">⚡</div>
      <div class="feat-title">GitOps pipeline</div>
      <p class="feat-desc">Push to GitHub, Jenkins handles the rest — plan, apply, deploy, smoke-test. Zero manual steps from commit to production.</p>
    </div>
    <div class="feature-card">
      <div class="feat-icon">🔒</div>
      <div class="feat-title">Secrets-first security</div>
      <p class="feat-desc">Credentials live in AWS Secrets Manager, never in code or env vars. Rotation happens transparently at runtime.</p>
    </div>
    <div class="feature-card">
      <div class="feat-icon">📊</div>
      <div class="feat-title">CloudWatch + Slack alerts</div>
      <p class="feat-desc">Real-time monitoring on every deployed instance. Slack alerts fire the moment a health check degrades.</p>
    </div>
    <div class="feature-card">
      <div class="feat-icon">🗄️</div>
      <div class="feat-title">RDS with read replicas</div>
      <p class="feat-desc">Postgres on RDS with cross-region replicas. Failover promotes the replica automatically with no data loss.</p>
    </div>
    <div class="feature-card">
      <div class="feat-icon">🧩</div>
      <div class="feat-title">Modular Terraform</div>
      <p class="feat-desc">Provider, resource, variable, output — four concepts that do 90% of the work. Add a region in under 10 minutes.</p>
    </div>
  </div>
</section>

<div class="health-section" id="health">
  <div>
    <span class="section-label">Live status</span>
    <h2 class="section-title">Health checks that actually mean something</h2>
    <p>
      Every ALB health check hits <code style="color:var(--accent2)">/health</code>,
      queries RDS, and returns a structured JSON response.
      Green means the app and database are both reachable.
      A single 500 triggers CloudWatch and starts the failover countdown.
    </p>
    <a href="/health" class="btn-primary" style="margin-top:28px; display:inline-block;">
      Check live status →
    </a>
  </div>
  <div class="terminal">
    <div class="terminal-bar">
      <div class="t-dot r"></div><div class="t-dot y"></div><div class="t-dot g"></div>
      <span>GET /health</span>
    </div>
    <div class="terminal-body">
      <div><span class="t-cmd">$ </span><span class="t-url">curl https://app.nexaflow.io/health</span></div>
      <div>&nbsp;</div>
      <div><span class="t-brace">{</span></div>
      <div>&nbsp; <span class="t-key">"status"</span>: <span class="t-val-ok">"healthy"</span>,</div>
      <div>&nbsp; <span class="t-key">"db"</span>: <span class="t-val-ok">"connected"</span>,</div>
      <div>&nbsp; <span class="t-key">"region"</span>: <span class="t-val">"eu-north-1"</span>,</div>
      <div>&nbsp; <span class="t-key">"replica_lag_ms"</span>: <span class="t-val-ok">12</span></div>
      <div><span class="t-brace">}</span></div>
      <div>&nbsp;</div>
      <div><span class="t-cmd">HTTP </span><span class="t-val-ok">200 OK</span> — <span style="color:rgba(255,255,255,.4)">34ms</span></div>
    </div>
  </div>
</div>

<div class="cta-footer" id="pricing">
  <h2>Ready to make your infrastructure bulletproof?</h2>
  <p>Deploy your first multi-region stack in under 30 minutes. No credit card required.</p>
  <div class="hero-actions">
    <a href="#" class="btn-primary">Get started free →</a>
    <a href="/users" class="btn-ghost">Explore the API</a>
  </div>
</div>

<footer>
  <span><strong style="font-family:'Syne',sans-serif;">NexaFlow</strong> &copy; 2025</span>
  <span>Built on AWS · Powered by Flask · Deployed with Terraform</span>
  <span><a href="/health" style="color:var(--muted);text-decoration:none;">System status</a></span>
</footer>

</body>
</html>"""


@app.route('/')
def landing():
    return render_template_string(LANDING_HTML)


# ─────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('APP_PORT', 5000)))
