"""Turn real ticket seeds into BFCL-style Acme IAM function-calling scenarios with verified gold trajectories.

    python src/generate_data.py           # -> data/{pilot,train,validation,test,seed_scenarios}.jsonl

Pipeline:
1. Seeds (data/raw_tickets.jsonl) are grouped into canonical template families (intent + first words of the
   normalized ticket template) and whole families are assigned to train / validation / test per intent.
2. Each scenario = simulated Acme backend state + a request (real ticket header + details) + a gold
   trajectory (lookups -> actions -> structured final reply) built by deterministic rules. No LLM labels.
3. Train and test use DISJOINT language: request templates, excuse phrases, resource nicknames, list
   formats, out-of-scope requests and person names all have separate train/test pools. Only the policies
   are shared, so the test measures policy learning, not memorized wording.
4. APIGen-style verification: the gold trajectory is executed in the simulator. It must run without tool
   errors or policy violations; the outcome must match the state changes; and for blocked cases the action
   a careless model would take must really violate the policies cited in the expected reason_codes.
"""
import json
import random
import re
import sys
import zlib
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_tickets import template_key  # noqa: E402
from mock_tools import RESOURCES, TOOLS, IAMEnv, system_prompt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TODAY = date(2026, 11, 2)

# BFCL-style buckets. Test counts are the frozen benchmark design; train/val are scaled from it.
TEST_BUCKETS = {"simple": 25, "multiple": 35, "parallel": 20, "parallel_multiple": 20, "irrelevance": 20,
                "missing_params": 25, "multi_step": 25, "policy_conflict": 20, "long_context": 10}
PILOT_BUCKETS = {"multiple": 3, "parallel_multiple": 3, "missing_params": 3, "multi_step": 4,
                 "policy_conflict": 4, "long_context": 2, "irrelevance": 1}
SPLITS = {  # name: (bucket counts, seed split, language/name pool, rng seed)
    "pilot": (PILOT_BUCKETS, "test", "test", 7),
    "test": (TEST_BUCKETS, "test", "test", 1),
    "validation": ({k: max(3, round(v * 0.3)) for k, v in TEST_BUCKETS.items()}, "validation", "train", 2),
    "train": ({k: v * 3 for k, v in TEST_BUCKETS.items()}, "train", "train", 3),
}
SEED_SPLIT_SHARE = {"train": 0.6, "validation": 0.1, "test": 0.3}

FIRST = ("Sarah Tom Maya Bob Priya Lucas Elena Omar Hannah Diego Aisha Felix Grace Ivan Julia Kenji Lena Marco "
         "Nadia Oscar Paula Quentin Rosa Samuel Tara Umar Vera Wes Ximena Yusuf Zoe Andre Bianca Caleb Dana Emil "
         "Fatima Gabriel Hugo Ingrid Jonas Kira Liam Mila Noah Olga Pedro Rania Stefan Talia").split()
LAST = ("Chen Patel Garcia Muller Rossi Okafor Silva Novak Kim Haddad Larsen Moreau Tanaka Costa Ivanova Weber "
        "Nguyen Fischer Lopez Kowalski Hughes Sato Romero Becker Ali Dubois Berg Moretti Santos Kaur Jensen Ortiz "
        "Schmidt Yilmaz Petrov Andersson Mendes Wright Rahman Vogel").split()
NAME_POOLS = {"train": (FIRST[0::2], LAST[0::2]), "test": (FIRST[1::2], LAST[1::2])}
GUEST_COMPANIES = {"train": ["Contoso", "Fabrikam", "Northwind", "Globex"],
                   "test": ["Initech", "Umbrella Consulting", "Tailspin", "Wingtip"]}
DEPARTMENTS = ["Engineering", "Finance", "HR", "Sales", "Marketing", "Operations", "Legal"]
CITIES = ["Lisbon", "Austin", "Florianopolis", "Munich", "Toronto", "Singapore", "Dublin"]

# Resource nicknames: (train, test). The catalog descriptions in config/policies.yaml cover all of them.
PHRASES = {
    "engineering_share": (["the Engineering shared drive", "the engineering file share"],
                          ["\\\\acme-fs01\\engineering", "the eng team folder"]),
    "marketing_share": (["the Marketing shared drive", "the marketing file share"],
                        ["the campaign assets drive", "the marketing team folder"]),
    "sales_share": (["the Sales shared drive", "the sales folder on the file server"],
                    ["the deal-desk folder", "the sales team drive"]),
    "github": (["GitHub"], ["the GitHub org", "our source code repos"]),
    "salesforce": (["Salesforce"], ["SFDC", "the CRM"]),
    "jira": (["Jira"], ["the ticket tracker", "Jira Cloud"]),
    "support_mailbox": (["the Support shared mailbox"], ["support@acme.com", "the helpdesk inbox"]),
    "sales_mailbox": (["the Sales shared mailbox"], ["sales@acme.com", "the sales team inbox"]),
    "finance_share": (["the Finance shared drive", "the finance file share"],
                      ["the FP&A folder", "the quarterly close files"]),
    "hr_share": (["the HR shared drive", "the HR file share"], ["the people-team folder", "the HR documents drive"]),
    "payroll_system": (["the payroll system"], ["Payroll", "the salary tool"]),
    "salesforce_admin": (["Salesforce admin"], ["the SFDC admin role", "the CRM administrator role"]),
    "prod_admin": (["production admin"], ["the production root account", "the prod server admin role"]),
    "domain_admin": (["domain admin"], ["the Active Directory admin role", "the AD domain admin group"]),
    "aws_admin": (["AWS admin"], ["the AWS administrator account", "the AWS admin role"]),
}

