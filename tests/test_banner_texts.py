"""Report banner text helpers: entity name, subscription badge, period text.

These mirror the UI report banner (الاشتراك / المنشأة / فترة التحليل) and are
shared by the PDF, PPTX and Excel export generators.
"""

from app.main import _entity_name, _period_text, _subscription_label


class _Row:
    """Minimal stand-in for an analyses DB row."""

    def __init__(self, display_name, filename):
        self.display_name = display_name
        self.filename = filename


class _User:
    """Minimal stand-in for an auth user."""

    def __init__(self, subscription="free", plan=None):
        self.subscription = subscription
        self.plan = plan


# ---------------------------------------------------------------- entity name

def test_entity_name_strips_extension_from_filename():
    assert _entity_name(_Row(None, "demo-quarterly-report.xlsx")) == "demo-quarterly-report"


def test_entity_name_keeps_display_name_as_is():
    assert _entity_name(_Row("فحص شامل — تحليل تجريبي", "demo.xlsx")) == "فحص شامل — تحليل تجريبي"


def test_entity_name_handles_extensionless_filename():
    assert _entity_name(_Row(None, "annual-2024")) == "annual-2024"


# ------------------------------------------------------------ subscription

def test_subscription_label_free_user():
    assert _subscription_label(_User("free"), "ar") == "الاشتراك: النسخة المجانية"
    assert _subscription_label(_User("free"), "en") == "Subscription: Free edition"


def test_subscription_label_paid_plans():
    assert _subscription_label(_User("paid", "pro"), "ar") == "الاشتراك: برو"
    assert _subscription_label(_User("paid", "business"), "ar") == "الاشتراك: الأعمال"
    assert _subscription_label(_User("paid", "business"), "en") == "Subscription: Business"
    # grandfathered legacy plans keep carrying the PRO badge
    assert _subscription_label(_User("paid", "yearly"), "en") == "Subscription: PRO"


def test_subscription_label_paid_without_cycle():
    assert _subscription_label(_User("paid", None), "ar") == "الاشتراك: برو"


# ------------------------------------------------------------- period text

def test_period_text_prefers_real_labels():
    result = {"period_labels": ["2023", "2024"]}
    assert _period_text(result, "ar") == "2023 - 2024"
    assert _period_text(result, "en") == "2023 - 2024"


def test_period_text_falls_back_to_metric_count_excluding_liabilities():
    result = {"metrics": {"revenue": [1, 2, 3], "liabilities": [1, 2, 3, 4, 5]}}
    assert _period_text(result, "ar") == "3 فترات"
    assert _period_text(result, "en") == "3 periods"


def test_period_text_counting_singular_and_dual():
    assert _period_text({"metrics": {"revenue": [1]}}, "ar") == "فترة واحدة"
    assert _period_text({"metrics": {"revenue": [1, 2]}}, "ar") == "فترتان"
    assert _period_text({"metrics": {"revenue": [1]}}, "en") == "Single period"


def test_period_text_empty_result_is_unspecified():
    assert _period_text({}, "ar") == "غير محددة"
    assert _period_text({}, "en") == "Not specified"
