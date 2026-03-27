import psycopg2

conn = psycopg2.connect(
    dbname="ncc",
    user="ncc_app",
    password="RGft567**",
    host="localhost",
    port=5432
)

cur = conn.cursor()

cur.execute("""
SELECT agent_id, machine_name, is_revoked, last_seen, created_at, public_ip, agent_version
FROM agents;
""")

rows = cur.fetchall()

print("AGENTS:")
for row in rows:
    print(row)

conn.close()