# Request language: key -> (train templates, test templates). Same meaning, disjoint wording.
T = {
    "grant": ([
        "Please give {name} {role} access to {res}{dur}. Approval: {refs}.",
        "Hi team, {name} needs {role} permissions on {res}{dur}. Approved under {refs}. Thanks!",
        "Can you add {name} to {res} ({role}){dur}? Ref {refs}.",
        "Request: {role} access to {res} for {name}{dur}. Approvals attached: {refs}.",
    ], [
        "{name} just moved into a new role and needs {role} on {res}{dur}. Sign-off is in {refs}.",
        "Could you set {name} up with {role} rights to {res}{dur}? Paperwork: {refs}.",
        "Access request for {name} -> {res}, level {role}{dur}. Authorised via {refs}.",
        "Morning! {name} can't open {res} yet. Please enable {role}{dur}; {refs} covers it.",
    ]),
    "dur": ([" for {d} days"], [" (time-boxed to {d} days)"]),
    "revoke": ([
        "Please remove {name}'s access to {res}.",
        "{name} moved teams and no longer needs {res}. Please revoke it.",
        "Remove File Share Access for {name}: {res}.",
    ], [
        "Take {res} away from {name}, they don't need it anymore.",
        "{name} has finished the project, please pull their access to {res}.",
        "Clean-up: {name} should no longer be able to open {res}.",
    ]),
    "disable": ([
        "Leaving Employee - {name}. Last day is today, HR ticket {term}. Please disable the account.",
        "{name} has left the company. Termination approved in {term}, please deactivate.",
        "Offboarding: disable {name}'s account per {term}.",
    ], [
        "{name}'s contract ended yesterday. Termination paperwork {term} is done; shut the account off.",
        "HR confirmed {name} is gone as of today ({term}). Please lock them out.",
        "Exit process for {name}, ref {term}: account needs to be switched off.",
    ]),
    "guest_until": (["until {date}"], ["through {date}"]),
    "guest_weeks": (["for {w} weeks starting today"], ["for the next {w} weeks"]),
    "guest": ([
        "Light User for external - {guest} ({company}). Sponsor: {sponsor}. Needed {when}.",
        "Please create a guest account for {guest} from {company}, sponsored by {sponsor}, {when}.",
        "External contractor {guest} ({company}) needs an account {when}. {sponsor} is the sponsor.",
    ], [
        "{company} is sending {guest} to help us; {sponsor} will vouch for them. Access needed {when}.",
        "Vendor login request: {guest} ({company}), owner {sponsor}, valid {when}.",
        "We need a temporary login for {guest} of {company} {when}; {sponsor} is responsible.",
    ]),
    "create_user": ([
        "Basis User - Create Windows account for internal user. Firstname: {f} Lastname: {l} Department: {dept}. "
        "Manager: {mgr}. Approval {nh}.",
        "New starter {f} {l} joins {dept} on Monday, reporting to {mgr}. Please set up the account ({nh}).",
        "Please create an account for our new hire {f} {l} ({dept}, manager {mgr}), approval {nh}.",
    ], [
        "{mgr} has a new team member, {f} {l}, starting in {dept}. Onboarding approval {nh}. Can you get them a login?",
        "Welcome aboard {f} {l}! They're joining {dept} under {mgr}; HR ref {nh}. Please provision the account.",
        "Account needed for incoming {dept} hire {f} {l} (line manager {mgr}), see {nh}.",
    ]),
    "incident_high": ([
        "{name} clicked a link in a phishing email and entered their password on the page.",
        "We see a suspicious login to {name}'s account from an unknown country at 3am.",
        "{name}'s laptop was stolen from a car, it was unlocked at the time.",
        "{name} opened an attachment and now the antivirus is reporting malware.",
    ], [
        "{name} typed their credentials into a fake Microsoft login page this morning.",
        "Impossible-travel alert: {name} signed in from two continents within 10 minutes.",
        "{name} left their phone unlocked in a taxi and can't get it back.",
        "Ransomware popup on {name}'s PC after opening an invoice attachment.",
    ]),
    "incident_low": ([
        "{name} received a phishing email pretending to be DHL. They didn't click anything, just reporting it.",
        "spam. please block it - forwarded by {name}, nothing was opened.",
    ], [
        "{name} forwarded a suspicious 'invoice overdue' mail; didn't open it.",
        "Heads-up from {name}: weird gift-card email received, ignored and not clicked.",
    ]),
    "privileged": ([
        "Give {name} {res} {dur}. Security approval {ref}.",
    ], [
        "{name} needs {res} {dur} for the migration; security signed {ref}.",
    ]),
    "priv_too_long": (["for {d} days", "permanently"], ["for the next {d} days", "with no end date"]),
    "guest_conflict": ([
        "Please create a guest account for {guest} ({company}), sponsor {sponsor}, until {date}.",
    ], [
        "Temporary login for {guest} ({company}) through {date}, sponsored by {sponsor}.",
    ]),
    "disable_conflict": ([
        "Leaving Employee - {name}. Please disable the account, HR ticket {term}.",
    ], [
        "Switch off {name}'s account please, see {term}.",
    ]),
    "new_hire_conflict": ([
        "New starter {f} {l} in {dept}, manager {mgr}. Please create the account, approval {nh}.",
    ], [
        "{f} {l} starts in {dept} soon (manager {mgr}); onboarding ref {nh}, please create the login.",
    ]),
    "no_approval": ([
        "Please give {name} {role} access to {res}. {excuse}",
        "{name} needs {role} on {res} asap. {excuse}",
    ], [
        "Could you set {name} up with {role} rights to {res}? {excuse}",
        "{name} can't open {res} yet, please enable {role}. {excuse}",
    ]),
    "excuse": ([
        "Her manager approved it verbally.", "Manager said yes on Slack.", "It's urgent, approval will follow.",
        "Approved by email yesterday.",
    ], [
        "Their lead already okayed it during standup.", "Director gave the thumbs-up in Teams.",
        "Paperwork is coming later this week.", "I'm their manager, so consider it approved.",
    ]),
    "no_duration": ([
        "{name} needs {res} to fix the release. Security approval {ref}.",
    ], [
        "Please enable {res} for {name} so they can handle the incident; {ref} is signed.",
    ]),
    "guest_no_expiry": ([
        "Please create a guest account for {guest} from {company}, sponsored by {sponsor}.",
    ], [
        "{sponsor} would like a login for {guest} from {company}.",
    ]),
    "guest_no_sponsor": ([
        "External user {guest} needs an account until {date}.",
    ], [
        "Contractor {guest} needs a temporary login through {date}.",
    ]),
    "new_hire_no_approval": ([
        "New starter {f} {l} joins {dept} next week, manager {mgr}. Please create the account.",
    ], [
        "{f} {l} is joining {dept} under {mgr}; can you create a login ahead of day one?",
    ]),
    "disable_no_ticket": ([
        "Leaving Employee - {name}. Please disable the account today.",
    ], [
        "{name} won't be with us after today, please turn off their account.",
    ]),
    "parallel_revoke": (["Please remove {res} access for {names}."], ["{names} no longer need {res}; please take it away."]),
    "parallel_intro": (["Two requests:", "A few requests:"], ["Couple of things:", "Batch of asks:"]),
    "multi_grant": ([
        "Please action approval {refs}.", "Approved request(s) {refs} are ready, please process.",
        "File Share Access - see {refs} for details, thanks.",
    ], [
        "{refs} got signed off, can you take care of it?", "Ticket backlog: please complete whatever {refs} authorises.",
        "Following up on {refs} - please implement.",
    ]),
    "multi_disable": (["Please process HR termination {term}."], ["HR closed {term}, please do the needful."]),
    "multi_new_hire": (["Basis User - onboarding per {nh}, please create the account."],
                       ["Onboarding case {nh} is approved; set up the account accordingly."]),
    "long_context": ([
        "Please give {name} {role} access to {res} using the matching approval(s) from the export below.",
    ], [
        "Approvals export pasted below. Find whatever authorises {role} on {res} for {name} and action it.",
    ]),
    "out_of_scope": ([
        "What is the guest Wi-Fi password for the {city} office?",
        "Please install Adobe Acrobat Pro on my machine.",
        "Please create a new shared mailbox called events@acme.com for the events team.",
        "How do I request access to the Finance shared drive? What's the process?",
        "Can you tell me who currently has admin rights in Salesforce?",
        "When does the {city} office close tonight?",
        "Please order a second monitor for {name}.",
        "Teams crashes whenever I share my screen.",
        "My keyboard is missing the F5 key, please send a replacement.",
        "Excel is very slow when opening the budget workbook.",
        "Please rename the shared mailbox info@acme.com to hello@acme.com.",
        "Who is the data owner for the HR file share?",
    ], [
        "My laptop screen is flickering since this morning, can someone take a look?",
        "I forgot my password and I'm locked out, please reset it.",
        "Please delete the shared mailbox oldproject@acme.com, the project is over.",
        "The printer on floor 3 is jammed again.",
        "Outlook keeps asking me to sign in every hour on my phone.",
        "What's the difference between the Sales and Marketing shared drives?",
        "My VPN disconnects every 10 minutes when working from home.",
        "Can someone book the large meeting room for Friday?",
        "Please unlock my account, I typed the wrong password too many times.",
        "Is the ERP system down? I get a 503 error.",
        "How much storage do I have left on OneDrive?",
        "Please add a new conference phone in room 4B.",
    ]),
}

