<div align="center">

<img src="../assets/logo.png" alt="RagLeap Core logo" width="120">

# RagLeap Core

**Outonome KI-Agente — Nie Net RAG Nie.**

[![license MIT](https://img.shields.io/badge/license-MIT-blue)](../LICENSE) [![46 KI-Werknemers](https://img.shields.io/badge/46-AI%20Employees-brightgreen)](https://github.com/antonyrag/ragleap-core) [![Outonoom](https://img.shields.io/badge/Autonomous-brightgreen)](https://github.com/antonyrag/ragleap-core) [![Self-Aangebied](https://img.shields.io/badge/Self--Hosted-brightgreen)](https://github.com/antonyrag/ragleap-core)

[English](../readme.md) · Afrikaans · [العربية](README.ar.md) · [Български](README.bg.md) · [বাংলা](README.bn.md) · [Català](README.ca.md) · [Čeština](README.cs.md) · [Cymraeg](README.cy.md) · [Dansk](README.da.md) · [Deutsch](README.de.md) · [Ελληνικά](README.el.md) · [Español](README.es.md) · [Eesti](README.et.md) · [فارسی](README.fa.md) · [Suomi](README.fi.md) · [Français](README.fr.md) · [ગુજરાતી](README.gu.md) · [עברית](README.he.md) · [हिन्दी](README.hi.md) · [Hrvatski](README.hr.md) · [Magyar](README.hu.md) · [Bahasa Indonesia](README.id.md) · [Italiano](README.it.md) · [日本語](README.ja.md) · [ಕನ್ನಡ](README.kn.md) · [한국어](README.ko.md) · [Lietuvių](README.lt.md) · [Latviešu](README.lv.md) · [Македонски](README.mk.md) · [മലയാളം](README.ml.md) · [मराठी](README.mr.md) · [नेपाली](README.ne.md) · [Nederlands](README.nl.md) · [Norsk](README.no.md) · [ਪੰਜਾਬੀ](README.pa.md) · [Polski](README.pl.md) · [Português](README.pt.md) · [Română](README.ro.md) · [Русский](README.ru.md) · [Slovenčina](README.sk.md) · [Slovenščina](README.sl.md) · [Soomaali](README.so.md) · [Shqip](README.sq.md) · [Svenska](README.sv.md) · [Kiswahili](README.sw.md) · [தமிழ்](README.ta.md) · [తెలుగు](README.te.md) · [ไทย](README.th.md) · [Tagalog](README.tl.md) · [Türkçe](README.tr.md) · [Українська](README.uk.md) · [اردو](README.ur.md) · [Tiếng Việt](README.vi.md) · [简体中文](README.zh-cn.md) · [繁體中文](README.zh-tw.md)

</div>

RagLeap Core is die oopbron-enjin agter RagLeap — 'n self-aangebied, agentiese stelsel wat u besigheid bestuur vanuit u eie dokumente op u eie bediener, sonder enige verskaffer-inperking.

**46 rol-gebaseerde KI-Werknemers:** 9 kern generalis-rolle (KI-Bestuurder, Sekretaresse, HUB, Verkope, Ondersteuning, MH, Finansies, Bemarking, Bedrywighede) plus 37 vertikaal-spesifieke globale rolle (Werwer, Eiendomsagent, Regsinname, Gesondheidsorg-inname, Versekeringsagent, en meer) — volledige lys in `core/employees/defaults.py`.

**Wat dit doen:**
- Selflerend, uitkomsgewing gegewe geheue
- Outomatiese werkvloei-snellers en eskalasie
- Volle / semi-outonomie-modusse
- Dink-handel-besluit-lus, nie net herwinning nie

[Vinnige Begin](#vinnige-begin) · [Dokumentasie](https://docs.ragleap.com) · [Webwerf](https://ragleap.com) · [Aangebied Weergawe](https://ragleap.com) · [Pakkette](https://packages.ragleap.com/)

---

> **Moenie verwar word met `install.ragleap.com` nie** — dit is 'n aparte, betaalde, lisensie-beheerde self-aangebied produk (Gratis vlak met 'n lisensie-sleutel, tot Onderneming). `ragleap-core` (hierdie repo) is MIT-gelisensieer, heeltemal gratis, en vereis nooit 'n lisensiesleutel nie.

## Installeer

```bash
pip install ragleap-rag
```

> ⭐ As dit u help, oorweeg asseblief om die repo te ster — dit help werklik meer mense om dit te vind.

Verkies Java? `ragleap-rag` is ook op Maven Central:
```xml
<dependency>
    <groupId>io.github.antonyrag</groupId>
    <artifactId>ragleap-rag</artifactId>
    <version>0.5.0</version>
</dependency>
```

Voeg `ragleap-graph` ook by as u Neo4j-ondersteunde kennisgraaf-herwinning wil hê:
```bash
pip install ragleap-rag ragleap-graph
```

Voeg `ragleap-vectorstores` ook by as u inpropbare vektorbakpunte buite ragleap-rag se ingeboude ses wil hê:
```bash
pip install ragleap-rag ragleap-vectorstores[chroma]
```

Ontplooi na Kubernetes? `ragleap-ops` stuur lewend-getoetste manifeste en 'n Helm-grafiek vir die volledige stapel:
```bash
pip install ragleap-ops
```

## As 'n RAG-kletsdiens vrae beantwoord, bestuur RagLeap u besigheid

Die meeste oopbron-RAG-projekte gee u 'n gereedskapstel — u moet steeds die program bou, 'n UI bedraad, geheue byvoeg en elke kanaal self koppel. RagLeap Core gee u een KI oor WhatsApp, Telegram, Discord en stemoproepe, in plaas van 'n verskillende losgekoppelde bot per kanaal. Geheue hou oor sessies en kanale aan, sodat dit nie elke keer herken wie 'n kliënt is nie.

## Kenmerke

| | |
|---|---|
| 📄 **Dokumentinvoer** | Laai PDF's, teks en algemene dokumentformate op |
| 🔍 **RAG-herwinning** | Vektordeursoek oor u dokumente via pgvector |
| 💬 **Kletsery met aanhalings** | Antwoorde verwys na die brondokument, nie 'n swart boks nie |
| 🔌 **Bring u eie KI-sleutel** | OpenAI, Gemini, Anthropic, of enige OpenAI-versoenbare eindpunt |
| 🌐 **Webklets-widget** | Inbed 'n klets-widget op enige webwerf |
| 🐳 **Docker-gebaseerde opstelling** | Een-opdrag plaaslike ontplooiing |
| 🕸️ **Kennisgraaf (Neo4j)** | Entiteitsekstrak en grafiekversterkte herwinning langs vektordeursoek |
| 🌍 **Taaldeteksie** | Bespeur outomaties dokument- en navraag-taal, toegepas oor elke kanaal |
| 🔗 **Integrasies** | Koppel MySQL, PostgreSQL, MongoDB, REST API's, Salesforce, HubSpot, Shopify, Google Sheets, Stripe |
| 🔀 **Hibriede soektog** | Kombineer digte (vektor) en yl (volleteks) herwinning via Wederkerige Rang-Samesmelting |
| ⚡ **Stroomreaksies** | Antwoorde stroom token-vir-token in plaas van wag vir die volledige reaksie |
| 🔁 **Verskafferterugval** | Herbeproef outomaties met 'n rugsteun-LLM-verskaffer as die primêre misluk |
| 💰 **Token-gebruikverslagdoening** | Werklike per-oproep token-tellings van die verskaffer |
| 🧑‍💼 **KI-Werknemers** | Rol-gebaseerde agente (46 verstekrolle) met aanhoudende besigheids-konteks-geheue |
| 🛠️ **Bou u eie KI-Werknemer** | Definieer 'n volledig pasgemaakte rol via `PATCH /employees/{role}` |
| 🔗 **n8n werkvloei-outomatisering** | Stuur 'n webhook nadat die KI antwoord op WhatsApp/Telegram/Discord |

## Argitektuur

RagLeap Core is die grondlaag van die volledige RagLeap-platform. Die kernrepositoriestruktuur:

```
ragleap-core/
├── core/                  # RAG-enjin — verdeling, inbedding, herwinning, generasie
│   ├── chunker.py
│   ├── embedding.py       # Gemini-inbeddings
│   ├── retrieval.py       # pgvector kosinusdeursoek
│   ├── generation.py      # 19-verskaffer BYOK generasie
│   ├── ingest.py          # verdeel -> inbed -> stoor pyplyn
│   ├── parsers.py         # PDF/DOCX/TXT teksekstrak
│   ├── employees/         # KI-Werknemers — rolle, besigheidsprofiel, geleerde geheue
│   ├── workflows.py       # n8n werkvloei-outomatisering
│   └── api.py             # FastAPI-program
├── channels/              # Boodskappe + stemkanaalbewerkings
├── db/
│   └── schema.sql
├── examples/
├── docker-compose.yml
└── Dockerfile
```

## Vinnige Begin

**Vinnigste manier om dit te probeer** — een opdrag kontroleer Docker, kloon die repo, en stel `.env` op vir u:

```bash
curl -fsSL https://raw.githubusercontent.com/antonyrag/ragleap-core/main/install.sh | bash
```

(Windows-gebruikers: voer dit uit in Git Bash, nie Opdraggereël of PowerShell nie.)

Die skrip sal pouseer nadat dit gekloon het en u vra om u Gemini API-sleutel by `.env` te voeg.

**Of, die handmatige manier:**

```bash
git clone https://github.com/antonyrag/ragleap-core.git
cd ragleap-core
cp .env.example .env
# voeg u Gemini API-sleutel by .env
docker compose up --build -d
```

Vereistes: Docker, Docker Compose, 'n API-sleutel van OpenAI, Google Gemini, of Anthropic.

## Ondersteunde LLM-Verskaffers (BYOK)

| `LLM_PROVIDER` waarde | Vereiste omgewingsveranderlikes | Notas |
|---|---|---|
| `gemini` (verstek) | `GEMINI_API_KEY` | Kry 'n sleutel by aistudio.google.com/apikey |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | |
| `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL` | |
| `mistral` | `MISTRAL_API_KEY`, `MISTRAL_MODEL` | |
| `groq` | `GROQ_API_KEY`, `GROQ_MODEL` | Gratis vlak beskikbaar |
| `ollama` | `OLLAMA_MODEL` (geen API-sleutel nodig nie) | Self-aangebied |
| `custom` | `CUSTOM_API_KEY`, `CUSTOM_MODEL`, `CUSTOM_BASE_URL` | Enige OpenAI-versoenbare eindpunt |

## Bydrae

RagLeap Core is werkend, getoets en oop vir bydraes nou. Sien [CONTRIBUTING.md](../CONTRIBUTING.md) vir hoe om te begin.

## Lisensie

MIT © 2026 RagLeap
