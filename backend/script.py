"""
script.py — RateMyTWU timetable scraper

Parses a TWU timetable PDF and inserts professors, courses, and
professor-course links into the database. Safe to re-run: no duplicates.

Usage:
    cd backend
    python script.py --pdf Course_Timetable.pdf --semester SU2026
    python script.py --pdf Fall2026_Timetable.pdf --semester FA2026
"""

import re
import argparse
import sys

# ── DB setup ──────────────────────────────────────────────────────────────────
sys.path.insert(0, ".")
from database import SessionLocal, engine, Base
from models import Professor, Courses, ProfessorCourse
Base.metadata.create_all(bind=engine)


# ── Regexes ───────────────────────────────────────────────────────────────────

# Course header: "ANTH 101 Introduction Cultural Anthropology Sem. Hr. 3.00"
COURSE_RE = re.compile(
    r"^([A-Z]{2,5})\s+(\d{3,4})\s+.+?Sem\.\s*Hr\.\s*[\d.]+\s*$"
)

# Section line: "Sec. A6 9:00 AM - 12:00 PM TR 4/28/2026 - 6/4/2026 Name"
# Includes lab variant: "Sec. Lab A3 ..." — we skip those
SECTION_RE = re.compile(r"^Sec\.\s+(?:Lab\s+)?(\S+)")

# Travel Study section lines start with "- mm/dd/yyyy" instead of "Sec."
# e.g. "- 4/27/2026 - 5/22/2026 Elizabeth"
TRAVEL_SECTION_RE = re.compile(r"^-\s+\d{1,2}/\d{1,2}/\d{4}")

# Standalone overflow tokens produced by line-wrapped schedules: "F", "FS", "L1"
OVERFLOW_RE = re.compile(r"^[A-Z]{1,3}\d?$")

# Words that should never start a department heading
DEPT_NOISE = {
    "please", "note:", "crosslisted:", "instruction", "method:",
    "page", "trinity", "western", "university", "f2f", "virt", "ol",
    "fee:", "$", "tba", "-",
}

# Known single-word department keywords — used to reject them as name continuations
KNOWN_DEPT_WORDS = {
    "anthropology", "art", "biology", "business", "chemistry",
    "communication", "computer", "sciences", "economics", "education",
    "english", "environment", "foundations", "french", "geography",
    "development", "history", "interdisciplinary", "japanese", "kinetics",
    "leadership", "linguistics", "management", "mathematics", "media",
    "music", "nursing", "philosophy", "preparation", "psychology",
    "religious", "science", "skills", "sociology", "spanish",
    "studies", "study", "travel", "university", "writing",
}


# ── Line classification helpers ───────────────────────────────────────────────

def is_skip_line(line: str) -> bool:
    """Return True for lines that carry no useful data."""
    low = line.lower().strip()
    if not low:
        return True
    if OVERFLOW_RE.match(line.strip()):
        return True
    for noise in (
        "please note:", "crosslisted:", "instruction method:",
        "page ", "trinity western university", "fee: $",
    ):
        if low.startswith(noise):
            return True
    return False


def looks_like_department(line: str) -> bool:
    """
    Return True if the line looks like a department heading.
    Headings are short, title-case, contain no digits,
    and don't start with known noise tokens.
    """
    stripped = line.strip()
    if not stripped:
        return False
    words = stripped.split()
    if len(words) > 6:
        return False
    if any(ch.isdigit() for ch in stripped):
        return False
    if words[0][0].islower():
        return False
    if words[0].lower() in DEPT_NOISE:
        return False
    return True


def extract_name_from_line(line: str) -> str | None:
    """
    Extract the professor name from a section line.
    The name always appears after the LAST date (mm/dd/yyyy) on the line.
    """
    date_matches = list(re.finditer(r"\d{1,2}/\d{1,2}/\d{4}", line))
    if not date_matches:
        return None
    name_part = line[date_matches[-1].end():].strip()
    # Strip trailing fee suffix
    name_part = re.sub(r"\s+Fee:\s*\$.*", "", name_part).strip()
    if not name_part or name_part.lower() == "tba" or name_part == "-":
        return None
    return name_part


def is_name_continuation(line: str) -> bool:
    """
    Return True if this line is the overflow second part of a professor name.

    Examples that should return True:
        "Zwamborn"                 → second part of "Elizabeth Zwamborn"
        "Nelson"                   → second part of "Leanne Drocholl Nelson"
        "Von Koenigsloew"          → second part of "Heilwig Von Koenigsloew"

    Examples that should return False:
        "Study Skills"             → department heading, not a surname
        "Travel Studies"           → department heading
        "Biology"                  → known department word
    """
    stripped = line.strip()
    if not stripped:
        return False
    words = stripped.split()
    if len(words) > 3:
        return False
    if any(ch.isdigit() for ch in stripped):
        return False
    if (
        SECTION_RE.match(stripped)
        or TRAVEL_SECTION_RE.match(stripped)
        or COURSE_RE.match(stripped)
        or is_skip_line(stripped)
    ):
        return False
    # All words must start with uppercase
    if not all(w[0].isupper() for w in words if w):
        return False
    # Multi-word lines that look like department headings → NOT continuations
    # (Single-word surnames like "Zwamborn" are allowed through)
    if len(words) > 1 and looks_like_department(stripped):
        return False
    # Single word: reject known department keywords
    if len(words) == 1 and stripped.lower() in KNOWN_DEPT_WORDS:
        return False
    return True


