"""Load the real IT-support tickets and keep the English, IAM-relevant ones.

Source: tasksource/it-support-tickets (2,229 real anonymized tickets, CC-BY-4.0)
https://huggingface.co/datasets/tasksource/it-support-tickets

    python src/load_tickets.py            # -> data/raw_tickets.jsonl (+ prints stats)
    python src/load_tickets.py --all      # also dump every ticket to data/all_tickets.jsonl for inspection
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from datasets import load_dataset

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw_tickets.jsonl"

# IAM keyword -> rough intent hint (only used to seed scenario generation; labels come from rules later)
IAM_KEYWORDS = {
    "grant": r"\b(access|permission|permissions|rights|authori[sz]ation|grant|add (?:to|user)|member(?:ship)?|shared? ?drive|file ?share|folder|sharepoint|teams? channel|distribution list|group)\b",
    "create_account": r"\b(new (?:user|employee|account|hire|colleague)|create (?:user|account)|user creation|onboard\w*|new starter|joiner)\b",
    "revoke": r"\b(revoke|remove (?:access|user|permission)|withdraw)\b",
    "disable": r"\b(disable|deactivate|leaving employee|leaver|terminat\w+|offboard\w*|exit|block (?:user|account))\b",
    "admin": r"\b(admin|administrator|privileged|elevated|root|local admin)\b",
    "mailbox": r"\b(mailbox|shared mailbox|mail ?box|email account|calendar access|delegate)\b",
    "password": r"\b(password|passwort|reset|locked out|lockout|unlock|mfa|2fa|authenticator)\b",
    "guest": r"\b(guest|external user|contractor|vendor account|visitor)\b",
    "security": r"\b(phishing|phish|compromis\w+|suspicious|hacked|malware|spam|security|breach|stolen)\b",
    "account": r"\b(account|user ?name|login|log ?in|sign ?in|active directory|\bAD\b)\b",
}
IAM_RE = {k: re.compile(v, re.I) for k, v in IAM_KEYWORDS.items()}

# Cheap language filter: count common function words per language
STOPWORDS = {
    "en": "the and to for of is please with on in from you can not have this access user new".split(),
    "de": "und der die das nicht ist bitte mit für ein eine von zu auf den ich sie benutzer zugriff".split(),
    "pt": "de que não para com uma por os as do da em acesso usuário favor está".split(),
    "es": "el la los las que para con por una del acceso usuario favor está".split(),
}


def language(text):
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    scores = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
    if re.search(r"[äöüß]", text.lower()):
        scores["de"] += 2
    if re.search(r"[ãõçáéíóú]", text.lower()):
        scores["pt"] += 1
        scores["es"] += 1
    best = max(scores, key=scores.get)
    # Short title-style tickets often have no stopwords; treat them as English if they're plain ASCII
    if scores[best] == 0:
        return "en" if text.isascii() else "unknown"
    return best


def template_key(text):
    t = re.sub(r"\[[A-Z _]+\]", " ", text)          # masked placeholders
    t = re.sub(r"\b(new support ticket received|a support ticket was forwarded to your role|rv|fw|re)\b", " ", t, flags=re.I)
    t = re.sub(r"[^a-z]+", " ", t.lower())            # digits, punctuation
    return " ".join(t.split())


def main():
    ds = load_dataset("tasksource/it-support-tickets")
    labels = ds["train"].features["label"].names

    rows, langs, cats = [], Counter(), Counter()
    for split in ds:
        for i, r in enumerate(ds[split]):
            text = " ".join(r["text"].split())
            lang = language(text)
            langs[lang] += 1
            hits = [k for k, rx in IAM_RE.items() if rx.search(text)]
            row = {
                "ticket_id": f"{split}-{i:04d}",  # stable ID = the ticket family for splitting later
                "source_split": split,
                "category": labels[r["label"]],
                "lang": lang,
                "iam_hints": hits,
                "text": text,
            }
            if "--all" in sys.argv:
                rows.append(row)
            elif lang == "en" and hits:
                rows.append(row)
                cats[row["category"]] += 1

    # Most tickets are the same templated title ("File Share Access - [TICKET ID] - [NAME] ...").
    # Keep one row per template and record how often it occurred (useful for the business story).
    if "--all" not in sys.argv:
        by_key = {}
        for row in rows:
            key = template_key(row["text"])
            if key in by_key:
                by_key[key]["occurrences"] += 1
            else:
                by_key[key] = {**row, "occurrences": 1}
        print(f"deduplicated {len(rows)} -> {len(by_key)} unique ticket templates")
        rows = sorted(by_key.values(), key=lambda r: -r["occurrences"])
        cats = Counter(r["category"] for r in rows)

    out = ROOT / "data" / ("all_tickets.jsonl" if "--all" in sys.argv else "raw_tickets.jsonl")
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    total = sum(langs.values())
    print(f"loaded {total} tickets | languages: {dict(langs.most_common())}")
    print(f"wrote {len(rows)} rows -> {out.relative_to(ROOT)}")
    if cats:
        print("kept by category:", dict(cats.most_common()))
        hint_counts = Counter(h for r in rows for h in r["iam_hints"])
        print("IAM hints:", dict(hint_counts.most_common()))


if __name__ == "__main__":
    main()
