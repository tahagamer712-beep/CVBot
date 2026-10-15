"""Generate test CVs (AR + EN, all 3 designs) and verify output."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cvgen import generate_pdf, generate_docx, pdf_first_page_png

AR_DATA = {
    'full_name': 'طه محمد حميد',
    'phone': '+9647721535420',
    'email': 'imtah3@gmail.com',
    'address': 'بغداد، الرصافة، العراق',
    'job_title': 'مندوب طبي',
    'summary': 'طالب صيدلة أعمل حاليًا كمندوب طبي في شركة نيوتريك فارما، بخبرة في الترويج الدوائي وإدارة مخزون الصيدليات والعمل الميداني.',
    'experience': [
        {'title': 'مندوب طبي', 'company': 'شركة نيوتريك فارما',
         'period': 'كانون الثاني 2026 - حتى الآن',
         'desc': 'الترويج للمنتجات الدوائية عبر زيارات منتظمة للأطباء والصيادلة\nتحقيق أهداف المبيعات الشهرية لثلاثة أشهر متتالية'},
        {'title': 'ممثل مخزون الصيدليات', 'company': 'شركة ميركاتو',
         'period': 'حزيران 2025 - كانون الثاني 2026',
         'desc': 'إجراء جرد يومي للمخزون في عدة صيدليات\nجمع وتسجيل بيانات المخزون بدقة'},
    ],
    'education': 'بكالوريوس صيدلة — كلية المصطفى الجامعة\nالتخرج المتوقع: 2027',
    'certs': ['دورة المبيعات الطبية', 'دورة مهارات التواصل'],
    'skills': ['الترويج الدوائي', 'إدارة العلاقات', 'العمل الميداني', 'مايكروسوفت إكسل'],
    'languages': ['العربية — ممتاز', 'الإنجليزية — جيد جدًا'],
}

EN_DATA = {
    'full_name': 'Taha Mohammed Hameed',
    'phone': '+9647721535420',
    'email': 'imtah3@gmail.com',
    'address': 'Baghdad, Al-Rusafa, Iraq',
    'job_title': 'Medical Representative',
    'summary': 'Pharmacy student currently working as a Medical Representative at Neutric Pharma, with experience in pharmaceutical promotion and field work.',
    'experience': [
        {'title': 'Medical Representative', 'company': 'Neutric Pharma',
         'period': 'Jan 2026 - Present',
         'desc': 'Promote pharmaceutical products through regular visits to physicians\nAchieved monthly sales targets for three consecutive months'},
        {'title': 'Pharmacy Inventory Representative', 'company': 'Mercato',
         'period': 'Jun 2025 - Jan 2026',
         'desc': 'Conducted daily inventory checks across multiple pharmacies\nCollected and reported inventory data accurately'},
    ],
    'education': 'Bachelor of Pharmacy — Mustafa University College\nExpected Graduation: 2027',
    'certs': ['Medical Sales Training', 'Communication Skills Course'],
    'skills': ['Pharmaceutical Promotion', 'Relationship Management', 'Field Work', 'MS Excel'],
    'languages': ['Arabic — Native', 'English — Advanced'],
}

OUT = os.path.expanduser('~/cvtest')
os.makedirs(OUT, exist_ok=True)
results = []
for lang, data in (('ar', AR_DATA), ('en', EN_DATA)):
    for design in ('formal', 'modern', 'medical'):
        pdf = os.path.join(OUT, f'test_{lang}_{design}.pdf')
        docx = os.path.join(OUT, f'test_{lang}_{design}.docx')
        generate_pdf(data, lang, design, pdf)
        generate_docx(data, lang, design, docx)
        png = os.path.join(OUT, f'test_{lang}_{design}.png')
        pdf_first_page_png(pdf, png)
        psz, dsz = os.path.getsize(pdf), os.path.getsize(docx)
        results.append((pdf, psz, docx, dsz, png))
        print(f'OK {lang}/{design}: pdf={psz}b docx={dsz}b')
print(f'\nGenerated {len(results)} pairs in {OUT}')
