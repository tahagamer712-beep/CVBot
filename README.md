<div align="center">

# 🤖📄 CVBot

### Commercial Telegram Bot for Professional, ATS-Friendly CVs

**بوت تيليجرام تجاري متكامل لإنشاء السير الذاتية الاحترافية — من المحادثة إلى التسليم**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-v21-green?logo=telegram)](https://github.com/python-telegram-bot/python-telegram-bot)
[![ReportLab](https://img.shields.io/badge/PDF-ReportLab-orange)](https://www.reportlab.com/)
[![SQLite](https://img.shields.io/badge/DB-SQLite-lightgrey?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Tests](https://img.shields.io/badge/tests-36%20passed-brightgreen)](tests/)
[![License](https://img.shields.io/badge/license-Proprietary-red)](LICENSE)
[![Arabic](https://img.shields.io/badge/Arabic-RTL%20✓-9cf)](README.md)

[Features](#-features) • [Quick Start](#-quick-start) • [Installation](#-installation) • [Configuration](#️-configuration) • [Documentation](#-documentation) • [Contributing](#-contributing)

</div>

---

## 📖 About

**CVBot** is a production-ready commercial Telegram bot that sells professional CVs. A customer chats with the bot, answers guided questions in Arabic or English, previews a watermarked design, pays manually, and receives a final **PDF + editable Word document + free cover letter** — all inside Telegram, no website needed.

> **نبذة عربية:** بوت تيليجرام تجاري يبيع السير الذاتية الاحترافية (5,000 د.ع للسيرة).
> الزبون يجاوب على أسئلة تفاعلية، يشوف معاينة بعلامة مائية، يدفع عبر كي كارد،
> وبعد موافقة الإدارة يستلم PDF نهائي + ملف Word قابل للتعديل + خطاب تقديم مجاني.

---

## ✨ Features

### For customers
- 🗣️ **Conversational CV builder** — step-by-step guided questions (Arabic / English)
- 🤖 **AI-written professional summary** — tailored to the target job title
- 🎨 **15 templates** — ATS-safe single-column layouts + modern designs
- 🌍 **Full Arabic support** — correct RTL, letter shaping, Arabic-safe bullets
- 🖼️ **Optional profile photo** — automatic 1:1 crop on upload
- 📥 **PDF/DOCX import** — reads an old CV and pre-fills the form
- 👀 **Watermarked preview** before payment
- 💳 **Manual Keycard payment** with admin receipt review
- 📝 **Free cover letter** with every order
- 🔁 **2 free edits** after delivery; system-bug fixes free forever

### For the owner (admin center)
- 📊 **Dashboard** — orders, revenue, conversion stats
- 📢 **Broadcast system** — message all users
- 🔒 **Force-subscribe** — require channel membership
- 🎁 **Referral system** — user invites with tracking
- 👋 **Welcome system** — onboarding messages
- 🛡️ **Mandatory quality gate** — every file is auto-checked before delivery
- 🚫 **Anti-fabrication guard** — user data is ground truth; nothing is invented

---

## 🚀 Quick Start

```bash
git clone https://github.com/tahagamer712-beep/CVBot.git
cd CVBot
pip install -r requirements.txt

# 1. Configure secrets (never commit this file!)
cp .env.example .env   # then fill in real values
chmod 600 .env

# 2. Fonts: download fonts.zip from the repo root and EXTRACT it
#    so the files land at fonts/*.ttf  (required for PDF generation)

# 3. Run
bash run_cvbot.sh
```

Open Telegram, talk to your bot, send `/start` — done. 🎉

---

## 🔧 Installation

### Requirements
- Python 3.10+
- `pip install -r requirements.txt`
- Arabic TTF fonts in `fonts/` (see below)

### Dependencies
| Package | Purpose |
|---|---|
| `python-telegram-bot` ≥21 | Bot framework & conversations |
| `reportlab` | PDF generation with RTL Arabic |
| `arabic-reshaper` | Arabic letter shaping |
| `pillow` | Photo upload & auto-crop |
| `pypdf` | PDF import / text extraction |
| `httpx` | AI provider calls (OpenRouter) |
| `python-dotenv` | `.env` config loading |

### Fonts setup ⚠️
PDF generation needs the Arabic fonts. They ship as **`fonts.zip` in the repo root**
(GitHub can't diff binaries, so they're zipped):

1. Download `fonts.zip`
2. **Extract it** — the files must land at:
   ```
   fonts/Amiri-Regular.ttf
   fonts/Amiri-Bold.ttf
   fonts/Cairo-Regular.ttf
   fonts/Cairo-Bold.ttf
   fonts/CairoFull-Regular.ttf
   ```
3. Without this step, Arabic PDFs will fail to build.

---

## ⚙️ Configuration

Create `.env` in the project root (see `.env.example`):

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | ✅ | Numeric Telegram user ID of the admin |
| `KEYCARD_NUMBER` | ✅ | Keycard number customers pay to |
| `SECRET_KEY` | ✅ | Long random string for internal signing |

> 🔐 `.env`, `*.db`, `orders/` and `*.session` are git-ignored by default.
> Never commit secrets, customer data, or order files.

---

## 🖥️ Running

### Direct
```bash
bash run_cvbot.sh     # supervisor: restarts on crash (5s backoff + circuit breaker)
```

### tmux (recommended for servers)
```bash
tmux new-session -d -s cvbot 'bash run_cvbot.sh'
```

### Android / Termux 📱
This bot is designed to run 24/7 on a phone via Termux — zero hosting cost:
```bash
pkg install python git
# ...follow Installation above, then:
bash run_cvbot.sh
```

---

## 🗂️ Project Structure

```
CVBot/
├── bot.py               # Main bot logic & conversation handlers
├── cvgen.py             # PDF generation (ReportLab + RTL)
├── docxgen.py           # DOCX generation (lightweight WordprocessingML)
├── ats_template.py      # ATS-safe templates
├── modern_templates.py  # Modern design templates
├── templates_registry.py# Template catalog (15 templates)
├── coverletter.py       # Cover letter generator
├── cvimport.py          # PDF/DOCX import & auto-fill
├── photo.py             # Photo upload & 1:1 crop
├── db.py                # SQLite data layer
├── ai/                  # AI engine: quality gate, scoring, anti-fabrication
│   ├── quality_gate.py  # Mandatory pre-delivery checks
│   ├── antifab.py       # Fabrication / test-data detection
│   └── ...
├── admin_center.py      # Admin dashboard
├── broadcast_sys.py     # Broadcast messaging
├── referral_sys.py      # Referral tracking
├── force_sub.py         # Forced channel subscription
├── welcome_sys.py       # Onboarding & welcome flows
├── utils/security.py    # Security helpers
├── fonts/               # TTF fonts (from fonts.zip — see setup)
├── docs/                # Policies, FAQ, launch docs
├── tests/               # Test suite
├── requirements.txt
└── run_cvbot.sh         # Process supervisor
```

---

## 🧪 Testing

```bash
python3 test_all.py
# ✅ 36 passed, 0 failed
```

Covers: Arabic BiDi handling, text extraction, template integrity,
and the delivery quality gate. Run before every release.

---

## 🔒 Security Model

- **User data is ground truth** — the bot never invents information.
- **No final file** is delivered before payment approval **and** a passed quality check.
- The quality gate **blocks** any file containing test data, leaks, or corruption.
- Secrets live in `.env` only — never in code, logs, or git history.
- Customer databases and order files are **never** committed.

---

## 🗺️ Roadmap

- [ ] More ATS templates
- [ ] English cover letters
- [ ] Online payment gateway (optional)
- [ ] Multi-admin roles

---

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repo and create a feature branch
2. Run `python3 test_all.py` — all tests must pass
3. Never commit `.env`, `*.db`, or customer data
4. Open a Pull Request with a clear description

---

## 📄 License

Proprietary — all rights reserved.  
This is a commercial product; redistribution without permission is prohibited.

---

## 📬 Support

- 📖 [FAQ](docs/FAQ.md) • [Refund Policy](docs/POLICY-refund.md) • [Restore Guide](docs/RESTORE.md)
- 🐛 Found a bug? [Open an issue](https://github.com/tahagamer712-beep/CVBot/issues)

<div align="center">
Made with ❤️ for Iraqi job seekers — صُنع بحب للباحثين عن العمل في العراق
</div>