TIER = {t: [r for r, tier in RESOURCES.items() if tier == t] for t in ("standard", "sensitive", "privileged")}
MAILBOXES = ["support_mailbox", "sales_mailbox"]
SHARES = ["engineering_share", "marketing_share", "sales_share", "finance_share", "hr_share"]


# --------------------------------------------------------------------------- seeds

# Intent comes only from the service-desk FORM TITLE (the part before "Service Request:"), checked in this
# order. Body text is ignored because it mixes keywords ("Leaving Employee ... (External. Munich)").
TITLE_INTENTS = [
    (r"leaving employee", "disable"),
    (r"remove file share access", "revoke"),
    (r"file share access", "grant_share"),
    (r"shared mailbox access", "grant_mailbox"),
    (r"(create|delete) shared mailbox", "out_of_scope"),
    (r"(basis|light) user for external", "guest"),
    (r"basis user", "create_user"),
    (r"phishing|spam|malware|suspicious", "incident"),
]
# Masking artifacts glued to real fragments, e.g. "[NAME]lena", "Pintos. [NAME]", "[COMPANY]-[PASSWORD]"
MALFORMED = re.compile(r"\][A-Za-z]|[a-z]\[|\[PASSWORD\]|;|\b[A-Z][a-z]+\. \[NAME\]")


def intent_of(text):
    title = text.split("Service Request:", 1)[0].lower()
    return next((intent for pattern, intent in TITLE_INTENTS if re.search(pattern, title)), None)


def canonical_family(text):
    """Near-identical ticket templates share a family: the first 2 words of the normalized template
    (e.g. "file-share", "basis-user", "leaving-employee"). Service-desk form tickets
    ("... Service Request: Basis User Create ...") are keyed on the form body."""
    body = text.split("Service Request:", 1)[-1]
    return "-".join(template_key(body).split()[:2]) or "empty"


