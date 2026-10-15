"""Test personas: synthetic CV data for evaluation.
All data is fictional and marked for testing only.
"""
PERSONAS = [
    # 1. Fresh pharmacy graduate
    {
        'id': 'P01', 'role': 'fresh_pharmacy_graduate', 'lang': 'ar',
        'data': {
            'full_name': 'Test Persona Alpha', 'job_title': 'صيدلي حديث التخرج',
            'phone': '07000000001', 'email': 'test.alpha@example.test',
            'summary': ('خريج صيدلة حديث بتقدير جيد جداً، أتممت التدريب الصيفي في صيدلية مجتمعية '
                        'ومشروع تخرج حول التفاعلات الدوائية. أبحث عن فرصة لتطبيق المعرفة الأكاديمية.'),
            'experience': [],
            'education': 'بكالوريوس صيدلة، جامعة بغداد، 2026',
            'skills': ['المعرفة الدوائية', 'التواصل مع المرضى', 'إدارة المخزون'],
            'training': 'تدريب صيفي: صيدلية مجتمعية (3 أشهر)',
        }
    },
    # 2. Medical representative
    {
        'id': 'P02', 'role': 'medical_rep', 'lang': 'en',
        'data': {
            'full_name': 'Test Persona Beta', 'job_title': 'Medical Representative',
            'phone': '07000000002', 'email': 'test.beta@example.test',
            'summary': ('Medical representative with 3 years of pharmaceutical sales experience, '
                        'skilled in physician engagement and territory management.'),
            'experience': [
                {'title': 'Medical Representative', 'company': 'TestPharma Co',
                 'period': '2021 - 2024',
                 'desc': 'Conducted daily physician visits\nAchieved sales targets'},
            ],
            'education': 'BSc Pharmacy, 2021',
            'skills': ['Communication', 'Negotiation', 'Territory Management'],
        }
    },
    # 3. Accountant (fresh)
    {
        'id': 'P03', 'role': 'accountant_fresh', 'lang': 'ar',
        'data': {
            'full_name': 'Test Persona Gamma', 'job_title': 'محاسب حديث التخرج',
            'phone': '07000000003', 'email': 'test.gamma@example.test',
            'summary': 'خريج محاسبة بمهارات في Excel وإعداد التقارير المالية.',
            'experience': [],
            'education': 'بكالوريوس محاسبة، 2025',
            'skills': ['Excel', 'التقارير المالية', 'الدقة'],
        }
    },
    # 4. Software developer
    {
        'id': 'P04', 'role': 'software_dev', 'lang': 'en',
        'data': {
            'full_name': 'Test Persona Delta', 'job_title': 'Software Developer',
            'phone': '07000000004', 'email': 'test.delta@example.test',
            'summary': ('Software developer with 2 years experience in Python and web development. '
                        'Built REST APIs and contributed to open-source projects.'),
            'experience': [
                {'title': 'Junior Developer', 'company': 'TestSoft',
                 'period': '2023 - 2025',
                 'desc': 'Developed REST APIs\nWrote unit tests'},
            ],
            'education': 'BSc Computer Science, 2023',
            'skills': ['Python', 'Django', 'PostgreSQL', 'Git'],
        }
    },
    # 5. Civil engineer
    {
        'id': 'P05', 'role': 'civil_engineer', 'lang': 'ar',
        'data': {
            'full_name': 'Test Persona Epsilon', 'job_title': 'مهندس مدني',
            'phone': '07000000005', 'email': 'test.epsilon@example.test',
            'summary': 'مهندس مدني بخبرة 5 سنوات في إدارة مشاريع البناء.',
            'experience': [
                {'title': 'مهندس موقع', 'company': 'شركة البناء التجريبية',
                 'period': '2020 - 2025',
                 'desc': 'إشراف على تنفيذ المشاريع\nإدارة فرق العمل'},
            ],
            'education': 'بكالوريوس هندسة مدنية، 2020',
            'skills': ['AutoCAD', 'إدارة المشاريع', 'حساب الكميات'],
        }
    },
    # 6. Nurse
    {
        'id': 'P06', 'role': 'nurse', 'lang': 'en',
        'data': {
            'full_name': 'Test Persona Zeta', 'job_title': 'Registered Nurse',
            'phone': '07000000006', 'email': 'test.zeta@example.test',
            'summary': 'Compassionate nurse with 4 years of hospital experience.',
            'experience': [
                {'title': 'Staff Nurse', 'company': 'Test General Hospital',
                 'period': '2022 - 2026',
                 'desc': 'Patient care and monitoring\nMedication administration'},
            ],
            'education': 'BSc Nursing, 2022',
            'skills': ['Patient Care', 'Emergency Response', 'Documentation'],
        }
    },
    # 7. Graphic designer
    {
        'id': 'P07', 'role': 'graphic_designer', 'lang': 'ar',
        'data': {
            'full_name': 'Test Persona Eta', 'job_title': 'مصمم جرافيك',
            'phone': '07000000007', 'email': 'test.eta@example.test',
            'summary': 'مصمم جرافيك بخبرة في الهوية البصرية وتصميم السوشيال ميديا.',
            'experience': [
                {'title': 'مصمم جرافيك', 'company': 'وكالة إبداعية',
                 'period': '2022 - 2026',
                 'desc': 'تصميم هويات بصرية\nإدارة حسابات سوشيال ميديا'},
            ],
            'education': 'بكالوريوس تصميم، 2022',
            'skills': ['Photoshop', 'Illustrator', 'الإبداع'],
        }
    },
    # 8. Data analyst
    {
        'id': 'P08', 'role': 'data_analyst', 'lang': 'en',
        'data': {
            'full_name': 'Test Persona Theta', 'job_title': 'Data Analyst',
            'phone': '07000000008', 'email': 'test.theta@example.test',
            'summary': 'Data analyst skilled in SQL, Python, and dashboard creation.',
            'experience': [
                {'title': 'Data Analyst', 'company': 'Test Analytics',
                 'period': '2023 - 2026',
                 'desc': 'Built dashboards\nAutomated reports'},
            ],
            'education': 'BSc Statistics, 2023',
            'skills': ['SQL', 'Python', 'Tableau', 'Excel'],
        }
    },
    # 9. HR officer
    {
        'id': 'P09', 'role': 'hr_officer', 'lang': 'ar',
        'data': {
            'full_name': 'Test Persona Iota', 'job_title': 'موظف موارد بشرية',
            'phone': '07000000009', 'email': 'test.iota@example.test',
            'summary': 'موظف موارد بشرية بخبرة في التوظيف وإدارة شؤون الموظفين.',
            'experience': [
                {'title': 'موظف HR', 'company': 'شركة تجريبية',
                 'period': '2021 - 2026',
                 'desc': 'إجراءات التوظيف\nمتابعة الحضور والإجازات'},
            ],
            'education': 'بكالوريوس إدارة أعمال، 2021',
            'skills': ['التوظيف', 'التواصل', 'إدارة الوقت'],
        }
    },
    # 10. Career changer (negative: unrelated skills)
    {
        'id': 'P10', 'role': 'career_changer', 'lang': 'en',
        'data': {
            'full_name': 'Test Persona Kappa', 'job_title': 'Aspiring Data Analyst',
            'phone': '07000000010', 'email': 'test.kappa@example.test',
            'summary': 'Former teacher transitioning to data analysis with online certifications.',
            'experience': [
                {'title': 'Teacher', 'company': 'Test School',
                 'period': '2018 - 2024',
                 'desc': 'Taught mathematics\nManaged classroom'},
            ],
            'education': 'BSc Mathematics, 2018; Data Analysis Certificate, 2025',
            'skills': ['SQL', 'Excel', 'Teaching', 'Communication'],
        }
    },
    # 11. Negative: missing contact
    {
        'id': 'P11', 'role': 'negative_missing_contact', 'lang': 'en',
        'data': {
            'full_name': 'Test Persona Lambda', 'job_title': 'Developer',
            'phone': '', 'email': '',
            'summary': 'Developer seeking opportunities.',
            'experience': [],
            'education': 'BSc CS',
            'skills': ['Python'],
        }
    },
    # 12. Negative: very long content
    {
        'id': 'P12', 'role': 'negative_too_long', 'lang': 'en',
        'data': {
            'full_name': 'Test Persona Mu With A Very Long Name That Exceeds Normal',
            'job_title': 'Senior Experienced Professional',
            'phone': '07000000012', 'email': 'test.mu.very.long.email.address@example.test',
            'summary': ' '.join(['Experienced professional with extensive background.'] * 20),
            'experience': [
                {'title': f'Role {i}', 'company': f'Company {i}',
                 'period': f'{2010+i} - {2011+i}',
                 'desc': 'Did many things\nAchieved many results\nLed teams'}
                for i in range(8)
            ],
            'education': 'Multiple degrees from various institutions over many years',
            'skills': [f'Skill{i}' for i in range(20)],
        }
    },
]

# Mark all as synthetic
for p in PERSONAS:
    p['data']['_synthetic'] = True
    p['data']['_test_id'] = p['id']
