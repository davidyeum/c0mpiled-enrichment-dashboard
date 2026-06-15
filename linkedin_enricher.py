import argparse
import csv
import json
import os
import time
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CRUSTDATA_API_KEY = os.getenv("CRUSTDATA_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

INPUT_FILE = "contacts.csv"
OUTPUT_FILE = "enriched_contacts.csv"
OUTPUT_COLUMNS = [
    "full_name", "email", "linkedin_url", "source_sheet", "location",
    "current_position", "past_positions", "education", "reason", "tag",
]

US_STATE_ABBREVS = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

US_COUNTRY_VARIANTS = {"united states", "united states of america", "usa", "us"}

STATE_NAME_TO_ABBREV = {v: k for k, v in US_STATE_ABBREVS.items()}

# Maps substrings found in metro/area names → state abbreviation.
# Checked case-insensitively against the full location string.
METRO_TO_STATE = {
    "san francisco": "CA", "bay area": "CA", "silicon valley": "CA",
    "san jose": "CA", "san diego": "CA", "los angeles": "CA", "sacramento": "CA",
    "new york": "NY", "brooklyn": "NY", "manhattan": "NY", "bronx": "NY", "queens": "NY",
    "chicago": "IL",
    "houston": "TX", "dallas": "TX", "austin": "TX", "san antonio": "TX", "fort worth": "TX",
    "phoenix": "AZ", "tucson": "AZ", "scottsdale": "AZ",
    "philadelphia": "PA", "pittsburgh": "PA",
    "san antonio": "TX",
    "seattle": "WA", "tacoma": "WA",
    "denver": "CO", "boulder": "CO",
    "boston": "MA", "cambridge": "MA",
    "atlanta": "GA",
    "miami": "FL", "orlando": "FL", "tampa": "FL", "jacksonville": "FL",
    "minneapolis": "MN",
    "portland": "OR",
    "las vegas": "NV", "reno": "NV",
    "detroit": "MI", "grand rapids": "MI",
    "nashville": "TN", "memphis": "TN",
    "charlotte": "NC", "raleigh": "NC",
    "indianapolis": "IN",
    "columbus": "OH", "cleveland": "OH", "cincinnati": "OH",
    "kansas city": "MO", "st. louis": "MO",
    "salt lake city": "UT",
    "richmond": "VA", "norfolk": "VA", "virginia beach": "VA",
    "baltimore": "MD",
    "washington": "DC", "district of columbia": "DC",
    "new orleans": "LA",
    "oklahoma city": "OK",
    "albuquerque": "NM",
    "omaha": "NE",
    "hartford": "CT",
    "providence": "RI",
    "buffalo": "NY", "rochester": "NY",
    "louisville": "KY",
    "birmingham": "AL",
    "jackson": "MS",
    "little rock": "AR",
    "columbia": "SC", "charleston": "SC",
    "boise": "ID",
    "des moines": "IA",
    "sioux falls": "SD",
    "fargo": "ND",
    "billings": "MT",
    "cheyenne": "WY",
    "anchorage": "AK",
    "honolulu": "HI",
    "burlington": "VT",
    "manchester": "NH",
    "portland": "ME",
    "wilmington": "DE",
    "wichita": "KS",
}


def _metro_state(location_str: str) -> str:
    """Check the full location string for known city/metro names and return a state abbrev."""
    loc_lower = (location_str or "").lower()
    for metro, abbrev in METRO_TO_STATE.items():
        if metro in loc_lower:
            return abbrev
    return None


def normalize_location(location_str: str, city: str, region: str, country: str):
    raw_parts = [p.strip() for p in (location_str or "").split(",") if p.strip()]
    full_str = location_str or ""

    # Combine all text fields for metro detection
    combined = " ".join(filter(None, [full_str, city, region]))

    country_lower = (country or "").strip().lower()
    is_us = country_lower in US_COUNTRY_VARIANTS
    if not is_us and raw_parts:
        last = raw_parts[-1]
        if last.lower() in US_COUNTRY_VARIANTS or last.upper() in US_STATE_ABBREVS or last in STATE_NAME_TO_ABBREV:
            is_us = True
    # Also detect US via metro lookup across all fields
    if not is_us and _metro_state(combined):
        is_us = True

    if is_us:
        state_abbrev = None
        # 1. Scan comma-separated parts for explicit state name or abbreviation
        for part in raw_parts:
            if part.upper() in US_STATE_ABBREVS:
                state_abbrev = part.upper()
                break
            if part in STATE_NAME_TO_ABBREV:
                state_abbrev = STATE_NAME_TO_ABBREV[part]
                break
        # 2. Fall back to region component field
        if not state_abbrev and region:
            r = region.strip()
            state_abbrev = r.upper() if r.upper() in US_STATE_ABBREVS else STATE_NAME_TO_ABBREV.get(r)
        # 3. Fall back to metro/city name lookup across all available text
        if not state_abbrev:
            state_abbrev = _metro_state(combined)
        return state_abbrev or "USA"

    # Non-US: country name only
    result = country.strip() if country and country.strip() else (raw_parts[-1] if raw_parts else None)
    if result and result.lower() in US_COUNTRY_VARIANTS:
        return None
    return result or None


def _employer_role_string(entry: dict) -> str:
    title = (entry.get("employee_title") or "").strip()
    company = (entry.get("employer_name") or "").strip()
    if title and company:
        return f"{title} at {company}"
    return title or company or ""


def _sort_key(entry: dict) -> tuple:
    # Sort by end_date desc (None = still active = "9999"), then start_date desc
    end = entry.get("end_date") or "9999"
    start = entry.get("start_date") or ""
    return (end, start)


def parse_experience(person_data: dict):
    current_employers = person_data.get("current_employers") or []
    past_employers = sorted(
        person_data.get("past_employers") or [],
        key=_sort_key,
        reverse=True,
    )

    if current_employers:
        current_str = _employer_role_string(current_employers[0])
    else:
        # No active role — use top-level title (most recent) + most recent past employer's company
        top_title = (person_data.get("title") or "").strip()
        most_recent = past_employers[0] if past_employers else {}
        top_company = (most_recent.get("employer_name") or "").strip()
        if top_title and top_company:
            current_str = f"{top_title} at {top_company}"
        elif top_title:
            current_str = top_title
        elif most_recent:
            current_str = _employer_role_string(most_recent)
        else:
            current_str = ""

    past_strs = []
    for entry in past_employers:
        role_str = _employer_role_string(entry)
        if role_str and role_str != current_str and role_str not in past_strs:
            past_strs.append(role_str)
        if len(past_strs) == 3:
            break

    return current_str, "; ".join(past_strs)


def parse_education(person_data: dict) -> str:
    education = person_data.get("education_background") or []
    entries = []
    for edu in education:
        school = (edu.get("institute_name") or "").strip()
        degree = (edu.get("degree_name") or "").strip()
        field = (edu.get("field_of_study") or "").strip()
        degree_full = f"{degree} in {field}" if field else degree
        if degree_full and school:
            entries.append(f"{degree_full} at {school}")
        elif school:
            entries.append(school)
    return "; ".join(entries)


def clean_linkedin_url(url: str) -> str:
    """Strip query params, fragments, trailing slashes, locale subdomains, and language suffixes."""
    import re
    url = url.strip()
    url = url.split("#")[0]
    url = url.split("?")[0]
    url = url.rstrip("/")
    if url.startswith("http://"):
        url = "https://" + url[7:]
    # Normalize locale subdomains (jp.linkedin.com, fr.linkedin.com, etc.) to www.linkedin.com
    url = re.sub(r"https://[a-z]{2}\.linkedin\.com", "https://www.linkedin.com", url)
    # Strip language suffix at end of slug (e.g. /en, /ja)
    url = re.sub(r"/in/([^/]+)/[a-z]{2}$", r"/in/\1", url)
    return url


def crustdata_enrich(linkedin_url: str) -> dict:
    resp = requests.get(
        "https://api.crustdata.com/screener/person/enrich",
        headers={
            "Authorization": f"Bearer {CRUSTDATA_API_KEY}",
            "Content-Type": "application/json",
            "x-api-version": "2025-11-01",
        },
        params={"linkedin_profile_url": linkedin_url},
        timeout=30,
    )
    if not resp.ok:
        raise Exception(f"{resp.status_code} {resp.reason} — {resp.text}")
    return resp.json()


def _url_slug(url: str) -> str:
    """Extract the lowercase slug from a linkedin.com/in/<slug> URL."""
    url = url.rstrip("/").lower()
    if "/in/" in url:
        return url.split("/in/")[-1].split("?")[0]
    return ""


def _normalize_slug(slug: str) -> str:
    """Strip trailing LinkedIn numeric suffix only.
    e.g. 'hiroki-sawai-b1ab89203' -> 'hiroki-sawai'
    """
    import re
    return re.sub(r"-[a-f0-9]{7,12}$", "", slug)


def pick_best_result(response: dict, queried_url: str = "") -> dict:
    results = response if isinstance(response, list) else response.get("results", [response])
    if not results:
        return {}
    best = max(results, key=lambda r: r.get("confidence_score", 0))
    person_data = best.get("person_data", best)

    # Validate that the returned profile slug matches what we queried
    if queried_url:
        queried_slug = _url_slug(queried_url)
        returned_slug = _url_slug(
            person_data.get("linkedin_flagship_url") or
            person_data.get("linkedin_profile_url") or ""
        )
        if queried_slug and returned_slug and _normalize_slug(queried_slug) != _normalize_slug(returned_slug):
            print(f"  Crustdata returned a different profile ({returned_slug}) than queried ({queried_slug}) — skipping")
            return {}

    return person_data


def claude_reason_tag(full_name: str, current_position: str, past_positions: str,
                      education: str, location: str):
    prompt = f"""Given this profile, return a JSON object with exactly two fields.
Return ONLY valid JSON. No explanation, no markdown fences.

- "reason": 2-3 sentences on why this person is notable. Be specific — \
mention their role, company, background, and location where relevant. \
For students, highlight leadership roles or accomplishments.
- "tag": A single letter A, B, C, or D based on seniority:
    A = Senior professionals (executives, founders, 10+ years experience)
    B = Mid-level professionals (managers, engineers, analysts with experience) \
OR anyone currently pursuing or holding a Master's degree or higher (MBA, MS, PhD, etc.), \
regardless of work experience
    C = Undergrad students (bachelor's degree only, leadership roles, notable internships, research)
    D = Undergrad students with limited experience beyond coursework

Profile:
Name: {full_name}
Current position: {current_position}
Past positions: {past_positions}
Education: {education}
Location: {location}
"""
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.text
    try:
        body = json.loads(raw)
    except Exception:
        raise Exception(f"Claude response not JSON. Status={resp.status_code} Body={raw[:500]}")
    text = body["content"][0]["text"].strip()
    if not text:
        raise Exception(f"Claude returned empty text. Full response: {body}")
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop opening ```json line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # drop closing ``` line
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        raise Exception(f"Claude text not JSON: {text[:500]}")
    return parsed.get("reason", ""), parsed.get("tag", "")


ENRICHMENT_FIELDS = ["current_position", "past_positions", "education", "reason", "tag"]


def purge_failed_rows():
    """Remove rows with no enrichment data from the output file so they get retried."""
    if not Path(OUTPUT_FILE).exists():
        return
    with open(OUTPUT_FILE, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    kept = [r for r in rows if any(r.get(col, "").strip() for col in ENRICHMENT_FIELDS)]
    removed = len(rows) - len(kept)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(kept)
    print(f"Purged {removed} failed rows — they will be retried this run.")


def load_processed_emails(fresh: bool, retry_failed: bool) -> set[str]:
    if fresh or not Path(OUTPUT_FILE).exists():
        return set()
    if retry_failed:
        purge_failed_rows()
    processed = set()
    with open(OUTPUT_FILE, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("email"):
                processed.add(row["email"].strip().lower())
    return processed


def write_row(writer, row_data: dict) -> None:
    writer.writerow({col: row_data.get(col, "") for col in OUTPUT_COLUMNS})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="Re-process everyone from scratch")
    parser.add_argument("--retry-failed", action="store_true", help="Retry rows that previously returned no enrichment data")
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("WARNING: ANTHROPIC_API_KEY not set — reason and tag will be empty for all rows.")

    processed_emails = load_processed_emails(args.fresh, args.retry_failed)

    output_exists = Path(OUTPUT_FILE).exists() and not args.fresh
    out_f = open(OUTPUT_FILE, "a" if output_exists else "w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(out_f, fieldnames=OUTPUT_COLUMNS)
    if not output_exists:
        writer.writeheader()

    try:
        with open(INPUT_FILE, newline="", encoding="utf-8") as in_f:
            all_rows = list(csv.DictReader(in_f))

        total = len(all_rows)
        done = 0

        for row in all_rows:
            full_name = (row.get("full_name") or row.get("name") or "").strip()
            email = row.get("email", "").strip()
            linkedin_url = clean_linkedin_url(row.get("linkedin_url") or row.get("linkedin_profile") or "")
            source_sheet = row.get("source_sheet", "").strip()

            if email.lower() in processed_emails:
                done += 1
                continue

            if "/in/" not in linkedin_url:
                print(f"  Skipping {email} — not a person LinkedIn URL: {linkedin_url}")
                write_row(writer, {"full_name": full_name, "email": email, "linkedin_url": linkedin_url, "source_sheet": source_sheet})
                out_f.flush()
                processed_emails.add(email.lower())
                done += 1
                continue

            print(f"[{done + 1}/{total}] Processing {full_name} <{email}>")

            base = {"full_name": full_name, "email": email, "linkedin_url": linkedin_url, "source_sheet": source_sheet}

            # Step 1 — Crustdata
            person_data = {}
            try:
                response = crustdata_enrich(linkedin_url)
                person_data = pick_best_result(response, queried_url=linkedin_url)
            except Exception as e:
                print(f"  Crustdata error for {email}: {e}")
                write_row(writer, base)
                out_f.flush()
                processed_emails.add(email.lower())
                done += 1
                time.sleep(1)
                continue

            current_position, past_positions = parse_experience(person_data)
            education = parse_education(person_data)
            location = normalize_location(
                person_data.get("location") or "",
                person_data.get("city") or "",
                person_data.get("region") or person_data.get("state") or "",
                person_data.get("country") or "",
            )

            # If Crustdata returned no useful data, skip and retry later
            if not any([current_position, past_positions, education, location]):
                print(f"  [{done + 1}/{total}] Crustdata returned empty profile for {email} — will retry on next run")
                time.sleep(1)
                continue

            # Step 2 — Claude
            reason, tag = "", ""
            if ANTHROPIC_API_KEY:
                try:
                    reason, tag = claude_reason_tag(
                        full_name, current_position, past_positions,
                        education, location or "",
                    )
                except Exception as e:
                    print(f"  Claude error for {email}: {e}")

            write_row(writer, {
                **base,
                "location": location or "",
                "current_position": current_position,
                "past_positions": past_positions,
                "education": education,
                "reason": reason,
                "tag": tag,
            })
            out_f.flush()
            processed_emails.add(email.lower())
            done += 1
            print(f"  [{done}/{total}] Done — tag={tag or '(none)'}")
            time.sleep(1)

    finally:
        out_f.close()

    print(f"Output written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
