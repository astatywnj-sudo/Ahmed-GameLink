<meta name="google-site-verification" content="YZ_Wldp-8mkViZuD2hDvlfP64E7BbJGVUnn-41BGRvk" />

# Ahmed GameLink — Smart Roblox Connectivity Assistant
### Developed by AhmedOmerCode

أداة مفتوحة المصدر لمساعدة المستخدمين على **تشخيص** مشكلات الاتصال بلعبة Roblox:
فحص الإنترنت وDNS وTCP وHTTPS وزمن الاستجابة، مع تقرير عربي مفهوم وحلول
قانونية آمنة حسب نتيجة الفحص.

> **إخلاء مسؤولية:** الأداة لا تقدّم خدمات VPN ولا تدّعي تجاوز كل أنواع الحجب.
> تعرض التشخيص فقط، وتوضّح متطلبات أي حل اتصال بديل قبل استخدامه.

---

## التشغيل السريع

### المتطلبات
- Windows 10/11 (64-bit)
- Python 3.10+ (اختُبر على 3.13)

### التثبيت والتشغيل من المصدر
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### تحويل البرنامج إلى ملف .exe واحد (للأجهزة الضعيفة)

البرنامج يعمل جيدًا على 4GB RAM لأنه لا يستهلك شيئًا في الخمول
(46 MB RAM، صفر threads إضافية). لتوزيعه كملف واحد بدون تثبيت Python:

```bat
:: 1) مرة واحدة فقط: تثبيت PyInstaller داخل البيئة الافتراضية
pip install pyinstaller

:: 2) بناء ملف exe واحد (بدون نافذة سوداء Console)
pyinstaller --noconsole --onefile --name AhmedGameLink main.py

:: 3) الملف الناتج هنا:
::    dist\AhmedGameLink.exe
```

