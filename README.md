# المنصة المالية الذكية — Smart Financial Platform

موقع لتحليل الملفات المالية (Excel / Word / PDF / PowerPoint) وعرض داشبورد تفاعلي وتوليد تقارير PDF.

A platform to upload financial files (Excel / Word / PDF / PowerPoint), analyse them, view an interactive dashboard and generate PDF reports.

## التشغيل — Running

### أسرع طريقة: تشغيل بنقرة واحدة

```bat
scripts\start.bat        :: ويندوز
# أو
./scripts/start.sh       :: macOS / Linux
```

> يثبّت كل شيء، يولّد ملف Excel تجريبياً، ويشغّل الخادمين معاً.

### دليل استكشاف الأخطاء

لديّ خطأ في pip؟ المنفذ مشغول؟ npm install يفشل؟
راجع **docs/RUNBOOK.md** — فيه حلول لعشرة مشاكل شائعة مرقّمة (T1–T10).

### 1) الخلفية (Backend)

```bash
# داخل مجلد المشروع
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2) الواجهة (Frontend)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### 3) نسخة الإنتاج (اختياري)

```bash
cd frontend
npm run build      # تُبنى في frontend/dist
# الخلفية تقدم الواجهة تلقائياً من نفس المنفذ 8000
```

### 4) تسجيل الدخول الاجتماعي الحقيقي (Google / Apple)

تسجيل الدخول الاجتماعي يعمل افتراضياً في **وضع محاكى محلي** (بلا اتصال بمزوّد).
لتفعيل التحقق الحقيقي — الخلفية تتحقق من توقيع ID Token عبر JWKS المزوّد
(التوقيع + exp + aud + iss) — اضبط متغيّري البيئة هذين:

| المتغير | المزوّد | المصدر |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Google | [Google Cloud Console ← Credentials](https://console.cloud.google.com/apis/credentials) |
| `APPLE_CLIENT_ID` | Apple | [Apple Developer ← Identifiers](https://developer.apple.com/account/resources/identifiers) |

**Google**: أنشئ OAuth Client ID من نوع **Web application**، وأضف في
**Authorized JavaScript origins** عناوين الأصل المسموح بها: `http://localhost:5173`
(تطوير) و`http://localhost:8000` (إنتاج) ونطاق موقعك بعد النشر مثل
`https://example.com`، ثم انسخ **Client ID** (عام، لا حاجة إلى Client Secret —
الزر الرسمي GIS يعيد ID Token للخلفية للتحقق منه فقط).

**Apple**: أنشئ **Services ID** وفعّل Sign in with Apple وأضف Return URL، ثم ضع
المعرّف في `APPLE_CLIENT_ID`.

```bash
# Windows (PowerShell)
$env:GOOGLE_CLIENT_ID="xxxx.apps.googleusercontent.com"
$env:APPLE_CLIENT_ID="com.example.web"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# macOS / Linux
GOOGLE_CLIENT_ID=... APPLE_CLIENT_ID=... uvicorn app.main:app --port 8000
```

- عند غياب المتغيرين تبقى أزرار الدخول الاجتماعي محاكاة محلية، وترد نقاط
  `/api/auth/social/google` و`/api/auth/social/apple` بـ 503 إن نوديت مباشرة.
- نقطة `GET /api/auth/social-config` تكشف للواجهة المزوّدين المفعّلين (بـ
  client_id العام) فتُستبدل الأزرار المحاكاة بزر Google الرسمي (Google Identity
  Services) أو زر Apple JS تلقائياً.
- بعد النشر، أضف نطاق الإنتاج إلى Authorized JavaScript origins وإلى Return URL
  لدى Apple، وإلا سيرفض المتصفح فتح نافذة المزوّد.

## الاستخدام

1. افتح `http://localhost:5173` (تطوير) أو `http://localhost:8000` (إنتاج).
2. ارفع ملف Excel / Word / PDF / PowerPoint من صندوق الرفع.
3. اختر تحليلاً من السجل لعرض المؤشرات، النسب، الرسوم البيانية، والتنبؤات.
4. اضغط "تحميل تقرير PDF" للحصول على التقرير بالعربية أو الإنجليزية.
5. زر "بيانات تجريبية" يضيف تحليلاً جاهزاً للتجربة السريعة.

## البنية

```
app/
  main.py        FastAPI: رفع، تحليل، سجل، تقارير
  analyzer.py    محرك التحليل المالي (KPIs, ratios, series, forecast)
  report.py      مولد تقارير PDF بدعم العربية
  database.py    SQLite + SQLAlchemy
  labels.py      نصوص الواجهة ثنائية اللغة
  parsers/       Excel / Word / PDF / PowerPoint extractors
frontend/
  src/           React + Recharts dashboard (AR/EN, RTL/LTR)
scripts/
  make_sample.py ملف Excel تجريبي
  start.bat/.sh  تشغيل بنقرة واحدة
  deliver.py     سير عمل تسليم (deps + TypeScript + pytest)
tests/
  test_analyzer.py  اختبارات محرك التحليل
  test_parsers.py   اختبارات المحللات الأربعة بملفات حقيقية
  test_api.py       اختبارات واجهة REST كاملة
```