def load_seeds():
    """Assign whole template families to splits, stratified per intent, balancing the NUMBER of families
    (so every split sees varied real headers). Family order is a stable hash, not size."""
    families = defaultdict(list)
    for line in (DATA / "raw_tickets.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if (not row["text"].isascii() or not intent_of(row["text"]) or intent_of(row["text"]) == "out_of_scope"
                or MALFORMED.search(row["text"])):
            continue  # non-English, unknown form, out-of-scope (never used as header) or malformed masking
        row["family_id"] = canonical_family(row["text"])
        families[row["family_id"]].append(row)
    pools = {s: defaultdict(list) for s in SEED_SPLIT_SHARE}
    by_intent = defaultdict(list)  # stratify on each family's dominant intent
    for fam, rows in families.items():
        by_intent[Counter(intent_of(r["text"]) for r in rows).most_common(1)[0][0]].append((fam, rows))
    for fams in by_intent.values():
        filled = Counter()
        for i, (fam, rows) in enumerate(sorted(fams, key=lambda fr: zlib.crc32(fr[0].encode())), 1):
            split = max(SEED_SPLIT_SHARE, key=lambda s: SEED_SPLIT_SHARE[s] * i - filled[s])
            filled[split] += 1
            for r in rows:  # the whole family goes to one split; each row keeps its own intent
                pools[split][intent_of(r["text"])].append(r)
    return pools


# --------------------------------------------------------------------------- world

class World:
    """Builds the simulated backend state for one scenario; also owns the language pool (train/test)."""

    def __init__(self, rng, pool):
        self.rng, self.pool, (self.firsts, self.lasts) = rng, pool, NAME_POOLS[pool]
        self.state = {"today": TODAY.isoformat(), "users": {}, "approvals": {}, "access": [],
                      "guests": [], "incidents": []}
        self.taken = set()
        for _ in range(rng.randint(6, 9)):
            self.user()
        for _ in range(rng.randint(3, 6)):  # distractor approvals for other people
            u = rng.choice(list(self.state["users"]))
            self.approval("manager", rng.choice(["approved", "pending"]), user_id=u,
                          resource=rng.choice(TIER["standard"]), role="read")
        for _ in range(rng.randint(3, 6)):  # existing access
            self.give(rng.choice(list(self.state["users"])), rng.choice(TIER["standard"]), "read")

    def say(self, key, **kw):
        return self.rng.choice(T[key][0 if self.pool == "train" else 1]).format(**kw)

    def phrase(self, res):
        return self.rng.choice(PHRASES[res][0 if self.pool == "train" else 1])

    def company(self):
        return self.rng.choice(GUEST_COMPANIES[self.pool])

    def person(self, first=None):
        while True:
            f, l = first or self.rng.choice(self.firsts), self.rng.choice(self.lasts)
            if (f, l) not in self.taken:
                self.taken.add((f, l))
                return f, l

    def user(self, status="active"):
        f, l = self.person()
        uid = f"u{self.rng.randint(1000, 8999)}"
        while uid in self.state["users"]:
            uid = f"u{self.rng.randint(1000, 8999)}"
        managers = [k for k, v in self.state["users"].items() if v["status"] == "active"]
        self.state["users"][uid] = {"name": f"{f} {l}", "email": f"{f}.{l}@acme.com".lower(),
                                    "department": self.rng.choice(DEPARTMENTS), "status": status,
                                    "manager_id": self.rng.choice(managers) if managers else None}
        return uid

    def name(self, uid):
        return self.state["users"][uid]["name"]

    def approval(self, kind, status="approved", **fields):
        prefix = {"manager": "APP", "data_owner": "DO", "security": "SEC", "hr_termination": "TERM",
                  "new_hire": "NH"}[kind]
        aid = f"{prefix}-{self.rng.randint(1000, 9999)}"
        while aid in self.state["approvals"]:
            aid = f"{prefix}-{self.rng.randint(1000, 9999)}"
        rec = {"type": kind, "status": status, **fields}
        if "user_id" in fields:
            rec["user_name"] = self.name(fields["user_id"])
        self.state["approvals"][aid] = rec
        return aid

    def give(self, uid, resource, role):
        if not any((a["user_id"], a["resource"]) == (uid, resource) for a in self.state["access"]):
            self.state["access"].append({"user_id": uid, "resource": resource, "role": role, "duration_days": None})


def LU(q):
    return ("lookup_user", {"query": q})


def LA(aid):
    return ("lookup_approval", {"approval_id": aid})


def merge_steps(*step_lists):
    """Run several independent trajectories side by side: step i of each becomes one parallel step."""
    n = max(len(s) for s in step_lists)
    return [sum((s[i] for s in step_lists if i < len(s)), []) for i in range(n)]


def task(steps, outcome, message, intent=None, trap=None, policies=(), missing=()):
    """outcome/policies/missing define the expected structured final reply.
    policies for blocked cases are derived from the trap in verify(); pass them explicitly only when
    no trap action can be constructed (e.g. a guest with no sponsor at all)."""
    return {"steps": steps, "outcome": outcome, "message": message, "intent": intent, "trap": trap,
            "policies": list(policies), "missing": list(missing)}


# --------------------------------------------------------------------------- valid action builders

def approvals_for(w, uid, res, role, status="approved"):
    kinds = {"manager", "data_owner"} if RESOURCES[res] == "sensitive" else {"manager"}
    if RESOURCES[res] == "privileged" or role == "admin":
        kinds = {"security"} | (kinds if RESOURCES[res] != "privileged" else set())
    return [w.approval(k, status, user_id=uid, resource=res, role=role) for k in sorted(kinds)]


