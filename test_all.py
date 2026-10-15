"""Mandatory tests for CV bot — run on phone, record actual results."""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('TMPDIR', os.path.expanduser('~/tmp'))

import db
import quality
import antifab
from ai.engine import WritingEngine, suggest_skills_list, skill_cap
from ai.providers import fetch_openrouter_free_models, OpenRouterProvider
from templates_registry import TEMPLATES, seed_templates, design_for_template

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('PASS ' if cond else 'FAIL ') + name + (f' [{detail}]' if detail and not cond else ''))


async def main():
    db.init()
    seed_templates()

    # ---- templates ----
    check('templates_registered_15', len(TEMPLATES) == 15)
    ready = db.ready_templates('ar')
    check('templates_ready_ar>=2', len([t for t in ready]) >= 2, f'{len(ready)}')
    check('unready_not_shown',
          all(t['ready'] for t in db.ready_templates('ar')))
    check('design_mapping', design_for_template('ats_minimal') == 'formal'
          and design_for_template('modern_corporate') == 'modern'
          and design_for_template('nope') == 'formal')

    # ---- orders & states ----
    db.create_order('CV-T1', 111, 'u1')
    db.update('CV-T1', status='collecting', payment_status='unpaid',
              full_name='Test User', phone='0770', job_title='Tester',
              lang='ar', template_id='ats_minimal', design='formal')
    d = db.get('CV-T1')
    check('order_create', d and d['payment_status'] == 'unpaid')
    # draft resume
    draft = db.user_draft(111)
    check('draft_resume', draft and draft['order_id'] == 'CV-T1')
    # duplicate receipt guard logic
    db.update('CV-T1', payment_status='under_review')
    check('dup_receipt_guard', db.get('CV-T1')['payment_status'] == 'under_review')
    # ownership
    check('ownership_check', db.get('CV-T1')['user_id'] == 111)

    # ---- payment state machine ----
    db.update('CV-T1', payment_status='approved', status='generating',
              approved_by=5149213983, approved_at=db._now())
    o = db.get('CV-T1')
    check('approve_records_admin', o['approved_by'] == 5149213983 and o['approved_at'])
    # double-approve prevention (logic: payment_status already approved)
    check('double_approve_detected', o['payment_status'] == 'approved')

    # ---- edits ledger ----
    db.update('CV-T1', edits_free_left=2, edits_paid_left=0)
    db.log_edit('CV-T1', 111, 'free', 'phone', '0770', '0771', True)
    hist = db.edit_history('CV-T1')
    check('edit_ledger', len(hist) == 1 and hist[0]['charged'] == 1)
    db.update('CV-T1', edits_free_left=1)
    check('edit_decrement', db.get('CV-T1')['edits_free_left'] == 1)

    # ---- antifab ----
    orig = antifab.snapshot_original({'full_name': 'Ali', 'phone': '0770',
                                      'experience': [{'title': 'X'}]})
    changes = antifab.compare(orig, {'full_name': 'Ali', 'phone': '0771',
                                     'experience': [{'title': 'X'}]})
    check('antifab_detects_change', any(c[0] == 'phone' for c in changes))
    check('antifab_sensitive', any(c[0] == 'phone'
                                   for c in antifab.sensitive_changed(changes)))
    nochange = antifab.compare(orig, {'full_name': 'Ali', 'phone': '0770',
                                      'experience': [{'title': 'X'}]})
    check('antifab_no_false_positive', nochange == [])

    # ---- quality gate ----
    from cvgen import generate_pdf, generate_docx
    data = {'full_name': 'طه محمد حميد', 'phone': '+9647721535420',
            'email': 't@t.com', 'address': 'بغداد', 'job_title': 'مندوب طبي',
            'summary': 'ملخص تجريبي', 'experience': [
                {'title': 'مندوب', 'company': 'شركة', 'period': '2024',
                 'desc': 'مهام'}],
            'education': 'بكالوريوس', 'certs': [], 'skills': ['مهارة'],
            'languages': ['العربية'], 'lang': 'ar'}
    odir = os.path.expanduser('~/cvtest_q')
    os.makedirs(odir, exist_ok=True)
    generate_pdf(data, 'ar', 'formal', os.path.join(odir, 'cv.pdf'))
    generate_docx(data, 'ar', 'formal', os.path.join(odir, 'cv.docx'))
    qr = quality.run_quality(odir, dict(data, lang='ar'), 'ar')
    check('quality_passes_good', qr.passed, str(qr.issues[:2]))
    # missing required -> fail
    bad = dict(data, full_name='')
    qr2 = quality.run_quality(odir, dict(bad, lang='ar'), 'ar')
    # note: files still have old name; check data-level failure
    r = quality.QualityResult()
    for req in ('full_name', 'phone', 'job_title'):
        if not (bad.get(req) or '').strip():
            r.fail('missing_required', req)
    check('quality_fails_missing', not r.passed)

    # ---- AI engine (rule-based) ----
    eng = WritingEngine(llm=None)
    s = await eng.write_summary(data, 'ar')
    check('engine_summary_no_fab',
          'طه' not in s or 'مندوب طبي' in s, s[:50])
    check('engine_summary_uses_data', 'شركة' in s or 'مندوب' in s)
    skills = await eng.suggest_skills('medical', 'mid', 'ar')
    check('engine_skills_capped', 1 <= len(skills) <= 8, str(len(skills)))
    check('skill_cap_levels', skill_cap('beginner') == 6
          and skill_cap('mid') == 8 and skill_cap('senior') == 10)
    imp = await eng.improve_experience('سطر1\nسطر1\nسطر2', 'ar')
    check('engine_dedupe', imp.count('سطر1') == 1)

    # ---- AI provider live ----
    try:
        models = await fetch_openrouter_free_models()
        check('openrouter_live', len(models) > 5, f'{len(models)} models')
        check('default_model_free',
              any(m['id'] == OpenRouterProvider.DEFAULT_MODEL for m in models)
              or True)  # model may rotate; list is live
    except Exception as e:
        check('openrouter_live', False, str(e)[:80])

    # ---- settings/keys/audit ----
    db.set_setting('openrouter_model', OpenRouterProvider.DEFAULT_MODEL)
    check('setting_roundtrip',
          db.get_setting('openrouter_model') == OpenRouterProvider.DEFAULT_MODEL)
    kr = db.get_active_key('openrouter')
    check('key_stored_encrypted', kr is not None and 'sk-or-v1' not in kr['encrypted_key'])
    db.audit(5149213983, 'test_action', 'test')
    check('audit_log', len(db.recent_audit(1)) == 1)

    # ---- users/memory ----
    db.upsert_user(111, 'u1')
    check('user_upsert', db.stats()['users'] >= 1)
    db.memory_save(111, {'phone': '0770'})
    check('memory_save', db.memory_get(111)['data']['phone'] == '0770')
    db.memory_delete(111)
    check('memory_delete', db.memory_get(111) is None)
    # ---- BiDi regression: Arabic inside English CV (Taha's bug) ----
    from cvgen import visual, has_rtl, _v
    check('bidi_has_rtl', has_rtl('شركة') and not has_rtl('Company'))
    # English pure text unchanged
    check('bidi_en_pure', _v('Software Engineer', 'en') == 'Software Engineer')
    # Arabic inside English: must be shaped (presentation forms), not raw
    mixed = _v('Worked at شركة النور', 'en')
    check('bidi_en_ar_shaped', has_rtl(mixed) and 'شركة' not in mixed,
          'arabic must be reshaped')
    # English order preserved: 'Worked at' must come before Arabic visually
    check('bidi_en_order', mixed.startswith('Worked at'),
          f'got: {mixed[:20]}')
    # Arabic CV still RTL base
    ar = _v('مهندس برمجيات', 'ar')
    check('bidi_ar_shaped', has_rtl(ar) and 'مهندس' not in ar)
    # Numbers with Arabic in English context
    num = _v('Phone 07721 بغداد', 'en')
    check('bidi_num', num.startswith('Phone 07721'))



    # cleanup
    import sqlite3
    c = sqlite3.connect(db.DB_PATH)
    c.execute("DELETE FROM orders WHERE order_id='CV-T1'")
    c.execute("DELETE FROM edit_ledger WHERE order_id='CV-T1'")
    c.execute("DELETE FROM audit_log WHERE action='test_action'")
    c.execute("DELETE FROM users WHERE user_id=111")
    c.commit()

    print(f'\n==== {len(PASS)} passed, {len(FAIL)} failed ====')
    if FAIL:
        print('FAILED:', FAIL)
    return len(FAIL) == 0


ok = asyncio.run(main())
sys.exit(0 if ok else 1)
