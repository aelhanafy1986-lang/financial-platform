# دليل التشغيل الكامل وحل المشاكل الشائعة

منصة التحليل المالي — FastAPI + React. اتبع الترتيب بالضبط ولا تتجاوز خطوة.

---

## 0) المتطلبات الأساسية

| الأداة | الإصدار | من أين |
|---|---|---|
| Python | 3.11 أو أحدث | https://www.python.org/downloads/ |
| Node.js | 18 أو أحدث | https://nodejs.org (نسخة LTS) |

**تحقق قبل البدء** (في CMD أو PowerShell):

```bash
python --version
node --version
npm --version
```

> إذا لم يتعرف ويندوز على `python` أو `pip` انظر المشكلة **T1** أدناه.

---

## 1) تشغيل سريع (الطريق الأسهل)

### ويندوز — بنقرة واحدة
```bat
scripts\start.bat
```
السكربت ينشئ البيئة الافتراضية، يثبّت الحزم، يولّد ملف Excel تجريبي، ويشغّل الخادمين معاً. عند نجاحه سترى:
```
=== READY ===
Backend  : http://localhost:8000
Frontend : http://localhost:5173
```
افتح المتصفح على **http://localhost:5173**

### macOS / Linux
```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

### يدوياً (خطوة بخطوة)

**أ) الخلفية:**
```bash
python -m venv .venv
.venv\Scripts\activate            # ويندوز
# source .venv/bin/activate       # macOS / Linux