**ملاحظات مهمة حول الـexe:**
- **`--onefile`** ينتج ملفًا واحدًا (~50–60 MB) لكنه يفكّ نفسه في مجلد مؤقت عند
  كل تشغيل — يعني بدء تشغيل أبطأ قليلًا على الأجهزة الضعيفة. إن كان بدء التشغيل
  السريع أهم من "ملف واحد"، استخدم:
  ```bat
  pyinstaller --noconsole --onedir --name AhmedGameLink main.py
  ```
  ثم وزّع مجلد `dist\AhmedGameLink\` كاملًا (البدء أسرع بكثير).
- مكافح الفيروسات قد يرفع إنذارًا كاذبًا على ملفات PyInstaller — هذا شائع،
  ويمكنك إنشاء استثناء أو توقيع الملف لاحقًا.
- الحجم الكبير مصدره PySide6/Qt نفسه؛ لا تعتمدات أخرى خارجية على الإطلاق.
- **لا يحتاج الـexe صلاحيات admin** — نفس سياسة المصدر تمامًا.

### اختبارات قبول كل مرحلة (تعمل من سطر الأوامر)
```bat
python tests\test_phase1.py     :: واجهة + إعدادات + لغة
python tests\test_core_all.py   :: محرك الشبكة + دقة البايتات
python tests\test_phase3.py     :: الفحص الذكي + التقرير + الإلغاء
python tests\test_phase3_ui.py  :: ربط الزر بالواجهة والإغلاق الآمن
python tests\test_phase4.py     :: التشخيص التفصيلي + استهلاك البيانات + Zero-Idle
```

---

## لماذا كل مكتبة خارجية؟ (Spec §6)

| المكتبة | السبب | ما لم يُستخدم عمدًا |
|---|---|---|
| **PySide6** | مطلب المواصفات §3: RTL + Dark Mode احترافي + تبديل لغة فوري. tkinter لا يدعم هذا المستوى | — |
| **PyInstaller** (اختياري — للتوزيع فقط، ليس تبعية وقت تشغيل) | تحويل البرنامج إلى exe واحد دون تثبيت Python | — |
| **لا شيء آخر** | — | **dnspython**: أُسقطت لأن sockets الداخلية لا تسمح بعدّ بايتات DNS بدقة؛ استُبدلت بعميل DNS مصغّر بالمكتبة القياسية (32–144 B مقيسة بالضبط) |

**قرار دقة حاسم:** `ssl.wrap_socket` يسرق الـsocket الخام (`detach`) فتتجاوز
بايتات TLS العدّاد — لذلك بنينا TLS يدويًا بـ`ssl.MemoryBIO + SSLObject`
(`core/tls_socket.py`) بحيث يمر كل بايت مشفّر عبر `CountingSocket` إجباريًا.

**صلاحيات admin:** لا تحتاجها الأداة إطلاقًا — ping عبر `ctypes` + Windows
ICMP API (بلا raw sockets)، ولا تثبيت شهادات أو تعريفات شبكة، ولا تعديل
إعدادات النظام دون موافقة المستخدم.

---

## الخصوصية (Spec §4)

- **لا** تسجيل كلمات مرور أو بيانات حسابات Roblox.
- أي عنوان IP في تقارير التشخيص/التصدير يُقنَّع (`197.35.x.x`) قبل العرض —
  ملف JSON المصدَّر **لا يحتوي أي IPv4 خام** (مُثبت باختبار regex).
- الإعدادات فقط تُخزَّن: `%APPDATA%\AhmedGameLink\settings.json` (اللغة فقط).

## استهلاك الإنترنت والخمول (Spec §2 / §8.1)

- صفر sockets، صفر threads، صفر timers، صفر polling في وضع الخمول —
  **مُثبت باختبار ثابت** يمسح كود `ui/` و`core/` بحثًا عن أي timer.
- لا تحديث تلقائي. لا أي نشاط شبكة إلا بضغطة المستخدم.
- عند إغلاق التطبيق: إلغاء أي فحص + `wait()` على كل threads — لا شيء يبقى
  في الخلفية (§8.2، مُثبت باختبار closeEvent).
- القياس التفصيلي (Network Diagnostics): 3 محاولات ICMP لكل هدف من قائمة
  ثابتة (DNS النظام + 1.1.1.1 + 8.8.8.8 + 9.9.9.9 + خادم Roblox الرئيسي).

## قياس استهلاك البيانات (Spec §8.3)

- **فقط** بايتات هذا البرنامج أثناء الفحوص، مقيسة عند حدود الـSocket.
- صفحة Data Usage تعرض "آخر فحص" و"إجمالي الجلسة" منفصلين — تحديث يدوي/بحدث
  فقط (لا polling).
- **سياسة الأمانة الموثقة:** بايتات الـpayload عند الـSocket (شاملة تشفير TLS)
  تُعد بالضبط؛ ترويسات IP/TCP لكل حزمة (~40–60 B) غير ظاهرة للـSocket API
  فلا تُحسب — سياسة موحدة على كل الفحوص ولا تُقدَّر أبدًا.
- إثبات الدقة: سيرفر خام محلي يقارن العدّاد بالبايتات الفعلية على السلك —
  تطابق تام 100% في الاتجاهين (اختبار test_core_all.py).

---

## هيكل المشروع

```text
main.py                  نقطة الدخول
app_state.py             إعدادات المستخدم (JSON محلي)
core/                    محرك الشبكة — بلا Qt
  config.py              خوادم Roblox + DNS + حدود التوقيت (§8.4)
  data_counter.py        عدّاد البايتات (آخر فحص + جلسة، thread-safe)
  counting_socket.py     غلاف socket يعدّ send/recv بالبايت
  tls_socket.py          TLS يدوي بـMemoryBIO (كل بايت مشفّر يُعدّ)
  http_client.py         HTTP/HTTPS فوق http.client + التعدّاد + الإلغاء
  dns_test.py            استعلام DNS wire-format + قراءة خوادم النظام
  tcp_test.py / icmp_ping.py / internet_check.py / netdiag.py
  diagnostics.py         الـorchestrator: تسلسلي، 45s، إلغاء فوري
  report.py              تصنيف المشكلة + حلول صادقة + تصدير JSON مقنّع
  cancel.py              إلغاء تعاوني + عدواني (إغلاق الـsocket العالق)
  privacy.py             قناع الـIPs
i18n/                    الترجمات ar/en + المحمّل
ui/                      PySide6: الثيم، النافذة، الصفحات الست
worker.py                DiagnosticsWorker + NetDiagWorker (QThread)
tests/                   اختبارات قبول لكل مرحلة
```

## الترخيص
MIT — انظر `LICENSE`.
Developed by [AhmedOmerCode](https://github.com/astatywnj-sudo)
