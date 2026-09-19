<div align="center">

<img src="../assets/logo.png" alt="RagLeap Core logo" width="120">

# RagLeap Core

**وكلاء الذكاء الاصطناعي المستقلون — وليس مجرد RAG.**

[![license MIT](https://img.shields.io/badge/license-MIT-blue)](../LICENSE) [![46 موظف ذكاء اصطناعي](https://img.shields.io/badge/46-AI%20Employees-brightgreen)](https://github.com/antonyrag/ragleap-core) [![مستقل](https://img.shields.io/badge/Autonomous-brightgreen)](https://github.com/antonyrag/ragleap-core) [![مستضاف ذاتياً](https://img.shields.io/badge/Self--Hosted-brightgreen)](https://github.com/antonyrag/ragleap-core)

[English](../readme.md) · [Afrikaans](README.af.md) · العربية · [Български](README.bg.md) · [বাংলা](README.bn.md) · [Català](README.ca.md) · [Čeština](README.cs.md) · [Cymraeg](README.cy.md) · [Dansk](README.da.md) · [Deutsch](README.de.md) · [Ελληνικά](README.el.md) · [Español](README.es.md) · [Eesti](README.et.md) · [فارسی](README.fa.md) · [Suomi](README.fi.md) · [Français](README.fr.md) · [ગુજરાતી](README.gu.md) · [עברית](README.he.md) · [हिन्दी](README.hi.md) · [Hrvatski](README.hr.md) · [Magyar](README.hu.md) · [Bahasa Indonesia](README.id.md) · [Italiano](README.it.md) · [日本語](README.ja.md) · [ಕನ್ನಡ](README.kn.md) · [한국어](README.ko.md) · [Lietuvių](README.lt.md) · [Latviešu](README.lv.md) · [Македонски](README.mk.md) · [മലയാളം](README.ml.md) · [मराठी](README.mr.md) · [नेपाली](README.ne.md) · [Nederlands](README.nl.md) · [Norsk](README.no.md) · [ਪੰਜਾਬੀ](README.pa.md) · [Polski](README.pl.md) · [Português](README.pt.md) · [Română](README.ro.md) · [Русский](README.ru.md) · [Slovenčina](README.sk.md) · [Slovenščina](README.sl.md) · [Soomaali](README.so.md) · [Shqip](README.sq.md) · [Svenska](README.sv.md) · [Kiswahili](README.sw.md) · [தமிழ்](README.ta.md) · [తెలుగు](README.te.md) · [ไทย](README.th.md) · [Tagalog](README.tl.md) · [Türkçe](README.tr.md) · [Українська](README.uk.md) · [اردو](README.ur.md) · [Tiếng Việt](README.vi.md) · [简体中文](README.zh-cn.md) · [繁體中文](README.zh-tw.md)

</div>

RagLeap Core هو المحرك مفتوح المصدر وراء RagLeap — نظام ذاتي مستضاف يدير أعمالك من مستنداتك الخاصة على خادمك الخاص، دون أي قيود على البائع.

**46 موظف ذكاء اصطناعي حسب الدور:** 9 أدوار عامة أساسية (مدير الذكاء الاصطناعي، السكرتير، الرئيس التنفيذي، المبيعات، الدعم، الموارد البشرية، المالية، التسويق، العمليات) بالإضافة إلى 37 دوراً عالمياً خاصاً بقطاع معين (مجند، وكيل عقارات، استقبال قانوني، استقبال رعاية صحية، وكيل تأمين، والمزيد) — القائمة الكاملة في `core/employees/defaults.py`.

**ما يفعله:**
- ذاكرة ذاتية التعلم مرجحة بالنتائج
- مشغّلات سير العمل التلقائية والتصعيد
- أوضاع الاستقلالية الكاملة / شبه الكاملة
- حلقة التفكير-التصرف-القرار، وليس مجرد الاسترجاع

[البدء السريع](#البدء-السريع) · [الوثائق](https://docs.ragleap.com) · [الموقع الإلكتروني](https://ragleap.com) · [النسخة المستضافة](https://ragleap.com) · [الحزم](https://packages.ragleap.com/)

---

> **لا تخلط بين هذا و`install.ragleap.com`** — ذاك منتج منفصل مدفوع محمي بترخيص. `ragleap-core` (هذا المستودع) مرخص بـ MIT، مجاني تماماً، ولا يتطلب أبداً مفتاح ترخيص.

## التثبيت

```bash
pip install ragleap-rag
```

> ⭐ إذا ساعدك هذا، يرجى النظر في تنجيم المستودع — فهذا يساعد فعلاً على وصول المزيد من الأشخاص إليه.

تفضّل Java؟ `ragleap-rag` متاح أيضاً على Maven Central:
```xml
<dependency>
    <groupId>io.github.antonyrag</groupId>
    <artifactId>ragleap-rag</artifactId>
    <version>0.5.0</version>
</dependency>
```

أضف `ragleap-graph` أيضاً إذا أردت استرجاع الرسم المعرفي المدعوم بـ Neo4j:
```bash
pip install ragleap-rag ragleap-graph
```

## إذا كان روبوت الدردشة RAG يجيب على الأسئلة، فإن RagLeap يدير أعمالك

معظم مشاريع RAG مفتوحة المصدر تعطيك مجموعة أدوات — لا يزال عليك بناء التطبيق، وتوصيل واجهة المستخدم، وإضافة الذاكرة، وربط كل قناة بنفسك. يمنحك RagLeap Core ذكاءً اصطناعياً واحداً عبر WhatsApp وTelegram وDiscord والمكالمات الصوتية، بدلاً من روبوت منفصل لكل قناة.

## الميزات

| | |
|---|---|
| 📄 **استيعاب المستندات** | رفع ملفات PDF والنصوص وصيغ المستندات الشائعة |
| 🔍 **استرجاع RAG** | البحث الشعاعي عبر مستنداتك باستخدام pgvector |
| 💬 **الدردشة مع الاستشهادات** | تشير الإجابات إلى المستند المصدر |
| 🔌 **أحضر مفتاح الذكاء الاصطناعي الخاص بك** | OpenAI أو Gemini أو Anthropic أو أي نقطة نهاية متوافقة مع OpenAI |
| 🌐 **أداة الدردشة الويب** | تضمين أداة دردشة في أي موقع ويب |
| 🐳 **إعداد قائم على Docker** | نشر محلي بأمر واحد |
| 🕸️ **الرسم المعرفي (Neo4j)** | استخراج الكيانات والاسترجاع المعزز بالرسم |
| 🌍 **اكتشاف اللغة** | اكتشاف تلقائي للغة المستند والاستعلام |
| 🔗 **التكاملات** | ربط MySQL وPostgreSQL وMongoDB وواجهات REST وSalesforce وHubSpot وShopify وجداول Google وStripe |
| 🔀 **البحث الهجين** | يجمع الاسترجاع الكثيف (الشعاعي) والمتفرق (النص الكامل) |
| ⚡ **الاستجابات المتدفقة** | تتدفق الإجابات رمزاً بعد رمز |
| 🔁 **خطة احتياطية للمزود** | إعادة المحاولة تلقائياً مع مزود LLM احتياطي |
| 💰 **تقارير استخدام الرموز** | عدد الرموز الفعلي لكل استدعاء من المزود |
| 🧑‍💼 **موظفو الذكاء الاصطناعي** | وكلاء قائمون على الأدوار (46 دوراً افتراضياً) |
| 🛠️ **أنشئ موظف الذكاء الاصطناعي الخاص بك** | حدد دوراً مخصصاً بالكامل عبر `PATCH /employees/{role}` |
| 🔗 **أتمتة سير عمل n8n** | تشغيل webhook بعد رد الذكاء الاصطناعي على WhatsApp/Telegram/Discord |

## البدء السريع

**أسرع طريقة لتجربته** — أمر واحد يتحقق من Docker، يستنسخ المستودع، ويعدّ `.env` لك:

```bash
curl -fsSL https://raw.githubusercontent.com/antonyrag/ragleap-core/main/install.sh | bash
```

(مستخدمو Windows: شغّل هذا في Git Bash، وليس موجه الأوامر أو PowerShell.)

**أو، الطريقة اليدوية:**

```bash
git clone https://github.com/antonyrag/ragleap-core.git
cd ragleap-core
cp .env.example .env
# أضف مفتاح Gemini API إلى .env
docker compose up --build -d
```

المتطلبات: Docker وDocker Compose ومفتاح API من OpenAI أو Google Gemini أو Anthropic.

## الترخيص

MIT © 2026 RagLeap
