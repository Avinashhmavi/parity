import pytest

from fieldserve_board.extract import extract
from fieldserve_board.noise import classify

TRUST = ("omnimart.example",)


@pytest.mark.parametrize(
    "subject,email,code,name,job",
    [
        ("PM AT OMNIMART TARVENO (K7Q2XR)", "", "K7Q2XR", "Tarveno", "Maintenance"),
        ("INSTALLATION AT OMNIMART VESHOLM", "store.k7q2xr@omnimart.example", "K7Q2XR", "Vesholm", "Installation"),
        ("AMC visit OMNIMART OAKMERE (m3n8pd)", "", "M3N8PD", "Oakmere", "Maintenance"),
        ("CAMERA NOT WORKING at OMNIMART BRIXTON (D1F7GS)", "", "D1F7GS", "Brixton", "Service Call"),
        ("Alarm panel fault - OMNIMART SALTHAM", "store-h2j4lc@omnimart.example", "H2J4LC", "Saltham", "Service Call"),
        ("Quarterly review", "", "", "", "Other"),
        ("DVR offline K7Q2XR", "", "K7Q2XR", "", "Service Call"),
    ],
)
def test_extraction(subject, email, code, name, job):
    got = extract(subject, email)
    assert (got.store_code, got.store_name, got.job_type) == (code, name, job)


def test_plain_six_letter_words_are_not_store_codes():
    assert extract("CAMERA not recording", "").store_code == ""
    assert extract("Visit (ALARMS)", "").store_code == ""


def test_all_letter_code_in_parens_is_believed_only_when_email_agrees():
    assert extract("PM AT OMNIMART X (ABCDEF)", "store.abcdef@omnimart.example").store_code == "ABCDEF"


def test_pm_beats_fault_wording_as_the_brief_defines_pm_as_maintenance():
    assert extract("PM AT OMNIMART X (K7Q2XR) camera not working", "").job_type == "Maintenance"


@pytest.mark.parametrize(
    "subject,email",
    [
        ("Limited time offer: 50% OFF CCTV cameras", "promo@bulkmail.example"),
        ("Weekly newsletter - unsubscribe", "newsletter@deals.example"),
        ("[Auto] Disk space threshold exceeded", "no-reply@monitor.example"),
        ("Delivery Status Notification (Failure)", "mailer-daemon@mail.example"),
        ("Delivery Status Notification (Failure)", "alerts@omnimart.example"),  # automated mailbox, even on a trusted domain
    ],
)
def test_noise_is_detected(subject, email):
    verdict = classify(subject, email, extract(subject, email), TRUST)
    assert verdict.is_noise and verdict.reason


@pytest.mark.parametrize(
    "subject,email",
    [
        ("PM AT OMNIMART TARVENO (K7Q2XR)", "store.k7q2xr@omnimart.example"),
        ("ALERT: camera offline (K7Q2XR)", "alerts@omnimart.example"),  # store code = real work
        ("Please quote for new alarm", "ops@omnimart.example"),
        ("camera not working", "someone@gmail.example"),
        ("Spam-looking but from a store: 50% off", "store.k7q2xr@omnimart.example"),
    ],
)
def test_real_work_is_never_called_noise(subject, email):
    assert not classify(subject, email, extract(subject, email), TRUST).is_noise


def test_real_world_sample_from_the_live_api():
    """First real ticket the API returned (bare store code, code repeated in the requester name)."""
    got = extract("PM At OMNIMART M9GDCU 2ND MEKANZU DVR", "store.m9gdcu@omnimart.example", "OmniMart Rarsi (M9GDCU)")
    assert (got.store_code, got.store_name, got.job_type) == ("M9GDCU", "Rarsi", "Maintenance")


def test_store_code_is_found_from_the_requester_name_alone():
    assert extract("DVR issue", "", "OmniMart Rarsi (M9GDCU)").store_code == "M9GDCU"


def test_bare_code_is_removed_from_a_subject_derived_store_name():
    assert extract("PM AT OMNIMART M9GDCU TARVENO", "", "").store_name == "Tarveno"


# Subjects and senders taken from the first real report (promomail.example is the
# bulk-mail domain; the alert templates carry device/account numbers).
@pytest.mark.parametrize(
    "subject,email,name",
    [
        ("Grow your business with a Premium Listing - offer inside", "zelmefa.deka@promomail.example", ""),
        ("Your listing has 4 potential customers waiting", "x.y@promomail.example", ""),
        ("? This Summer, Sell Smart & Earn More with Huvo", "bofinmin.banfe@mailhost.example", ""),
        ("Re: Lease opportunity at prime commercial location", "a.b@mailhost.example", ""),
        ("DVR OFFLINE ALERT - DEVICE 48213", "store.k7q2xr@omnimart.example", "OmniMart Rarsi (K7Q2XR)"),
        ("MISSED CALL ALERT FROM 9876543210", "store.k7q2xr@omnimart.example", "OmniMart Rarsi (K7Q2XR)"),
        ("Monthly usage quota limit exceeded for account 55120", "billing.bot@mailhost.example", ""),
    ],
)
def test_noise_seen_in_the_real_data(subject, email, name):
    verdict = classify(subject, email, extract(subject, email, name), TRUST)
    assert verdict.is_noise and verdict.reason


@pytest.mark.parametrize(
    "subject,email",
    [
        ("Re: Reminder 5 Outstanding payment from DITI 4 branches", "paso.tonel@mailhost.example"),  # a person chasing a bill
        ("Fw: Complaint Regarding Unnecessary Security Alarm Ringing", "tanve.fanto@mailhost.example"),
        ("327_Quotation for Emergency Stairs VELNA System", "gapazu.mifo@mailhost.example"),
        ("PM at GELSANHU", "varnu.nufar@mailhost.example"),
        ("Service - NVR not working", "habire.bire@mailhost.example"),
        ("PM AT OMNIMART PANGE 4212", "helpa.vefin@mailhost.example"),
        ("Site survey for Velna bas & Norbel", "sinor.dorsi@mailhost.example"),
    ],
)
def test_real_business_emails_from_the_real_data_are_kept(subject, email):
    assert not classify(subject, email, extract(subject, email), TRUST).is_noise