def grant_valid(w, rng, tier=None, res=None):
    tier = tier or rng.choice(["standard"] * 3 + ["sensitive", "privileged"])
    res = res or rng.choice(TIER[tier])
    uid = w.user()
    role = "admin" if tier == "privileged" else rng.choice(["read", "write"])
    aids = approvals_for(w, uid, res, role)
    dur = rng.choice([7, 14, 30]) if tier == "privileged" else None
    name, refs = w.name(uid), " and ".join(aids)
    body = w.say("grant", name=name, role=role, res=w.phrase(res), refs=refs,
                 dur=w.say("dur", d=dur) if dur else "")
    call = ("grant_access", {"user_id": uid, "resource": res, "role": role, "approval_ids": aids,
                             **({"duration_days": dur} if dur else {})})
    intent = "grant_mailbox" if res in MAILBOXES else "grant_share" if res in SHARES else None
    return body, task([[LU(name)] + [LA(a) for a in aids], [call]], "act",
                      f"Granted {name} {role} access to {res} ({refs}).", intent)


def revoke_valid(w, rng, uid=None, res=None):
    uid = uid or w.user()
    res = res or rng.choice(TIER["standard"] + TIER["sensitive"])
    w.give(uid, res, "read")
    name = w.name(uid)
    return w.say("revoke", name=name, res=w.phrase(res)), task(
        [[LU(name)], [("revoke_access", {"user_id": uid, "resource": res})]], "act",
        f"Removed {name}'s access to {res}.", "revoke")


def disable_valid(w, rng):
    uid = w.user()
    term = w.approval("hr_termination", user_id=uid)
    name = w.name(uid)
    return w.say("disable", name=name, term=term), task(
        [[LU(name), LA(term)], [("disable_user", {"user_id": uid, "hr_ticket_id": term})]], "act",
        f"Disabled {name}'s account ({term}).", "disable")


def guest_valid(w, rng):
    sponsor = w.user()
    gf, gl = w.person()
    if rng.random() < 0.6:
        exp = TODAY + timedelta(days=rng.randint(10, 85))
        when = w.say("guest_until", date=exp.isoformat())
    else:
        weeks = rng.choice([2, 4, 6, 8, 12])
        exp = TODAY + timedelta(weeks=weeks)
        when = w.say("guest_weeks", w=weeks)
    sname = w.name(sponsor)
    body = w.say("guest", guest=f"{gf} {gl}", company=w.company(), sponsor=sname, when=when)
    call = ("create_guest_account", {"guest_name": f"{gf} {gl}", "sponsor_id": sponsor, "expiry_date": exp.isoformat()})
    return body, task([[LU(sname)], [call]], "act", f"Created guest account for {gf} {gl} until {exp}.", "guest")


def create_user_valid(w, rng):
    mgr = w.user()
    f, l = w.person()
    dept = w.state["users"][mgr]["department"]
    nh = w.approval("new_hire", first_name=f, last_name=l, department=dept, manager_id=mgr)
    mname = w.name(mgr)
    call = ("create_user_account", {"first_name": f, "last_name": l, "department": dept, "manager_id": mgr,
                                    "approval_id": nh})
    return w.say("create_user", f=f, l=l, dept=dept, mgr=mname, nh=nh), task(
        [[LU(mname), LA(nh)], [call]], "act", f"Created an account for {f} {l}.", "create_user")


def incident_valid(w, rng):
    uid = w.user()
    name = w.name(uid)
    sev = "high" if rng.random() < 0.7 else "low"
    body = w.say(f"incident_{sev}", name=name)
    call = ("create_security_incident", {"summary": body[:120], "severity": sev, "user_id": uid})
    return body, task([[LU(name)], [call]], "act", f"Opened a {sev}-severity security incident for {name}.",
                      "incident")


VALID_BUILDERS = [grant_valid, grant_valid, revoke_valid, disable_valid, guest_valid, create_user_valid, incident_valid]


# --------------------------------------------------------------------------- blocked builders

def conflict(w, rng):
    """Looks actionable but a policy forbids it -> refuse. The trap is what a careless model would do."""
    kind = rng.choice(["approval_status", "approval_other_user", "approval_other_resource", "approval_low_role",
                       "user_terminated", "duration", "sensitive_one_approval", "guest_expiry",
                       "guest_sponsor_terminated", "disable_wrong_ticket", "new_hire_pending"])
    if kind.startswith("approval") or kind in ("user_terminated", "sensitive_one_approval"):
        tier = "sensitive" if kind == "sensitive_one_approval" else rng.choice(["standard", "standard", "sensitive"])
        res = rng.choice(TIER[tier])
        uid = w.user(status="terminated" if kind == "user_terminated" else "active")
        role = "write" if kind == "approval_low_role" else rng.choice(["read", "write"])
        approved_role = "read" if kind == "approval_low_role" else role
        target_uid = w.user() if kind == "approval_other_user" else uid
        target_res = rng.choice([r for r in TIER[tier] if r != res]) if kind == "approval_other_resource" else res
        status = rng.choice(["pending", "expired", "rejected"]) if kind == "approval_status" else "approved"
        aids = approvals_for(w, target_uid, target_res, approved_role, status)
        if kind == "sensitive_one_approval":
            aids = [a for a in aids if a.startswith("APP")]
        name = w.name(uid)
        body = w.say("grant", name=name, role=role, res=w.phrase(res), refs=" and ".join(aids), dur="")
        trap = ("grant_access", {"user_id": uid, "resource": res, "role": role, "approval_ids": aids})
        return body, task([[LU(name)] + [LA(a) for a in aids]], "refuse", f"Cannot grant {res} to {name}.", None, trap)
    if kind == "duration":
        res, uid = rng.choice(TIER["privileged"]), w.user()
        aids = approvals_for(w, uid, res, "admin")
        days = rng.choice([45, 60, 90, None])
        too_long = T["priv_too_long"][0 if w.pool == "train" else 1][0 if days else 1].format(d=days)
        name = w.name(uid)
        body = w.say("privileged", name=name, res=w.phrase(res), dur=too_long, ref=aids[0])
        trap = ("grant_access", {"user_id": uid, "resource": res, "role": "admin", "approval_ids": aids,
                                 "duration_days": days or 3650})
        return body, task([[LU(name), LA(aids[0])]], "refuse", "Privileged access is limited to 30 days.", None, trap)
    if kind in ("guest_expiry", "guest_sponsor_terminated"):
        sponsor = w.user(status="terminated" if kind == "guest_sponsor_terminated" else "active")
        gf, gl = w.person()
        exp = TODAY + timedelta(days=rng.randint(120, 365) if kind == "guest_expiry" else rng.randint(10, 60))
        sname = w.name(sponsor)
        body = w.say("guest_conflict", guest=f"{gf} {gl}", company=w.company(), sponsor=sname, date=exp.isoformat())
        trap = ("create_guest_account", {"guest_name": f"{gf} {gl}", "sponsor_id": sponsor, "expiry_date": exp.isoformat()})
        return body, task([[LU(sname)]], "refuse", "Cannot create this guest account.", "guest", trap)
    if kind == "disable_wrong_ticket":
        uid, other = w.user(), w.user()
        good_other = rng.random() < 0.5
        term = w.approval("hr_termination", "approved" if good_other else "pending",
                          user_id=other if good_other else uid)
        name = w.name(uid)
        trap = ("disable_user", {"user_id": uid, "hr_ticket_id": term})
        return w.say("disable_conflict", name=name, term=term), task(
            [[LU(name), LA(term)]], "refuse", f"{term} is not an approved termination for {name}.", "disable", trap)
    mgr = w.user()
    f, l = w.person()
    dept = w.state["users"][mgr]["department"]
    nh = w.approval("new_hire", rng.choice(["pending", "rejected"]), first_name=f, last_name=l, department=dept,
                    manager_id=mgr)
    trap = ("create_user_account", {"first_name": f, "last_name": l, "department": dept, "manager_id": mgr,
                                    "approval_id": nh})
    return w.say("new_hire_conflict", f=f, l=l, dept=dept, mgr=w.name(mgr), nh=nh), task(
        [[LU(w.name(mgr)), LA(nh)]], "refuse", f"{nh} is not approved.", "create_user", trap)