pip install --upgrade pip
pip install -r requirements.txt
python scripts/make_sample.py     # يولّد sample-financials.xlsx
uvicorn app.main:app --reload --port 8000
```
اترك هذه النافذة مفتوحة.

**ب) الواجهة (نافذة ثانية):**
```bash
cd frontend
npm install
npm run dev
```
افتح **http://localhost:5173** وارفع `sample-financials.xlsx`.

### نسخة الإنتاج (بديل اختياري)
```bash
cd frontend && npm run build      # ينتج frontend/dist
cd .. && uvicorn app.main:app --port 8000
```
الخلفية تقدم الواجهة المبنية تلقائياً من المنفذ 8000 — لا حاجة لـ Vite.

---

## 2) المشاكل الشائعة وحلولها

### T1) "python" أو "pip" غير معروفين
**السبب:** بايثون غير مثبت، أو غير مضاف إلى PATH، أو المثبت من متجر مايكروسوفت هو العدّاد فقط.
**الحل:**
1. ثبّت بايثون من python.org وفي أول شاشة من المثبت **فعّل "Add python.exe to PATH"** ثم Install.
2. أغلق CMD وافتحه من جديد ثم أعد المحاولة.
3. إن بقيت المشكلة جرّب:
```powershell
py --version
py -m pip install -r requirements.txt
```

### T2) "pip install" يفشل أو بطيء جداً (شبكة/جدار حماية)
**الحل:**
```bash
pip install --upgrade pip
pip install -r requirements.txt -i https://pypi.org/simple --no-cache-dir
```
وإن كانت الشبكة تفصل التثبيت في المنتصف:
```bash
pip install fastapi uvicorn python-multipart sqlalchemy openpyxl python-docx pdfplumber python-pptx reportlab arabic-reshaper python-bidi matplotlib
```

### T3) المنفذ مشغول (error while attempting to bind on address / EADDRINUSE)
**الحل الأ:** استخدم منفذاً آخر:
```bash
uvicorn app.main:app --reload --port 8001
```
ثم عدّل البروكسي في `frontend/vite.config.ts` إلى `"http://localhost:8001"`.
وفي `frontend/package.json` غيّر `--port 5173` إلى `5174`.

**الحل ب:** اعرف من يحتل المنفذ ثم أغلقه (PowerShell):
```powershell
netstat -ano | findstr :8000
taskkill /PID <رقم_العملية> /F
```

### T4) `npm install` يفشل على ويندوز
جرّب بالترتيب:
```bash
cd frontend
rmdir /s /q node_modules     # إن وُجد
del package-lock.json
npm cache clean --force
npm install
```
إذا فشل بسبب الشبكة:
```bash
npm install --registry=https://registry.npmjs.org/
```
إذا ظهر خطأ "EPERM / operation not permitted":
- أغلق محرر الملفات/برامج الفحص التي تحتجز مجلد node_modules ثم أعد المحاولة
- شغّل CMD **كمسؤول** (Run as administrator) ثم `npm install`
- تأكد أن المسار الكامل للمشروع لا يحتوي أحرفاً عربية أو رموزاً غير لاتينية

وإذا ظهر خطأ غريب في "gyp / node-gyp" فلا قلق — هذا المشروع لا يحتاج أي حزم أصلية؛ غالباً السبب نسخة Node قديمة، حدّثها إلى LTS 18+.

### T5) `npm run dev` يعمل لكن الصفحة فارغة أو فشل الاتصال بالـ API
**السبب:** الخلفية غير مشغلة أو منفذ آخر.
**الحل:** تأكد أن نافذة uvicorn تعمل وأن آخر سطر فيها:
```
Uvicorn running on http://0.0.0.0:8000
```
ثم افتح http://localhost:8000/api/health في المتصفح — يجب أن ترى `{"status":"ok"}`. إن لم ترها فالمشكلة في الخلفية (انظر T2/T3)، لا في الواجهة.

### T6) رفع ملف يفشل برسالة "unsupported file type"
الصيغ المدعومة: `xlsx` `xlsm` `docx` `pdf` `pptx`.
الصيغ القديمة `xls` `doc` `ppt` غير مدعومة — افتحها في أوفيس و"احفظ باسم" بصيغة XML الحديثة، أو اطلب إضافة الدعم (انظر الملاحظات في README).

### T7) "failed to process file" عند رفع ملف
غالباً الملف تالف أو محمي بكلمة مرور (PDF) أو جدول محمي (Excel). جرّب ملفاً آخر. ولتشخيص أدق شغّل الخلفية بوضع التصحيح:
```bash
uvicorn app.main:app --reload --log-level debug --port 8000
```
واقرأ التفاصيل في نافذة الخلفية.

### T8) تقرير PDF بحروف عربية مقطعة أو معكوسة
الحل مضمّن: `report.py` يبحث عن خط عربي (Amiri / Noto Naskh / Tahoma / DejaVu Sans). على ويندوز سيجد Tahoma تلقائياً. إن ظهرت الحروف سليمة في الواجهة لكن مقطعة في PDF:
1. ثبّت خطاً عربياً (مثل Amiri من google fonts)
2. احذف مجلد `reports/` لإعادة توليد التقرير ثم أعد تحميله

### T9) قاعدة البيانات — أريد البدء من جديد
أوقف الخادمين ثم:
```bash
del financial.db
rmdir /s /q uploads reports
```
وأعد تشغيل الخلفية — تُنشأ قاعدة فارغة.

### T10) المنفذ 8000 يعمل لكن صفحة الواجهة من 5173 تظهر خطأ CORS
في هذا المشروع CORS مفتوح للجميع في `app/main.py`، فإن ظهر خطأ CORS فهذا يعني أنك تصل لمنفذ خلفية مختلف عن البروكسي — عدّل `vite.config.ts` (انظر T3 الحل أ).

---

## 3) كيف أعرف أن كل شيء يعمل؟

| الفحص | المتوقع |
|---|---|
| http://localhost:8000/api/health | `{"status":"ok"}` |
| http://localhost:8000/api/analyses | `[]` أو قائمة تحليلات |
| http://localhost:5173 | صفحة الداشبورد بعنوان "المنصة المالية الذكية" |
| زر "بيانات تجريبية" | بطاقات مؤشرات + رسوم تظهر فوراً |
| رفع sample-financials.xlsx | تحليل جديد في السجل بنِسب مالية وتنبيهات |

---

## 4) بنية المشروع (مرجع سريع)

```
app/
  main.py        # نقاط النهاية REST
  analyzer.py    # محرك التحليل المالي
  report.py      # مولد PDF عربي
  database.py    # SQLite
  parsers/       # excel, word, pdf, pptx
frontend/
  src/           # React dashboard (AR/EN, RTL/LTR)
scripts/
  make_sample.py # ملف Excel تجريبي
  start.bat      # تشغيل بنقرة (ويندوز)
  start.sh       # تشغيل بنقرة (mac/linux)
preview.html     # معاينة مستقلة تعمل بدون خادم
```