# ── PDF reader ────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> list[str]:
    """Extract all text lines from a PDF using pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    lines = []
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            lines.append(line)
    return lines


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_timetable(lines: list[str]) -> list[tuple[str, str, str]]:
    """
    Parse timetable lines into (course_code, department, professor_name) triples.

    Returns a deduplicated list — one row per unique (course_code, professor_name).
    """
    results: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    current_dept = "Unknown"
    current_course_code: str | None = None

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # ── Skip noise ──────────────────────────────────────────────────────
        if is_skip_line(stripped):
            i += 1
            continue

        # ── Course header ───────────────────────────────────────────────────
        m = COURSE_RE.match(stripped)
        if m:
            current_course_code = f"{m.group(1)} {m.group(2)}"
            i += 1
            continue

        # ── Sec. line ───────────────────────────────────────────────────────
        if SECTION_RE.match(stripped):
            if re.match(r"^Sec\.\s+Lab\b", stripped):
                i += 1
                continue  # skip lab sections entirely

            name_part = extract_name_from_line(stripped)

            # Look ahead for name continuation (split across two lines)
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and name_part and is_name_continuation(lines[j].strip()):
                name_part = (name_part + " " + lines[j].strip()).strip()
                i = j  # consume the continuation line

            if name_part and current_course_code:
                key = (current_course_code, name_part.lower())
                if key not in seen:
                    seen.add(key)
                    results.append((current_course_code, current_dept, name_part))

            i += 1
            continue

        # ── Travel Study section (starts with "- mm/dd/yyyy") ───────────────
        if TRAVEL_SECTION_RE.match(stripped):
            name_part = extract_name_from_line(stripped)

            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and name_part and is_name_continuation(lines[j].strip()):
                name_part = (name_part + " " + lines[j].strip()).strip()
                i = j

            if name_part and current_course_code:
                key = (current_course_code, name_part.lower())
                if key not in seen:
                    seen.add(key)
                    results.append((current_course_code, current_dept, name_part))

            i += 1
            continue

        # ── Department heading ──────────────────────────────────────────────
        if looks_like_department(stripped):
            current_dept = stripped
            i += 1
            continue

        i += 1

    return results


# ── Database upsert ───────────────────────────────────────────────────────────

def upsert(pdf_path: str, semester: str) -> None:
    print(f"Parsing {pdf_path}...")
    lines = extract_text_from_pdf(pdf_path)
    rows = parse_timetable(lines)
    print(f"Found {len(rows)} (course, professor) pairs. Writing to DB...")

    db = SessionLocal()
    try:
        prof_count = course_count = link_count = 0

        for course_code, department, prof_name in rows:
            norm_name = prof_name.lower().strip()

            # Professor: get or create (matched by lowercase name)
            prof = db.query(Professor).filter(Professor.name == norm_name).first()
            if not prof:
                prof = Professor(name=norm_name, department=department)
                db.add(prof)
                db.flush()
                prof_count += 1

            # Course: get or create (matched by code)
            course = db.query(Courses).filter(Courses.code == course_code).first()
            if not course:
                course = Courses(code=course_code, department=department)
                db.add(course)
                db.flush()
                course_count += 1

            # ProfessorCourse link: get or create
            link = db.query(ProfessorCourse).filter(
                ProfessorCourse.professor_id == prof.id,
                ProfessorCourse.course_id == course.id,
                ProfessorCourse.semester == semester,
            ).first()
            if not link:
                link = ProfessorCourse(
                    professor_id=prof.id,
                    course_id=course.id,
                    semester=semester,
                )
                db.add(link)
                link_count += 1

        db.commit()
        print(
            f"\n✓ Done — {prof_count} new professors, "
            f"{course_count} new courses, "
            f"{link_count} new links  (semester={semester})"
        )

    except Exception as e:
        db.rollback()
        print(f"✗ Error: {e}")
        raise
    finally:
        db.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import a TWU timetable PDF into the RateMyTWU database"
    )
    parser.add_argument("--pdf", required=True, help="Path to timetable PDF")
    parser.add_argument("--semester", required=True, help="Semester label e.g. SU2026")
    args = parser.parse_args()
    upsert(args.pdf, args.semester)