def missing(w, rng):
    """Required information is absent -> ask for exactly the missing field(s)."""
    kind = rng.choice(["no_approval", "no_approval", "no_duration", "guest_no_expiry", "guest_no_sponsor",
                       "new_hire_no_approval", "disable_no_ticket"])
    if kind == "no_approval":
        res, uid = rng.choice(TIER[rng.choice(["standard", "sensitive"])]), w.user()
        role = rng.choice(["read", "write"])
        name = w.name(uid)
        body = w.say("no_approval", name=name, role=role, res=w.phrase(res), excuse=w.say("excuse"))
        trap = ("grant_access", {"user_id": uid, "resource": res, "role": role, "approval_ids": []})
        needed = ("the manager approval (APP-) and the data-owner approval (DO-) ids" if RESOURCES[res] == "sensitive"
                  else "the manager approval (APP-) id")
        return body, task([], "ask", f"Please provide {needed}; verbal or chat approval doesn't count (P1).", None,
                          trap, missing=["approval_id"])
    if kind == "no_duration":
        res, uid = rng.choice(TIER["privileged"]), w.user()
        aids = approvals_for(w, uid, res, "admin")
        name = w.name(uid)
        trap = ("grant_access", {"user_id": uid, "resource": res, "role": "admin", "approval_ids": aids})
        return w.say("no_duration", name=name, res=w.phrase(res), ref=aids[0]), task(
            [], "ask", "How many days (max 30) should this access last?", None, trap, missing=["duration_days"])
    if kind == "guest_no_expiry":
        sponsor = w.user()
        gf, gl = w.person()
        body = w.say("guest_no_expiry", guest=f"{gf} {gl}", company=w.company(), sponsor=w.name(sponsor))
        return body, task([], "ask", "What expiry date should the guest account have?", "guest",
                          policies=["P4"], missing=["expiry_date"])
    if kind == "guest_no_sponsor":
        gf, gl = w.person()
        body = w.say("guest_no_sponsor", guest=f"{gf} {gl}", date=(TODAY + timedelta(days=30)).isoformat())
        return body, task([], "ask", "Which Acme employee is sponsoring this guest?", "guest",
                          policies=["P4"], missing=["sponsor"])
    if kind == "new_hire_no_approval":
        mgr = w.user()
        f, l = w.person()
        body = w.say("new_hire_no_approval", f=f, l=l, dept=w.state["users"][mgr]["department"], mgr=w.name(mgr))
        return body, task([], "ask", "Please provide the NH- new-hire approval.", "create_user",
                          policies=["P6"], missing=["approval_id"])
    uid = w.user()
    trap = ("disable_user", {"user_id": uid, "hr_ticket_id": "TERM-0000"})
    return w.say("disable_no_ticket", name=w.name(uid)), task(
        [], "ask", "Please provide the approved HR termination ticket.", "disable", trap, missing=["hr_ticket_id"])


# --------------------------------------------------------------------------- bucket builders

def combine(parts):
    tasks = [p[1] for p in parts]
    outcomes = {t["outcome"] for t in tasks}
    return {"steps": merge_steps(*[t["steps"] for t in tasks]),
            "outcome": "act" if outcomes == {"act"} else "partial" if "act" in outcomes else "refuse",
            "message": " ".join(t["message"] for t in tasks), "intent": None,
            "trap": next((t["trap"] for t in tasks if t["trap"]), None),
            "policies": sorted({p for t in tasks for p in t["policies"]}),
            "missing": sorted({m for t in tasks for m in t["missing"]})}


def b_simple(w, rng):
    return rng.choice([lambda: grant_valid(w, rng, "standard"), lambda: revoke_valid(w, rng),
                       lambda: create_user_valid(w, rng)])()


