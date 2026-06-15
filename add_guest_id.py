import csv

ENRICHED_FILE = "enriched_contacts.csv"
GUEST_ID_FILE = "guest_id.csv"
OUTPUT_FILE   = "enriched_contacts.csv"

# Load guest_id lookup: email -> guest_id
lookup = {}
with open(GUEST_ID_FILE, encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        email = (row.get("email") or "").strip().lower()
        guest_id = (row.get("guest_id") or "").strip()
        if email and guest_id:
            lookup[email] = guest_id

print(f"Loaded {len(lookup)} guest IDs")

# Read enriched contacts and add guest_id column
rows = []
with open(ENRICHED_FILE, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames or []
    if "guest_id" not in fieldnames:
        fieldnames = ["guest_id"] + list(fieldnames)
    for row in reader:
        email = (row.get("email") or "").strip().lower()
        row["guest_id"] = lookup.get(email, "")
        rows.append(row)

# Write back
matched = sum(1 for r in rows if r["guest_id"])
print(f"Matched {matched} / {len(rows)} contacts")

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"Done — saved to {OUTPUT_FILE}")
