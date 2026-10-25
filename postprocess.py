#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import re
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

FIELDS = [
    "Last_name_ru",
    "First_name_ru",
    "Middle_name_ru",
    "Sex_ru",
    "Birth_date",
    "Birth_place_ru",
    "Issue_date",
    "Issue_organisation_code",
    "Licence_number",
    "Issue_organization_ru",
]

AS_OF = date(2026, 10, 1)

CYR_TO_LAT = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "2",
    "Ж": "J", "З": "Z", "И": "I", "Й": "Q", "К": "K", "Л": "L", "М": "M",
    "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "C", "Ч": "3", "Ш": "4", "Щ": "W", "Ъ": "X",
    "Ы": "Y", "Ь": "9", "Э": "6", "Ю": "7", "Я": "8",
}
LATIN_HOMO = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
})
ORG_START = (
    "ОТДЕЛ", "ОТДЕЛЕНИЕ", "ОТД.", "ГУ", "ТП", "ОВД", "УВД", "МВД", "УМВД",
    "ГУВД", "ОУФМС", "УФМС", "ОФМС", "МП", "МО", "МРО", "ПВС", "ГОМ",
    "МИГРАЦИОННЫЙ", "ТЕРРИТОРИАЛЬНЫЙ", "МЕЖРАЙОННЫЙ", "МЕЖРАЙОННОЕ",
    "УПРАВЛЕНИЕ", "РЕЗЕРВ", "ПАСПОРТНО-ВИЗОВОЕ", "ПАСПОРТНЫЙ", "РОВД",
    "ГОВД", "ГРОВД", "ОМ", "ПОМ", "ТПМ",
)

TOKEN_FIX = {
    "РАЙОП": "РАЙОН",
    "РАЙОИ": "РАЙОН",
    "РЛЙОНА": "РАЙОНА",
    "РАЙОНАА": "РАЙОНА",
    "СБЛАСТИ": "ОБЛАСТИ",
    "СБЛ.": "ОБЛ.",
    "МИГРАЦИН": "МИГРАЦИИ",
    "МИГРАЦИН.": "МИГРАЦИИ",
    "РСПРОСАМ": "ВОПРОСАМ",
    "ВЕСПУБЛИКЕ": "РЕСПУБЛИКЕ",
    "ВЕСПУБЛИКИ": "РЕСПУБЛИКИ",
    "ОРЕНБУРГСКОИ": "ОРЕНБУРГСКОЙ",
    "КАРАЧАЕВО-ЧЕРКЕССКОИ": "КАРАЧАЕВО-ЧЕРКЕССКОЙ",
    "ЧСЕВЕРНАЯ": "СЕВЕРНАЯ",
    "ДАГЕСТЛН": "ДАГЕСТАН",
    "УЭБЕКСКАЯ": "УЗБЕКСКАЯ",
    "ВОЛОГОСКОЙ": "ВОЛОГОДСКОЙ",
    "СКР.": "КР.",
    "3КР.": "КР.",
    "ТЬВА": "ТЫВА",
    "ТЬВЕ": "ТЫВЕ",
    "ТЬВЫ": "ТЫВЫ",
}

MIN_CC = {
    "Birth_place_ru": 0.97,
    "Issue_organization_ru": 0.97,
    "Last_name_ru": 0.90,
    "First_name_ru": 0.90,
    "Middle_name_ru": 0.90,
    "Licence_number": 0.90,
}

VALID_RAION = {
    "Р-Н", "Р-НА", "Р-НЕ", "Р-НУ", "Р-НЫ", "Р-НАХ",
    "Р-Н.", "Р-НА.", "Р-НЕ.",
}

MIN_SHARPNESS = 90.0
MIN_DOC_PX = 700
MAX_GLARE = 0.22


