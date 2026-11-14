"""Read WiCS's TSV export as roster blocks, including continuation-line role descriptions."""

import csv
import hashlib
import re
from pathlib import Path

from app.services.role_definitions import VERIFIED_ROLE_DEFINITIONS


def parse_roster(path: Path) -> tuple[list[dict], list[str]]:
    records, warnings, seen = [], [], set()
    current = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle, delimiter="\t")
        header = next(rows, [])
        if header[1:5] != ["GirlHacks Title", "Eboard Position", "Major", "Graduation Date"]:
            raise ValueError("Unexpected TSV header. Expected the WiCS e-board export.")
        for line, row in enumerate(rows, start=2):
            cells = [value.strip() for value in row]
            if not any(cells):
                continue
            is_member = len(cells) >= 5 and cells[2] and re.fullmatch(
                r"[A-Za-z]+ 20\d{2}", cells[4]
            )
            if is_member:
                cells += [""] * max(0, 9 - len(cells))
                name, title, role, major, graduation, phone, email, description = cells[:8]
                key = name.casefold()
                if not name or key in seen:
                    raise ValueError(f"Line {line}: missing or duplicate member name.")
                seen.add(key)
                email = email.lower() or None
                if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                    raise ValueError(f"Line {line}: invalid email address.")
                if phone and not re.fullmatch(r"[+\d(). -]{7,50}", phone):
                    raise ValueError(f"Line {line}: invalid contact phone.")
                # Preserve the supplied number: do not guess a country prefix or sender identity.
                if role == "Industry Partnernships Chair":
                    role = "Industry Partnerships Chair"
                    warnings.append(f"Line {line}: corrected the Industry Partnerships role typo.")
                current = {
                    "code": "WICS_" + hashlib.sha256(key.encode()).hexdigest()[:12].upper(),
                    "display_name": name, "email": email, "phone_number": phone or None,
                    "contact_consent": bool(email or phone), "board_role": role,
                    "girlhacks_title": title, "major": major, "graduation_date": graduation,
                    "graduation_year": int(graduation[-4:]),
                    "role_description": description.removeprefix("The Role:").strip(),
                    "role_responsibilities": [], "delegation_context_verified": True,
                }
                records.append(current)
            else:
                text = " ".join(value for value in cells if value).strip()
                if text == "Tasks:":
                    continue
                if current is None or len(cells) >= 5 and any(cells[2:5]):
                    raise ValueError(f"Line {line}: unrecognized roster row.")
                current["role_responsibilities"].append(text)
    if not records:
        raise ValueError("No members found.")
    for record in records:
        definition = VERIFIED_ROLE_DEFINITIONS.get(record["board_role"])
        if definition:
            record["role_description"] = definition["description"]
            record["role_responsibilities"] = list(definition["responsibilities"])
    emails = [record["email"] for record in records if record["email"]]
    if len(emails) != len(set(emails)):
        raise ValueError("Duplicate invitation email addresses in roster.")
    return records, warnings
