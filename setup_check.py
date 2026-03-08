"""
Setup validator — run this after filling in your .env to verify all connections.

Usage:
    python setup_check.py
"""

import os
import sys

def check_env_var(name: str, prefix: str | None = None) -> str | None:
    val = os.environ.get(name, "")
    if not val or val.startswith("postgresql+asyncpg://user:") or val.startswith("rediss://default:password") or "xxxxxxxx" in val:
        print(f"  SKIP  {name} — not configured yet")
        return None
    if prefix and not val.startswith(prefix):
        print(f"  WARN  {name} — expected to start with '{prefix}', got '{val[:30]}...'")
    else:
        print(f"  OK    {name}")
    return val


def check_postgres(url: str) -> bool:
    try:
        # Convert async URL to sync for testing
        sync_url = url.replace("+asyncpg", "").split("?")[0]
        import psycopg2
        conn = psycopg2.connect(sync_url + "?sslmode=require")
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        print("  OK    PostgreSQL connection successful")
        return True
    except ImportError:
        print("  WARN  psycopg2 not installed — run: pip install psycopg2-binary")
        return False
    except Exception as e:
        print(f"  FAIL  PostgreSQL: {e}")
        return False


def check_redis(url: str) -> bool:
    try:
        import redis
        r = redis.from_url(url)
        r.ping()
        print("  OK    Redis connection successful")
        return True
    except ImportError:
        print("  WARN  redis not installed — run: pip install redis")
        return False
    except Exception as e:
        print(f"  FAIL  Redis: {e}")
        return False


def check_neo4j(uri: str, user: str, password: str) -> bool:
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        print("  OK    Neo4j connection successful")
        return True
    except ImportError:
        print("  WARN  neo4j not installed — run: pip install neo4j")
        return False
    except Exception as e:
        print(f"  FAIL  Neo4j: {e}")
        return False


def apply_schema(url: str) -> bool:
    """Apply the SQL schema to the Postgres database."""
    schema_path = os.path.join(os.path.dirname(__file__), "docs", "schema.sql")
    if not os.path.exists(schema_path):
        print(f"  FAIL  Schema file not found at {schema_path}")
        return False

    try:
        import psycopg2
        sync_url = url.replace("+asyncpg", "").split("?")[0]
        conn = psycopg2.connect(sync_url + "?sslmode=require")
        conn.autocommit = True
        cur = conn.cursor()

        with open(schema_path) as f:
            sql = f.read()

        cur.execute(sql)
        cur.close()
        conn.close()
        print("  OK    Schema applied successfully")
        return True
    except Exception as e:
        print(f"  FAIL  Schema apply: {e}")
        return False


def main():
    # Load .env file manually
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ[key.strip()] = value.strip()
        print(f"Loaded .env from {env_path}\n")
    else:
        print(f"No .env file found at {env_path}")
        print("Copy .env.example to .env and fill in your credentials.\n")
        sys.exit(1)

    print("=" * 50)
    print("  CHECKING ENVIRONMENT VARIABLES")
    print("=" * 50)

    db_url = check_env_var("DATABASE_URL")
    redis_url = check_env_var("REDIS_URL")
    neo4j_uri = check_env_var("NEO4J_URI")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_pass = os.environ.get("NEO4J_PASSWORD", "")
    check_env_var("HELIUS_API_KEY")
    check_env_var("ANTHROPIC_API_KEY")

    print()
    print("=" * 50)
    print("  TESTING CONNECTIONS")
    print("=" * 50)

    pg_ok = check_postgres(db_url) if db_url else False
    redis_ok = check_redis(redis_url) if redis_url else False
    neo4j_ok = check_neo4j(neo4j_uri, neo4j_user, neo4j_pass) if neo4j_uri else False

    # Offer to apply schema if Postgres is connected
    if pg_ok:
        print()
        print("=" * 50)
        print("  APPLYING DATABASE SCHEMA")
        print("=" * 50)
        apply_schema(db_url)

    print()
    print("=" * 50)
    print("  SUMMARY")
    print("=" * 50)
    results = {
        "PostgreSQL": pg_ok,
        "Redis": redis_ok,
        "Neo4j": neo4j_ok,
    }
    all_ok = True
    for name, ok in results.items():
        status = "READY" if ok else "NOT READY"
        print(f"  {status:>10}  {name}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("All systems go! Start the API with:")
        print("  uvicorn apps.api.main:app --reload --port 8000")
    else:
        print("Fix the issues above, then re-run: python setup_check.py")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