def check_digit(s: str) -> str:
    weights = (7, 3, 1)
    values = {c: i for i, c in enumerate("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
    values["<"] = 0
    total = 0
    for i, ch in enumerate(s):
        total += values.get(ch, 0) * weights[i % 3]
    return str(total % 10)


def translit(text: str) -> str:
    return "".join(CYR_TO_LAT[ch] for ch in text.upper() if ch in CYR_TO_LAT)


def norm_cmp(s: str) -> str:
    return " ".join(str(s or "").split()).upper()


def viz_join(field: dict | None) -> str | None:
    if not field:
        return None
    lines = field.get("lines") or []
    if not lines:
        return None
    return " ".join((ln.get("text") or "") for ln in lines)


def min_char_conf(field: dict | None) -> float:
    if not field:
        return 0.0
    confs: list[float] = []
    for ln in field.get("lines") or []:
        confs.extend(ln.get("char_conf") or [])
    return min(confs) if confs else 0.0


def n_lines(field: dict | None) -> int:
    if not field:
        return 0
    return len(field.get("lines") or [])


def box_h(field: dict | None) -> float:
    if not field or not field.get("box"):
        return 0.0
    return float(field["box"][3])


def clean_cyr_text(text: str) -> str:
    """Latin/digit homoglyphs → Cyrillic; collapse whitespace."""
    text = (text or "").upper().replace("Ё", "Ё")
    text = text.translate(LATIN_HOMO)
    out = []
    for ch in text:
        if ch.isascii() and ch.isalpha():
            out.append(ch.translate(LATIN_HOMO))
        else:
            out.append(ch)
    text = "".join(out)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def apply_token_fix(text: str) -> str:
    text = text.replace("БЧРЯТ", "БУРЯТ")
    parts = []
    for tok in text.split(" "):
        parts.append(TOKEN_FIX.get(tok, tok))
    return " ".join(parts)


def fix_birth_place(text: str) -> str:
    text = clean_cyr_text(text)
    text = apply_token_fix(text)
    text = re.sub(r"^(Г|С|Д|П|Х|ГОР|ДЕР|ПОС|ХУТ|СТАН)(\s+)", r"\1. ", text)
    text = re.sub(r"\bОБЛ$", "ОБЛ.", text)
    text = re.sub(r"\bКР$", "КР.", text)
    text = re.sub(r"\bРЕСП$", "РЕСП.", text)
    text = re.sub(r" +", " ", text).strip()
    return text


def fix_org(text: str) -> str:
    text = clean_cyr_text(text)
    text = apply_token_fix(text)
    text = re.sub(r"\.(В|ПО|НА|И)\b", r". \1", text)
    text = re.sub(r" +", " ", text).strip()
    return text


def parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return None


def add_years(d: date, years: int) -> date:
    try:
        return date(d.year + years, d.month, d.day)
    except ValueError:
        return date(d.year + years, d.month, monthrange(d.year + years, d.month)[1])


def age_years(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def passport_valid(birth: date, issue: date, as_of: date = AS_OF) -> bool:
    if issue < birth or issue > as_of:
        return False
    if age_years(birth, issue) < 14:
        return False
    age_iss = age_years(birth, issue)
    if age_iss < 20:
        return as_of <= add_years(birth, 20) + timedelta(days=90)
    if age_iss < 45:
        return as_of <= add_years(birth, 45) + timedelta(days=90)
    return True


def yymmdd_birth(s: str) -> str | None:
    if not re.fullmatch(r"\d{6}", s):
        return None
    yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    year = 2000 + yy if yy <= 26 else 1900 + yy
    try:
        date(year, mm, dd)
    except ValueError:
        return None
    if year < 1945 or year > 2015:
        return None
    return f"{dd:02d}.{mm:02d}.{year}"


def yymmdd_issue(s: str) -> str | None:
    if not re.fullmatch(r"\d{6}", s):
        return None
    yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    year = 1900 + yy if yy >= 90 else 2000 + yy
    try:
        date(year, mm, dd)
    except ValueError:
        return None
    if year < 1997 or year > 2026:
        return None
    return f"{dd:02d}.{mm:02d}.{year}"


def pad44(s: str) -> str:
    s = re.sub(r"[^A-Z0-9<]", "<", (s or "").upper().replace(" ", ""))
    if len(s) < 44:
        s = s + "<" * (44 - len(s))
    return s[:44]


def parse_mrz(mrz: dict | None) -> dict | None:
    if not mrz or not mrz.get("lines") or len(mrz["lines"]) < 2:
        return None
    l1 = pad44(mrz["lines"][0].get("text") or "")
    l2 = pad44(mrz["lines"][1].get("text") or "")
    cnum_ok = check_digit(l2[0:9]) == l2[9]
    cb_ok = check_digit(l2[13:19]) == l2[19]
    copt_ok = check_digit(l2[28:42]) == l2[42]
    comp_ok = check_digit(l2[0:10] + l2[13:20] + l2[21:43]) == l2[43]
    if not (cnum_ok and cb_ok and copt_ok and comp_ok):
        return None
    if l2[10:13] != "RUS":
        return None
    if l2[20] not in "MF":
        return None
    opt = l2[28:42]
    m = re.fullmatch(r"([0-9])(\d{6})(\d{6})<?", opt)
    if not m:
        return None
    issue = yymmdd_issue(m.group(2))
    code6 = m.group(3)
    birth = yymmdd_birth(l2[13:19])
    if not issue or not birth:
        return None
    code = f"{code6[:3]}-{code6[3:]}"
    names = l1[5:] if l1.startswith(("PNRUS", "P<RUS")) else l1[5:]
    parts = names.split("<<", 1)
    surname = re.sub(r"<+", "", parts[0])
    given = parts[1] if len(parts) > 1 else ""
    gparts = [p for p in given.split("<") if p]
    min1 = min(mrz["lines"][0].get("char_conf") or [0.0])
    min2 = min(mrz["lines"][1].get("char_conf") or [0.0])
    return {
        "num9": l2[0:9],
        "sex": "МУЖ." if l2[20] == "M" else "ЖЕН.",
        "birth": birth,
        "issue": issue,
        "code": code,
        "surname": surname,
        "gparts": gparts,
        "min1": min1,
        "min2": min2,
        "l1": l1,
        "l2": l2,
    }


def extract_digits(text: str) -> str:
    trans = str.maketrans({"О": "0", "O": "0", "З": "3", "Ч": "4", "Б": "6"})
    chars = []
    for ch in (text or "").upper().translate(trans):
        if ch.isdigit():
            chars.append(ch)
    return "".join(chars)


def names_agree(viz_last: str, viz_first: str, viz_mid: str, mrz: dict) -> bool:
    t_last = translit(viz_last)
    t_first = translit(viz_first)
    t_mid = translit(viz_mid)
    m_last = mrz["surname"]
    m_rest = "".join(mrz["gparts"])
    if t_last != m_last:
        return False
    if t_first + t_mid != m_rest:
        return False
    if t_first:
        acc = ""
        found = False
        for p in mrz["gparts"]:
            acc += p
            if acc == t_first:
                found = True
                break
        if not found:
            return False
    return True


def has_invalid_raion_abbr(text: str) -> bool:
    for tok in re.findall(r"Р-[А-ЯЁ]+", text.replace(")", "").replace("(", "")):
        if tok not in VALID_RAION:
            return True
    return False


def looks_truncated_place(text: str, field: dict | None) -> bool:
    if not text:
        return True
    if field and box_h(field) >= 50 and n_lines(field) == 1:
        return True
    tokens = text.split()
    first, last = tokens[0], tokens[-1]
    if first in {"Р-НА", "РАЙОНА", "Р-Н", "РАЙОН", "ОБЛ.", "ОБЛАСТИ", "КР.", "РЕСП."}:
        return True
    if last.endswith(("СКОГО", "ЦКОГО")):
        return True
    if last in {"ПО", "В", "НА", "И"}:
        return True
    return False


def looks_truncated_org(text: str, field: dict | None) -> bool:
    if not text:
        return True
    if field and box_h(field) >= 40 and n_lines(field) == 1:
        return True
    if field and box_h(field) >= 75 and n_lines(field) == 2:
        return True
    tokens = text.split()
    last = tokens[-1]
    if last in {"ПО", "В", "НА", "И"}:
        return True
    if tokens[0] in {"РОССИИ", "ПО", "В"}:
        return True
    first = re.sub(r"[^А-ЯЁ0-9.-]", "", tokens[0])
    if first and first not in {s.rstrip(".") for s in ORG_START} and not first.isdigit():
        if not any(text.startswith(p) for p in ORG_START):
            if len(text) < 20:
                return True
    return False


def load_subdivisions(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code, name = row.get("code") or "", row.get("name") or ""
            if code and name:
                out[code].append(name)
    return out
class Engine:
    def __init__(self, root: Path):
        self.known_codes = set(load_subdivisions(root / "reference" / "subdivisions.csv"))
        if not self.known_codes:
            raise RuntimeError("empty subdivisions.csv")

    def process(self, doc: dict) -> dict:
        doc_id = doc["doc_id"]
        rejected = {"doc_id": doc_id, "decision": "reject", "fields": {}}
        quality = doc.get("quality") or {}
        if quality.get("sharpness", 0) < MIN_SHARPNESS:
            return rejected
        if quality.get("doc_px", 0) < MIN_DOC_PX:
            return rejected
        if quality.get("glare", 1) > MAX_GLARE:
            return rejected

        viz = doc.get("viz") or {}
        mrz = parse_mrz(doc.get("mrz"))
        if not mrz:
            return rejected
        if mrz["min2"] < 0.90:
            return rejected

        birth = mrz["birth"]
        issue = mrz["issue"]
        code = mrz["code"]
        sex = mrz["sex"]
        birth_d = parse_date(birth)
        issue_d = parse_date(issue)
        if not birth_d or not issue_d:
            return rejected
        if not passport_valid(birth_d, issue_d):
            return rejected

        for fname, mval, parser in (
            ("Birth_date", birth, lambda s: s),
            ("Issue_date", issue, lambda s: s),
            ("Issue_organisation_code", code, lambda s: re.sub(r"\s+", "", s).replace(" ", "")),
            ("Sex_ru", sex, lambda s: s.replace(" ", "")),
        ):
            field = viz.get(fname)
            vt = viz_join(field)
            if vt and min_char_conf(field) >= 0.99:
                vt_n = norm_cmp(vt)
                if fname == "Issue_organisation_code":
                    vt_n = re.sub(r"[^0-9-]", "", vt_n)
                    if re.fullmatch(r"\d{6}", vt_n):
                        vt_n = vt_n[:3] + "-" + vt_n[3:]
                if fname == "Sex_ru":
                    if "МУЖ" in vt_n:
                        vt_n = "МУЖ."
                    elif "ЖЕН" in vt_n:
                        vt_n = "ЖЕН."
                if vt_n and vt_n != norm_cmp(mval):
                    return rejected

        last_f, first_f, mid_f = viz.get("Last_name_ru"), viz.get("First_name_ru"), viz.get("Middle_name_ru")
        last = clean_cyr_text(viz_join(last_f) or "")
        first = clean_cyr_text(viz_join(first_f) or "")
        mid = clean_cyr_text(viz_join(mid_f) or "")
        if not last or not first:
            return rejected
        if min_char_conf(last_f) < MIN_CC["Last_name_ru"]:
            return rejected
        if min_char_conf(first_f) < MIN_CC["First_name_ru"]:
            return rejected
        if mid_f and min_char_conf(mid_f) < MIN_CC["Middle_name_ru"]:
            return rejected
        if not names_agree(last, first, mid, mrz):
            return rejected
        for val in (last, first, mid):
            if val and not re.fullmatch(r"[А-ЯЁ]+(?:[ -][А-ЯЁ]+)*", val):
                return rejected

        lic_f = viz.get("Licence_number")
        lic_raw = viz_join(lic_f) or ""
        digits = extract_digits(lic_raw)
        if len(digits) != 10:
            return rejected
        if digits[0:3] + digits[4:] != mrz["num9"]:
            return rejected
        if min_char_conf(lic_f) < MIN_CC["Licence_number"]:
            return rejected
        series_yy = int(digits[2:4])
        issue_yy = issue_d.year % 100
        delta = (series_yy - issue_yy) % 100
        if delta not in {0, 97, 98, 99} and not (-3 <= series_yy - issue_yy <= 0):
            return rejected
        licence = f"{digits[0:2]} {digits[2:4]} {digits[4:10]}"

        bp_f = viz.get("Birth_place_ru")
        bp = viz_join(bp_f)
        if not bp:
            return rejected
        bp = fix_birth_place(bp)
        if min_char_conf(bp_f) < MIN_CC["Birth_place_ru"]:
            return rejected
        if looks_truncated_place(bp, bp_f):
            return rejected
        if has_invalid_raion_abbr(bp):
            return rejected
        if not re.fullmatch(r"[0-9А-ЯЁ. «»\"'№/()-]+", bp):
            return rejected
        if len(bp) < 5:
            return rejected

        org_f = viz.get("Issue_organization_ru")
        org = viz_join(org_f)
        if not org:
            return rejected
        org = fix_org(org)
        if min_char_conf(org_f) < MIN_CC["Issue_organization_ru"]:
            return rejected
        if looks_truncated_org(org, org_f):
            return rejected
        if has_invalid_raion_abbr(org):
            return rejected
        if not re.fullmatch(r"[0-9А-ЯЁ. «»\"'№/()°-]+", org):
            return rejected
        if len(org) < 11:
            return rejected

        fields = {
            "Last_name_ru": last,
            "First_name_ru": first,
            "Middle_name_ru": mid,
            "Sex_ru": sex,
            "Birth_date": birth,
            "Birth_place_ru": bp,
            "Issue_date": issue,
            "Issue_organisation_code": code,
            "Licence_number": licence,
            "Issue_organization_ru": org,
        }
        return {"doc_id": doc_id, "decision": "accept", "fields": fields}


def find_root(pred_path: Path) -> Path:
    here = Path(__file__).resolve().parent
    for cand in (here, pred_path.resolve().parent.parent, Path.cwd()):
        if (cand / "reference" / "subdivisions.csv").exists():
            return cand
    return here


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: python postprocess.py <predictions.jsonl> <answers.jsonl>", file=sys.stderr)
        sys.exit(2)
    pred_path = Path(argv[0])
    out_path = Path(argv[1])
    engine = Engine(find_root(pred_path))
    n_acc = 0
    n = 0
    with pred_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            ans = engine.process(doc)
            n += 1
            if ans["decision"] == "accept":
                n_acc += 1
            fout.write(json.dumps(ans, ensure_ascii=False) + "\n")
    print(f"processed {n}, accepted {n_acc}", file=sys.stderr)


if __name__ == "__main__":
    main()
