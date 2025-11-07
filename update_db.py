import sqlite3

# List of artist names to update
artist_names = [
    "Otto A. Totland & Erik K. Skodvin",
]

db_path = "/home/fred/cron/python/new_release_notifier/data/releases.db"

# Create a parameterized SQL query
placeholders = ",".join("?" for _ in artist_names)
# query = f"UPDATE artists SET ignore_releases = 0 WHERE name IN ({placeholders})"
query = f"UPDATE artists SET musicbrainz_id = 'e59108d3-2088-4b40-9d9d-5f368486951d' WHERE name IN ({placeholders})"

with sqlite3.connect(db_path) as conn:
    conn.execute(query, artist_names)
    conn.commit()
    print(f"Updated musicbrainz_id for artists: {artist_names}")
