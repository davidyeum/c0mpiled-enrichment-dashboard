# LinkedIn Enrichment Pipeline

A Python pipeline that takes a CSV of contacts with LinkedIn URLs, enriches each profile via Crustdata, generates a reasoning summary and seniority tag via Claude, and outputs a clean enriched CSV ready for CRM import or analysis.

---

## What It Does

For each contact, the pipeline:
1. Fetches profile data from Crustdata (current role, past roles, education, location)
2. Sends the profile to Claude Haiku to generate a 2-3 sentence reasoning summary and a seniority tag (A/B/C/D)
3. Writes the enriched row to `enriched_contacts.csv`
4. Skips already-processed contacts so runs are safe to resume

---

## Output Columns

| Column | Description |
|---|---|
| `full_name` | Contact's full name |
| `email` | Contact's email address |
| `linkedin_url` | Cleaned LinkedIn profile URL |
| `source_sheet` | Source the contact came from |
| `location` | US state abbreviation (e.g. `CA`) or country name |
| `current_position` | Most recent role and company |
| `past_positions` | Up to 3 previous roles |
| `education` | Degree(s) and institution(s) |
| `reason` | 2-3 sentence summary of why the contact is notable |
| `tag` | Seniority tag: A, B, C, or D |

### Seniority Tags
- **A** — Senior professionals (executives, founders, 10+ years experience)
- **B** — Mid-level professionals OR anyone with a Master's degree, MBA, or PhD
- **C** — Undergrad students with leadership roles, notable internships, or research
- **D** — Undergrad students with limited experience beyond coursework

---

## Setup

### 1. Install dependencies
```bash
pip install requests python-dotenv
```

### 2. Create a `.env` file
```
CRUSTDATA_API_KEY=your_crustdata_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
```

### 3. Prepare your input CSV
The input file should be named `contacts.csv` and contain at minimum:

| Column | Notes |
|---|---|
| `email` | Required |
| `linkedin_url` or `linkedin_profile` | Required |
| `full_name` or `name` | Optional but recommended |
| `source_sheet` | Optional — tracks where the contact came from |

---

## Usage

### Standard run
```bash
python3 linkedin_enricher.py
```
Skips any contacts already in `enriched_contacts.csv`.

### Reprocess everything from scratch
```bash
python3 linkedin_enricher.py --fresh
```

### Retry failed rows (rows with no enrichment data)
```bash
python3 linkedin_enricher.py --retry-failed
```
Purges blank rows from the output file and retries them.

---

## Notes

- Progress is saved after every row — safe to stop and resume at any time
- Contacts with invalid LinkedIn URLs are written to output with blank enrichment fields
- If Crustdata returns a different profile than the one queried, the row is skipped
- Rate limit: 1 second delay between each contact