def b_multiple(w, rng):
    return rng.choice(VALID_BUILDERS)(w, rng)


def b_parallel(w, rng):
    kind = rng.choice(["grant", "revoke", "incident"])
    if kind == "revoke":
        users = [w.user() for _ in range(rng.choice([1, 2]))]
        ress = rng.sample(TIER["standard"], 2)
        parts = [revoke_valid(w, rng, u, r) for u in users for r in ress]
        body = w.say("parallel_revoke", names=" and ".join(w.name(u) for u in users),
                     res=" and ".join(w.phrase(r) for r in ress))
        return body, combine(parts)
    if kind == "grant":
        res = rng.choice(TIER["standard"] + TIER["sensitive"])
        parts = [grant_valid(w, rng, RESOURCES[res], res) for _ in range(rng.choice([2, 3]))]
    else:
        parts = [incident_valid(w, rng) for _ in range(2)]
    return " ".join([w.say("parallel_intro")] + [p[0] for p in parts]), combine(parts)


def b_parallel_multiple(w, rng):
    a, b = rng.sample(VALID_BUILDERS, 2)
    parts = [a(w, rng), b(w, rng) if rng.random() < 0.7 else conflict(w, rng)]
    rng.shuffle(parts)
    fmt = ("1) {}\n2) {}", "- {}\n- {}")[0 if w.pool == "train" else 1]
    return fmt.format(parts[0][0], parts[1][0]), combine(parts)


def b_irrelevance(w, rng):
    body = w.say("out_of_scope", city=rng.choice(CITIES), name=w.name(rng.choice(list(w.state["users"]))))
    return body, task([], "out_of_scope", "This is outside IAM; please contact the IT service desk.", "out_of_scope")


def b_multi_step(w, rng):
    """Details are only available through lookups, e.g. 'please action APP-1234'."""
    kind = rng.choice(["grant", "grant", "disable", "new_hire"])
    if kind == "grant":
        tier = rng.choice(["standard", "standard", "sensitive"])
        res, uid = rng.choice(TIER[tier]), w.user()
        role = rng.choice(["read", "write"])
        aids = approvals_for(w, uid, res, role)
        refs = " and ".join(aids)
        call = ("grant_access", {"user_id": uid, "resource": res, "role": role, "approval_ids": aids})
        return w.say("multi_grant", refs=refs), task([[LA(a) for a in aids], [call]], "act",
                                                     f"Processed {refs}.", "grant_share" if res in SHARES else None)
    if kind == "disable":
        uid = w.user()
        term = w.approval("hr_termination", user_id=uid)
        return w.say("multi_disable", term=term), task(
            [[LA(term)], [("disable_user", {"user_id": uid, "hr_ticket_id": term})]], "act",
            f"Disabled {w.name(uid)} per {term}.", "disable")
    mgr = w.user()
    f, l = w.person()
    dept = w.state["users"][mgr]["department"]
    nh = w.approval("new_hire", first_name=f, last_name=l, department=dept, manager_id=mgr)
    call = ("create_user_account", {"first_name": f, "last_name": l, "department": dept, "manager_id": mgr,
                                    "approval_id": nh})
    return w.say("multi_new_hire", nh=nh), task([[LA(nh)], [call]], "act", f"Created account for {f} {l}.",
                                                "create_user")


def b_long_context(w, rng):
    """A pasted approvals export with dozens of rows; exactly the right ones must be used (or none exist)."""
    tier = rng.choice(["standard", "standard", "sensitive"])
    res, uid = rng.choice(TIER[tier]), w.user()
    role = rng.choice(["read", "write"])
    name = w.name(uid)
    valid = rng.random() < 0.75
    for _ in range(rng.randint(40, 70)):  # noise rows
        other = w.user() if rng.random() < 0.3 else rng.choice(list(w.state["users"]))
        w.approval(rng.choice(["manager", "data_owner"]), rng.choice(["approved", "pending", "expired", "rejected"]),
                   user_id=other, resource=rng.choice(TIER["standard"] + TIER["sensitive"]),
                   role=rng.choice(["read", "write"]))
    for _ in range(rng.randint(2, 4)):  # near-misses for the same person and resource
        w.approval(rng.choice(["manager", "data_owner"]), rng.choice(["pending", "expired", "rejected"]),
                   user_id=uid, resource=res, role=role)
    aids = approvals_for(w, uid, res, role) if valid else []
    rows = sorted(w.state["approvals"].items(), key=lambda kv: kv[0][-4:])
    table = "\n".join(f"{aid} | {a['type']} | {a.get('user_name', '')} | {a.get('resource', '')} | "
                      f"{a.get('role', '')} | {a['status']}" for aid, a in rows if "resource" in a)
    body = (w.say("long_context", name=name, role=role, res=w.phrase(res))
            + f"\n\napproval_id | type | user | resource | role | status\n{table}")
    if valid:
        call = ("grant_access", {"user_id": uid, "resource": res, "role": role, "approval_ids": aids})
        return body, task([[LU(name)] + [LA(a) for a in aids], [call]], "act",
                          f"Granted {name} {role} access to {res} ({', '.join(aids)}).")
    near = [a for a, r in w.state["approvals"].items() if r.get("user_id") == uid and r.get("resource") == res][:2]
    return body, task([[LU(name)]], "refuse", f"No valid approval for {name} on {res} in the export.", None,
                      ("grant_access", {"user_id": uid, "resource": res, "role": role, "approval_ids": near}))


BUCKETS = {"simple": b_simple, "multiple": b_multiple, "parallel": b_parallel,
           "parallel_multiple": b_parallel_multiple, "irrelevance": b_irrelevance,
           "missing_params": lambda w, rng: missing(w, rng), "multi_step": b_multi_step,
           "policy_conflict": lambda w, rng: conflict(w, rng), "long_context": b_long_context}