## الاختبارات وسير عمل التسليم

```bash
.venv\Scripts\python.exe -m pytest tests -q       # 46 اختباراً
.venv\Scripts\python.exe scripts/deliver.py       # فحص تبعيات + tsc + اختبارات
```

سير التسليم يطبع خلاصة PASS/FAIL لكل مرحلة ويعيد رمز خروج 0 فقط عند النجاح الكامل.

## مقارنة تحليلين

من زر "وضع المقارنة" في الداشبورد: اختر تحليلين (مرجع + مقارن) وشاهد
المؤشرات والنسب والاتجاهات جنباً إلى جنب مع نسب التغير، وحمّل تقرير المقارنة PDF.

نقاط النهاية:

```
GET /api/compare/{base_id}/{target_id}              # دلتا JSON
GET /api/compare/{base_id}/{target_id}/report?lang=ar   # تقرير المقارنة PDF
```

## أوضاع العمل: تحليل / قوائم مالية

الشريط الجانبي فيه مبدّل بأوضاع:
- **📊 تحليل مالي**: رفع ملف وتحليله فورياً (كالسابق).
- **📘 إعداد القوائم المالية**: اختر تحليلاً من السجل ثم ارفع ميزان مراجعة
  (Excel بأعمدة: الحساب / مدين / دائن) فتُبنى القوائم الكاملة:
  قائمة الدخل، قائمة المركز المالي، قائمة التدفقات النقدية حسب الأنشطة
  (تشغيلية/استثمارية/تمويلية مع الإهلاك)، قائمة التغير في حقوق الملكية،
  وإيضاحات الميزانية (أساس الإعداد + تفاصيل كل بند + فحوص التوازن).
  تُعرض في الداشبورد وتُدرج في تقرير PDF بنفس التنسيق، وتُشتق منها
  المؤشرات والنسب تلقائياً (مع فحص توازن الميزان والميزانية والتدفق).

## اسم العملية والملاحظات والتنزيلات

- **اسم مخصص لكل تحليل**: اضغط ✏️ بجانب العنوان لتغيير اسم عملية التحليل؛
  يظهر الاسم في السجل ووضع المقارنة وفي تقرير PDF بدل اسم الملف.
- **ملاحظات**: أضف أو عدّل ملاحظاتك على أي تحليل من لوحة 📝 — تُحفظ في قاعدة
  البيانات وتظهر في تقرير PDF.
- **التنزيلات**: زر 📊 يصدّر نتائج التحليل إلى مصنف Excel منسّق متعدد الأوراق
  (الملخص، الاتجاهات الزمنية، التنبؤات، ملاحظات) بلغة الواجهة واتجاه RTL عند
  العربية، مع ترويسات ملوّنة وتجميد للصف الأول في الاتجاهات وتلوين اتجاهات
  التنبؤ، وزر ⬇ يُنزّل الملف الأصلي المرفوع (للتحليلات المرفوعة بعد تفعيل هذه
  الميزة). تحرير الاسم أو الملاحظات يعيد توليد تقرير PDF تلقائياً في الطلب التالي.
نقاط النهاية:

```
PATCH /api/analyses/{id}                  # تحديث display_name و/أو notes و/أو values
POST /api/analyses/{id}/values/reset      # استعادة القيم المستخرجة الأصلية
GET  /api/analyses/{id}/file              # تنزيل الملف الأصلي المرفوع
GET  /api/analyses/{id}/export?lang=ar    # تصدير النتائج إلى Excel منسّق
```

## تعديل القيم يدوياً

زر «تعديل القيم ✏️» في الداشبورد يفتح محرراً لقيم البنود المستخرجة (الإيرادات،
صافي الربح، الأصول…) — عدّل القيم أو أضف فترات جديدة ثم «حفظ وإعادة الحساب»:
يعاد حساب النسب المالية والتنبؤات من القيم الخام المخزنة، ويظهر تنبيه أن القيم
معدّلة، وزر «استعادة القيم الأصلية» يعيد ما استُخرج من الملف. يبقى الاسم
والملاحظات كما هما، وتُبطل تقارير PDF المخزنة عند أي تعديل.

## الإحصاءات والإشعارات والتشغيل بنقرة

- **📈 الإحصاءات العامة**: زر في الشريط الجانبي يعرض لكل بند مالي أقدم وأحدث
  تحليل فيه وقيمة التغير بينهما (`GET /api/stats`).
- **إشعارات النجاح**: كل عمليات الحفظ (الاسم، الملاحظات، القيم، الاستعادة،
  الرفع، المقارنة، الحذف) تُظهر إشعاراً أخضر مؤقتاً.
- **تشغيل بنقرة مزدوجة**: `start-all.bat` في جذر المشروع يشغّل الخادمين ويفتح
  الداشبورد في المتصفح. يوجد اختصار «المنصة المالية» على سطح المكتب.

## ملاحظات

- كل شيء يعمل محلياً: قاعدة بيانات `financial.db` وملفات مرفوعة في `uploads/`.
- الحد الأقصى لحجم الملف 25MB.
- محرك التحليل يتعرف على بنود شائعة (إيرادات، أرباح، أصول...) بالعربية والإنجليزية.
