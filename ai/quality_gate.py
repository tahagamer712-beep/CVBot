"""Quality gate: mandatory checks AFTER PDF generation, BEFORE delivery.

Wired into build_files(). If gate fails critically, delivery is blocked.
"""
import os


def quality_gate(pdf_path, data, design_key, lang='ar', job_description=None):
    """Run all post-generation checks.

    Returns: (passed: bool, report: dict)
    If critical errors found, passed=False and delivery MUST be blocked.
    """
    report = {
        'checks': {},
        'critical_errors': [],
        'warnings': [],
        'score': None,
    }

    # 1. File exists and non-empty
    if not os.path.exists(pdf_path):
        report['critical_errors'].append('pdf_missing')
        report['checks']['file_exists'] = False
        return False, report
    report['checks']['file_exists'] = True

    size = os.path.getsize(pdf_path)
    report['checks']['file_size'] = size
    if size < 1000:
        report['critical_errors'].append('pdf_empty_or_corrupt')
        return False, report
    if size < 5000:
        report['warnings'].append('pdf_suspiciously_small')

    # 2. Text extraction (readability)
    try:
        from ai.ats_checks import check_readability
        read = check_readability(pdf_path)
        report['checks']['readability'] = read['passed']
        report['checks']['word_count'] = read.get('word_count', 0)
        report['checks']['pages'] = read.get('pages', 0)
        if not read['passed']:
            for issue in read.get('issues', []):
                if issue in ('too_little_text', 'extract_failed'):
                    report['critical_errors'].append(f'readability:{issue}')
                else:
                    report['warnings'].append(f'readability:{issue}')
        extracted_text = read.get('text', '')
    except Exception as e:
        report['critical_errors'].append(f'extraction_failed:{e}')
        return False, report

    # 3. Section completeness
    try:
        from ai.ats_checks import check_sections
        secs = check_sections(extracted_text, lang)
        report['checks']['sections'] = secs
        if secs['missing']:
            report['warnings'].append(f"missing_sections:{secs['missing']}")
    except Exception:
        pass

    # 4. Formatting risks (per template)
    try:
        from ai.ats_checks import check_formatting_risks
        fmt = check_formatting_risks(pdf_path, design_key)
        report['checks']['formatting_risks'] = fmt['risks']
        if fmt['risks']:
            report['warnings'].extend(fmt['risks'])
    except Exception:
        pass

    # 5. Quality score (data-level)
    try:
        from ai.quality_score import score_cv
        qs = score_cv(data, pdf_path, design_key, lang)
        report['score'] = qs['score']
        report['checks']['quality_breakdown'] = qs['breakdown']
        for ce in qs.get('critical_errors', []):
            report['critical_errors'].append(f'quality:{ce}')
    except Exception as e:
        report['warnings'].append(f'quality_score_failed:{e}')

    # 6. Keyword coverage (if JD provided)
    if job_description:
        try:
            from ai.ats_checks import check_keyword_coverage
            kw = check_keyword_coverage(extracted_text, job_description)
            report['checks']['keyword_coverage'] = kw
        except Exception:
            pass

    # 7. Arabic RTL sanity (no tofu in extracted text)
    if lang == 'ar':
        import re
        if re.search(r'[�□]', extracted_text):
            report['critical_errors'].append('arabic_corruption')

    passed = len(report['critical_errors']) == 0
    report['passed'] = passed
    return passed, report


def gate_summary(report, lang='ar'):
    """User-friendly status message (not technical)."""
    if report.get('critical_errors'):
        if lang == 'ar':
            return 'يوجد خطأ في الملف ويجري إصلاحه.'
        return 'There is an error in the file being fixed.'
    if report.get('warnings'):
        if lang == 'ar':
            return 'جاهزة للتقديم بعد المراجعة.'
        return 'Ready for submission after review.'
    if lang == 'ar':
        return 'جاهزة للتقديم.'
    return 'Ready to submit.'