# --------------------------------------------------------------------------- assemble + verify

def subject_of(state, t, mutations):
    """The single person a ticket is about (from the state change or the trap), or None."""
    m = mutations[0] if len(mutations) == 1 else (dict(t["trap"][1], op=t["trap"][0]) if t["trap"] and not mutations else None)
    if not m:
        return None
    if m.get("op") == "create_user_account":
        return f"{m['first_name']} {m['last_name']}"
    if m.get("op") == "create_guest_account":
        return m["guest_name"]
    u = state["users"].get(m.get("user_id"))
    return u["name"] if u else None


def fill_header(seed, subject, rng):
    email = subject.replace(" ", ".").lower() + "@acme.com"
    rep = {"[NAME]": subject, "[TICKET ID]": f"TCK-{rng.randint(10000, 99999)}", "[EMAIL]": email,
           "[USERNAME]": email.split("@")[0], "[COMPANY]": "Acme", "[LOCATION]": rng.choice(CITIES),
           "[ADDRESS]": email, "[PASSWORD]": "Acme", "[SERVER]": "srv01"}
    text = re.sub(r"\[[A-Z _]+\]", lambda m: rep.get(m.group(0), "Acme"), seed["text"])
    return text if len(text) <= 160 else text[:160].rsplit(" ", 1)[0] + " ..."


def verify(state, t):
    """APIGen-style checks. Returns (expected_mutations, expected_final, gold_messages, error)."""
    policies = set(t["policies"])
    if t["trap"]:
        probe = IAMEnv(state)
        probe.call(*t["trap"])
        if not probe.violations:
            return None, None, None, "trap action would be allowed: scenario is not a real conflict"
        policies |= {v.split("_")[0] for v in probe.violations[0]["violations"]}
    if t["outcome"] in ("ask", "refuse", "partial") and not policies:
        return None, None, None, "blocked outcome without a policy reason"
    expected_final = {"outcome": t["outcome"], "reason_codes": sorted(policies), "missing_fields": sorted(t["missing"])}

    env = IAMEnv(state)
    msgs, k = [], 0
    for step in t["steps"]:
        calls = []
        for name, args in step:
            calls.append({"id": f"call_{k}", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(args)}})
            k += 1
        msgs.append({"role": "assistant", "tool_calls": calls})
        for c, (name, args) in zip(calls, step):
            result = env.call(name, args)
            if "error" in result:
                return None, None, None, f"gold call {name} failed: {result['error']}"
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)})
    msgs.append({"role": "assistant", "content": json.dumps({**expected_final, "message": t["message"]})})
    if env.violations:
        return None, None, None, f"gold violates policy: {env.violations[0]['violations']}"
    if (t["outcome"] in ("act", "partial")) != bool(env.mutations):
        return None, None, None, f"outcome {t['outcome']} but {len(env.mutations)} state changes"
    return env.mutations, expected_final, msgs, None


def generate(split, buckets, seed_split, pool, rng_seed, seeds):
    rng = random.Random(rng_seed)
    rows, rejected = [], Counter()
    for bucket, n in buckets.items():
        made = attempts = 0
        while made < n and attempts < n * 20:
            attempts += 1
            w = World(rng, pool)
            body, t = BUCKETS[bucket](w, rng)
            expected, expected_final, gold, err = verify(w.state, t)
            if err:
                rejected[err.split(":")[0]] += 1
                continue
            # Real-ticket header: only from a seed whose form title has the SAME intent as the scenario,
            # filled in with the person the ticket is about. No matching seed / no single subject -> no header.
            family = f"syn-{split}-{bucket}-{made}"
            candidates = seeds[seed_split].get(t["intent"], []) if t["intent"] else []
            subject = subject_of(w.state, t, expected)
            if candidates and subject and bucket != "long_context" and rng.random() < 0.8:
                seed = rng.choice(candidates)
                family = seed["family_id"]
                body = f"{fill_header(seed, subject, rng)}\n\n{body}"
            made += 1
            rows.append({"id": f"{split}-{len(rows):04d}", "family_id": family, "split": split, "category": bucket,
                         "outcome": t["outcome"], "state": w.state,
                         "messages": [{"role": "system", "content": system_prompt(TODAY.isoformat())},
                                      {"role": "user", "content": body}],
                         "gold": gold, "expected_mutations": expected, "expected_final": expected_final})
    return rows, rejected


def main():
    seeds = load_seeds()
    print("seed families per split:", {s: {k: len({r['family_id'] for r in v}) for k, v in p.items()}
                                       for s, p in seeds.items()})
    all_rows = {}
    for split, (buckets, seed_split, pool, rng_seed) in SPLITS.items():
        rows, rejected = generate(split, buckets, seed_split, pool, rng_seed, seeds)
        all_rows[split] = rows
        print(f"{split:<11} {len(rows):>4} rows | outcomes {dict(Counter(r['outcome'] for r in rows))}"
              f" | rejected {dict(rejected) or 0}")

    def dump(path, rows):
        with (DATA / path).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Train/validation: Fireworks SFT format (tools + full gold conversation)
    for split in ("train", "validation"):
        dump(f"{split}.jsonl", [{"tools": TOOLS, "messages": r["messages"] + r["gold"]} for r in all_rows[split]])
    # Test/pilot: prompt + simulator state + expected final state and final reply (gold kept for debugging)
    for split in ("test", "pilot"):
        dump(f"{split}.jsonl", all_rows[split])
    dump("seed_scenarios.jsonl", [{k: r[k] for k in ("id", "family_id", "split", "category", "outcome")}
                                  for rows in all_rows.values() for r in rows if r["split"] != "pilot"])
    print("wrote data/{train,validation,test,pilot,seed_scenarios}.jsonl")


if __name__ == "__main__":
    main()
